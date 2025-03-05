import os
import sqlite3
import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Deine DB-Funktionen, Routen-Utils etc.
from webapp.db import get_connection
from webapp.routes_utils import (
    create_signup,
    cancel_signup,
    get_slots_for_role,
    count_signups
)

load_dotenv()
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

EVENT_CHANNEL_ID = None

# NEU: Hier sammeln wir Events, die aktualisiert werden müssen
update_queue = set()

#########################################
# 1) Spalten anlegen, falls sie fehlen
#########################################

def ensure_event_columns_exist():
    """
    Prüft, ob bestimmte Spalten existieren, 
    und legt sie ggf. an:
      - info_message_id, allies_message_id, axis_message_id, posted_in_discord
      - pw_sent
    """
    conn = get_connection()
    c = conn.cursor()

    # Block A: info_message_id & Co
    try:
        c.execute("SELECT info_message_id FROM events LIMIT 1")
    except sqlite3.OperationalError:
        print("[ensure_event_columns_exist] info_message_id fehlt -> lege Spalten an ...")
        try:
            c.execute("ALTER TABLE events ADD COLUMN info_message_id TEXT")
            c.execute("ALTER TABLE events ADD COLUMN allies_message_id TEXT")
            c.execute("ALTER TABLE events ADD COLUMN axis_message_id TEXT")
            c.execute("ALTER TABLE events ADD COLUMN posted_in_discord INTEGER DEFAULT 0")
            conn.commit()
            print("[ensure_event_columns_exist] info/allies/axis_message_id + posted_in_discord angelegt.")
        except Exception as e:
            print(f"[ensure_event_columns_exist] Fehler: {e}")

    # Block B: pw_sent
    try:
        c.execute("SELECT pw_sent FROM events LIMIT 1")
    except sqlite3.OperationalError:
        print("[ensure_event_columns_exist] pw_sent fehlt -> anlegen ...")
        try:
            c.execute("ALTER TABLE events ADD COLUMN pw_sent INTEGER DEFAULT 0")
            conn.commit()
            print("[ensure_event_columns_exist] Spalte pw_sent=0 angelegt.")
        except Exception as e:
            print(f"[ensure_event_columns_exist] Fehler bei ALTER TABLE pw_sent: {e}")

    conn.close()

#########################################
# 2) Kanal-ID aus bot_state laden/speichern
#########################################

def load_event_channel_id():
    global EVENT_CHANNEL_ID
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT event_channel_id FROM bot_state WHERE id=1")
    row = c.fetchone()
    conn.close()
    if row and row[0]:
        EVENT_CHANNEL_ID = int(row[0])
        print(f"[load_event_channel_id] EVENT_CHANNEL_ID={EVENT_CHANNEL_ID}")
    else:
        print("[load_event_channel_id] Kein event_channel_id in bot_state (id=1) gefunden.")

def save_event_channel_id(channel_id: int):
    global EVENT_CHANNEL_ID
    EVENT_CHANNEL_ID = channel_id
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE bot_state SET event_channel_id=? WHERE id=1", (str(channel_id),))
    conn.commit()
    conn.close()
    print(f"[save_event_channel_id] EVENT_CHANNEL_ID={EVENT_CHANNEL_ID} in DB gespeichert.")

#########################################
# DB-/ Hilfsfunktionen
#########################################

def get_event_dict(event_id: int) -> dict:
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM events WHERE id=?", (event_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return {}
    cols = [desc[0] for desc in c.description]
    data= dict(zip(cols,row))
    conn.close()
    return data

def get_signups_active(event_id: int):
    conn= get_connection()
    c= conn.cursor()
    c.execute("""
        SELECT user_name, seite, rolle
        FROM signups
        WHERE event_id=?
          AND status='active'
        ORDER BY id ASC
    """,(event_id,))
    rows= c.fetchall()
    conn.close()
    return rows

def user_already_signedup(event_id: int, user_id: str) -> bool:
    conn= get_connection()
    c= conn.cursor()
    c.execute("""
        SELECT COUNT(*)
        FROM signups
        WHERE event_id=? AND user_id=? AND status IN ('active','waiting')
    """,(event_id,user_id))
    count= c.fetchone()[0]
    conn.close()
    return (count>0)

def chunk(lst, size):
    return [lst[i:i+size] for i in range(0,len(lst),size)]

def german_datetime_format(dt_str):
    if not dt_str:
        return ""
    try:
        from datetime import datetime
        dt= datetime.fromisoformat(dt_str)
        return dt.strftime("%d.%m.%Y %H:%M")
    except:
        return str(dt_str)

#########################################
# EMBED-Bau-Funktionen: Info, Allies, Axis
#########################################

def build_info_embed(evt: dict) -> discord.Embed:
    nm  = evt.get("name","(NoName)")
    dtb = german_datetime_format(evt.get("date_briefing"))
    dts = german_datetime_format(evt.get("date_eventstart"))
    dtg = german_datetime_format(evt.get("date_gamestart"))
    srv = evt.get("server_info","")
    desc= evt.get("description","")

    embed= discord.Embed(title=f"Event: {nm}", color=discord.Color.blue())
    embed.set_thumbnail(url="https://via.placeholder.com/80x80.png?text=Event")

    lines= (
        f"**Briefing (Anmeldeschluss):** {dtb}\n"
        f"**Eventstart:** {dts}\n"
        f"**Spielstart:** {dtg}"
    )
    embed.add_field(name="Termine", value=lines, inline=False)

    if srv.strip():
        embed.add_field(name="Server", value=f"{srv}\n(PW nach Briefing per DM)", inline=False)
    if desc.strip():
        embed.add_field(name="Beschreibung", value=desc, inline=False)

    # Footer: Anmeldeschluss?
    dtb_iso= evt.get("date_briefing")
    if dtb_iso:
        from datetime import datetime
        try:
            dt_b= datetime.fromisoformat(dtb_iso)
            if datetime.now() >= dt_b:
                embed.set_footer(text="Briefing hat begonnen => Anmeldeschluss!")
            else:
                embed.set_footer(text="Anmeldung noch offen, bis zum Briefing!")
        except:
            embed.set_footer(text="Fehler beim Parsing vom Briefing-Datum!")
    else:
        embed.set_footer(text="Kein Briefing -> Keine automatische Schließung.")

    return embed

def build_allies_embed(evt: dict) -> discord.Embed:
    evt_id= evt["id"]
    embed= discord.Embed(title=f"Alliierte (Event {evt_id})",color=discord.Color.blue())
    embed.set_thumbnail(url="https://via.placeholder.com/80x80.png?text=Allies")

    signups= get_signups_active(evt_id)
    roles_map= {"inf":[],"tank":[],"sniper":[],"commander":[]}
    for (uname, seite, rolle) in signups:
        if seite=="allies" and rolle in roles_map:
            roles_map[rolle].append(uname)

    role_emoji= {"inf":"🪖","tank":"🛡️","sniper":"🎯","commander":"⭐"}
    roles_order= ["inf","tank","sniper","commander"]
    label_map= {"inf":"Infanterie","tank":"Panzer","sniper":"Sniper","commander":"Commander"}
    sq_size= {"inf":6,"tank":3,"sniper":2,"commander":1}

    total_allies= 0
    for r in roles_order:
        players= roles_map[r]
        total_allies+= len(players)
        squads= chunk(players, sq_size[r])
        if squads:
            for idx, sq in enumerate(squads,start=1):
                sq_name= f"{role_emoji[r]} {label_map[r]}-Squad #{idx}"
                sq_text= "\n".join(f"- {p}" for p in sq) if sq else "(leer)"
                embed.add_field(name=sq_name, value=sq_text, inline=True)
        else:
            embed.add_field(name=f"{role_emoji[r]} {label_map[r]}", value="Keine Spieler", inline=True)

    if total_allies>0:
        total_allies-=1
    embed.set_footer(text=f"Allies - Gesamt: {total_allies} (1 Admin abgezogen)")
    return embed

def build_axis_embed(evt: dict) -> discord.Embed:
    evt_id= evt["id"]
    embed= discord.Embed(title=f"Achsenmächte (Event {evt_id})", color=discord.Color.red())
    embed.set_thumbnail(url="https://via.placeholder.com/80x80.png?text=Axis")

    signups= get_signups_active(evt_id)
    roles_map= {"inf":[],"tank":[],"sniper":[],"commander":[]}
    for (uname,seite,rolle) in signups:
        if seite=="axis" and rolle in roles_map:
            roles_map[rolle].append(uname)

    role_emoji= {"inf":"🪖","tank":"🛡️","sniper":"🎯","commander":"⭐"}
    roles_order= ["inf","tank","sniper","commander"]
    label_map= {"inf":"Infanterie","tank":"Panzer","sniper":"Sniper","commander":"Commander"}
    sq_size= {"inf":6,"tank":3,"sniper":2,"commander":1}

    total_axis= 0
    for r in roles_order:
        players= roles_map[r]
        total_axis+= len(players)
        squads= chunk(players, sq_size[r])
        if squads:
            for idx, sq in enumerate(squads, start=1):
                sq_name= f"{role_emoji[r]} {label_map[r]}-Squad #{idx}"
                sq_text= "\n".join(f"- {u}" for u in sq) if sq else "(leer)"
                embed.add_field(name=sq_name, value=sq_text, inline=True)
        else:
            embed.add_field(name=f"{role_emoji[r]} {label_map[r]}", value="Keine Spieler", inline=True)

    if total_axis>0:
        total_axis-=1
    embed.set_footer(text=f"Axis - Gesamt: {total_axis} (1 Admin abgezogen)")
    return embed

def build_password_embed(evt: dict) -> discord.Embed:
    event_name= evt.get("name","(NoName)")
    event_dt= german_datetime_format(evt.get("date_eventstart"))
    pw= evt.get("password","(kein Passwort)")

    emb= discord.Embed(
        title=f"Passwort für Event: {event_name}",
        color=discord.Color.orange()
    )
    emb.add_field(name="Eventstart", value=event_dt if event_dt else "Unbekannt", inline=False)
    emb.add_field(name="Passwort", value=f"`{pw}`", inline=False)
    emb.set_footer(text="Bitte nicht weitergeben!")
    return emb

#########################################
# PERSISTENTE SIGNUP-VIEWS (Allies, Axis)
#########################################
def signups_still_open(evt: dict) -> bool:
    """
    Prüft, ob date_briefing in Zukunft liegt (Anmeldeschluss).
    """
    dtb= evt.get("date_briefing")
    if not dtb:
        return True
    try:
        dt_b= datetime.fromisoformat(dtb)
        return datetime.now() < dt_b
    except:
        return True

# Wir machen Debounce => update_queue
def add_event_to_update_queue(event_id: int):
    update_queue.add(event_id)

async def really_update_event_embeds(event_id: int):
    """
    Führt tatsächlich das Patchen der Discord-Messages durch.
    """
    print(f"[really_update_event_embeds] Starte Update für Event {event_id}")

    conn= get_connection()
    c= conn.cursor()
    c.execute("""
        SELECT info_message_id, allies_message_id, axis_message_id
        FROM events
        WHERE id=?
    """,(event_id,))
    row= c.fetchone()
    conn.close()
    if not row:
        print(f"[really_update_event_embeds] Event {event_id} nicht gefunden.")
        return
    info_id, allies_id, axis_id= row
    if not info_id or not allies_id or not axis_id:
        print(f"[really_update_event_embeds] Keine Msg-IDs für Event {event_id}.")
        return

    evt= get_event_dict(event_id)
    if not evt:
        return
    if not EVENT_CHANNEL_ID:
        print("[really_update_event_embeds] Kein EVENT_CHANNEL_ID.")
        return
    channel= bot.get_channel(EVENT_CHANNEL_ID)
    if not channel:
        print("[really_update_event_embeds] Channel nicht gefunden.")
        return

    emb_info   = build_info_embed(evt)
    emb_allies = build_allies_embed(evt)
    emb_axis   = build_axis_embed(evt)
    sign_up_view= SignUpButtonViewMulti(event_id)

    try:
        msg_info   = await channel.fetch_message(int(info_id))
        msg_allies = await channel.fetch_message(int(allies_id))
        msg_axis   = await channel.fetch_message(int(axis_id))

        # Um Rate-Limit-Spikes zu vermeiden, machen wir kleine Pausen
        await msg_info.edit(embed=emb_info)
        await asyncio.sleep(1)
        await msg_allies.edit(embed=emb_allies)
        await asyncio.sleep(1)
        await msg_axis.edit(embed=emb_axis, view=sign_up_view)

        print(f"[really_update_event_embeds] -> Embeds für Event {event_id} aktualisiert.")
    except discord.NotFound:
        print("[really_update_event_embeds] Mind. eine Nachricht nicht gefunden.")
    except discord.HTTPException as e:
        print(f"[really_update_event_embeds] HTTP-Fehler: {e}")

@tasks.loop(seconds=5)
async def process_update_queue():
    """
    Alle 5 Sek. holen wir uns die Warteschlange (update_queue),
    und aktualisieren die Events nacheinander, um 429-Fehler zu minimieren.
    """
    global update_queue
    if not update_queue:
        return

    to_update = list(update_queue)
    update_queue.clear()

    # Optionale Pause, wenn man "debouncen" möchte
    # await asyncio.sleep(3)

    for evt_id in to_update:
        # Warte 2 Sek zwischen den Events
        await asyncio.sleep(2)
        await really_update_event_embeds(evt_id)

#########################################
# EIGENTLICHE VIEWS
#########################################

class SignUpButtonViewMulti(discord.ui.View):
    def __init__(self, event_id: int):
        super().__init__(timeout=None)
        self.event_id= event_id

        # Falls signups geschlossen
        evt= get_event_dict(self.event_id)
        if not signups_still_open(evt):
            for child in self.children:
                child.disabled= True

    @discord.ui.button(
        label="Alliierte beitreten",
        style=discord.ButtonStyle.success,
        custom_id="signup_button_allies"
    )
    async def allies_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        evt= get_event_dict(self.event_id)
        if not signups_still_open(evt):
            await interaction.response.send_message(
                "Anmeldeschluss erreicht (Briefing hat begonnen).",
                ephemeral=True
            )
            return

        view= AlliesSelectViewMulti(interaction.user.id, self.event_id)
        await interaction.response.send_message(
            f"Rollen (Allies) für Event {self.event_id}:",
            ephemeral=True,
            view=view
        )

    @discord.ui.button(
        label="Achsenmächte beitreten",
        style=discord.ButtonStyle.danger,
        custom_id="signup_button_axis"
    )
    async def axis_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        evt= get_event_dict(self.event_id)
        if not signups_still_open(evt):
            await interaction.response.send_message(
                "Anmeldeschluss erreicht (Briefing hat begonnen).",
                ephemeral=True
            )
            return

        view= AxisSelectViewMulti(interaction.user.id, self.event_id)
        await interaction.response.send_message(
            f"Rollen (Axis) für Event {self.event_id}:",
            ephemeral=True,
            view=view
        )

class AlliesSelectViewMulti(discord.ui.View):
    def __init__(self, user_id: int, event_id: int):
        super().__init__(timeout=180)
        self.user_id= user_id
        self.event_id= event_id

        self.select= discord.ui.Select(
            placeholder=f"Allies-Rolle (Event {event_id})",
            min_values=1, max_values=1
        )
        self.select.callback= self.select_callback
        self.add_item(self.select)

        self.build_options()

    def build_options(self):
        evt= get_event_dict(self.event_id)
        if not evt:
            self.select.options.append(discord.SelectOption(label="Event nicht gefunden", value="none_none"))
            return
        if not signups_still_open(evt):
            self.select.options.append(discord.SelectOption(label="Briefing => Kein Signup mehr!", value="none_none"))
            return

        side= "allies"
        roles= ["inf","tank","sniper","commander"]
        label_map= {"inf":"Infanterie","tank":"Panzer","sniper":"Sniper","commander":"Commander"}

        for r in roles:
            max_s= get_slots_for_role(evt, side, r)
            if max_s<=0:
                continue
            curr= count_signups(self.event_id, side, r)
            if curr>= max_s:
                disp= f"{label_map[r]} [voll]"
                val= f"{side}_{r}_waiting"
            else:
                disp= label_map[r]
                val= f"{side}_{r}_active"
            self.select.options.append(discord.SelectOption(label=disp, value=val))

        if not self.select.options:
            self.select.options.append(discord.SelectOption(label="Allies - keine Slots", value="none_none"))

    async def select_callback(self, interaction: discord.Interaction):
        evt= get_event_dict(self.event_id)
        if not signups_still_open(evt):
            await interaction.response.send_message("Briefing => Anmeldeschluss.", ephemeral=True)
            return

        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Nicht dein Menü!", ephemeral=True)
            return

        val= self.select.values[0]
        if val=="none_none":
            await interaction.response.send_message("Keine Allies-Slots verfügbar.", ephemeral=True)
            return

        if user_already_signedup(self.event_id, str(interaction.user.id)):
            await interaction.response.send_message("Bereits angemeldet!", ephemeral=True)
            return

        side= "allies"
        if val.endswith("_waiting"):
            rolle= val.split("_")[1]
            create_signup(self.event_id, str(interaction.user.id),
                          interaction.user.display_name, side, rolle, "waiting")
            await interaction.response.send_message(f"[Warteliste] Allies/{rolle}", ephemeral=True)
            await send_signup_dm(interaction.user, self.event_id, side, rolle, "waiting")
            add_event_to_update_queue(self.event_id)
            return

        # active
        _, rolle, marker= val.split("_",2)
        create_signup(self.event_id, str(interaction.user.id), interaction.user.display_name,
                      side, rolle, "active")
        await interaction.response.send_message(f"Allies/{rolle} = aktiv!", ephemeral=True)
        await send_signup_dm(interaction.user, self.event_id, side, rolle, "active")
        add_event_to_update_queue(self.event_id)

class AxisSelectViewMulti(discord.ui.View):
    def __init__(self, user_id: int, event_id: int):
        super().__init__(timeout=180)
        self.user_id= user_id
        self.event_id= event_id

        self.select= discord.ui.Select(
            placeholder=f"Axis-Rolle (Event {event_id})",
            min_values=1, max_values=1
        )
        self.select.callback= self.select_callback
        self.add_item(self.select)

        self.build_options()

    def build_options(self):
        evt= get_event_dict(self.event_id)
        if not evt:
            self.select.options.append(discord.SelectOption(label="Event nicht gefunden", value="none_none"))
            return
        if not signups_still_open(evt):
            self.select.options.append(discord.SelectOption(label="Briefing => Kein Signup mehr!", value="none_none"))
            return

        side= "axis"
        roles= ["inf","tank","sniper","commander"]
        label_map= {"inf":"Infanterie","tank":"Panzer","sniper":"Sniper","commander":"Commander"}

        for r in roles:
            max_s= get_slots_for_role(evt, side, r)
            if max_s<=0:
                continue
            curr= count_signups(self.event_id, side, r)
            if curr>= max_s:
                disp= f"{label_map[r]} [voll]"
                val= f"{side}_{r}_waiting"
            else:
                disp= label_map[r]
                val= f"{side}_{r}_active"
            self.select.options.append(discord.SelectOption(label=disp, value=val))

        if not self.select.options:
            self.select.options.append(discord.SelectOption(label="Axis - keine Slots", value="none_none"))

    async def select_callback(self, interaction: discord.Interaction):
        evt= get_event_dict(self.event_id)
        if not signups_still_open(evt):
            await interaction.response.send_message("Briefing => Anmeldeschluss.", ephemeral=True)
            return

        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Nicht dein Menü!", ephemeral=True)
            return

        val= self.select.values[0]
        if val=="none_none":
            await interaction.response.send_message("Keine Axis-Slots verfügbar.", ephemeral=True)
            return

        if user_already_signedup(self.event_id, str(interaction.user.id)):
            await interaction.response.send_message("Bereits angemeldet!", ephemeral=True)
            return

        side= "axis"
        if val.endswith("_waiting"):
            rolle= val.split("_")[1]
            create_signup(self.event_id, str(interaction.user.id),
                          interaction.user.display_name, side, rolle, "waiting")
            await interaction.response.send_message(f"[Warteliste] Axis/{rolle}", ephemeral=True)
            await send_signup_dm(interaction.user, self.event_id, side, rolle, "waiting")
            add_event_to_update_queue(self.event_id)
            return

        _, rolle, marker= val.split("_",2)
        create_signup(self.event_id, str(interaction.user.id),
                      interaction.user.display_name, side, rolle, "active")
        await interaction.response.send_message(f"Axis/{rolle} = aktiv!", ephemeral=True)
        await send_signup_dm(interaction.user, self.event_id, side, rolle, "active")
        add_event_to_update_queue(self.event_id)

#########################################
# CANCEL-VIEW (DM) => persistenter Button
#########################################

class PersistentCancelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Abmelden",
        style=discord.ButtonStyle.danger,
        custom_id="cancel_dm_button"
    )
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        res = cancel_signup(str(interaction.user.id))
        if not res:
            await interaction.response.send_message("Nicht aktiv angemeldet!", ephemeral=True)
            return

        signup_id, event_id, seite, rolle, wait_row= res
        await interaction.response.send_message(
            f"Abmeldung OK: {seite}/{rolle}, Event={event_id}",
            ephemeral=True
        )

        for child in self.children:
            child.disabled= True
        await interaction.message.edit(view=self)

        add_event_to_update_queue(event_id)

#########################################
# SIGNUP-DM => Embed
#########################################

def build_dm_embed(event_id: int, side: str, rolle: str, status: str) -> discord.Embed:
    evt= get_event_dict(event_id)
    if not evt:
        return discord.Embed(
            title="Anmeldung",
            description="Event nicht gefunden",
            color=discord.Color.red()
        )

    event_name= evt.get("name","(NoName)")
    event_start= german_datetime_format(evt.get("date_eventstart"))
    
    emb= discord.Embed(
        title=f"Anmeldung für {event_name}",
        color=discord.Color.blurple()
    )
    emb.add_field(name="Eventstart", value=event_start if event_start else "Unbekannt", inline=False)
    emb.add_field(name="Seite", value=side, inline=True)
    emb.add_field(name="Rolle", value=rolle, inline=True)

    st_text= "Aktiv" if status=="active" else "Warteliste"
    emb.set_footer(text=f"Status: {st_text}")
    return emb

async def send_signup_dm(user: discord.User, event_id: int, side: str, rolle: str, status: str):
    try:
        if user.dm_channel is None:
            await user.create_dm()

        dm_embed= build_dm_embed(event_id, side, rolle, status)
        await user.dm_channel.send(embed=dm_embed, view=PersistentCancelView())
    except Exception as e:
        print(f"[send_signup_dm] Konnte DM an {user.id} nicht senden: {e}")

#########################################
# TASKS
#########################################

@tasks.loop(seconds=120)
async def check_for_new_events():
    """
    Prüft ungepostete Events => postet sie
    """
    await post_all_unposted_events()

@check_for_new_events.before_loop
async def before_check_for_new_events():
    await bot.wait_until_ready()

@tasks.loop(minutes=5)
async def check_for_signup_closure():
    """
    Prüft, ob now >= date_briefing, 
    => pw_sent=0 => PW verschicken etc.
    => Buttons disablen => via update_queue
    """
    now= datetime.now()
    conn= get_connection()
    c= conn.cursor()
    c.execute("""
      SELECT id, date_briefing, pw_sent
      FROM events
      WHERE posted_in_discord=1
        AND date_briefing IS NOT NULL
    """)
    rows= c.fetchall()
    if not rows:
        conn.close()
        return

    for (evt_id, dt_brief, pw_sent_val) in rows:
        if not dt_brief:
            continue
        try:
            dt_b= datetime.fromisoformat(dt_brief)
        except:
            continue

        # Falls now >= dt_b => closen / PW senden
        if now >= dt_b:
            if pw_sent_val==0:
                # Sende PW-Embed an aktive user
                evt= get_event_dict(evt_id)
                c2= conn.cursor()
                c2.execute("SELECT user_id FROM signups WHERE event_id=? AND status='active'", (evt_id,))
                users_list= c2.fetchall()
                for (u_id,) in users_list:
                    user= bot.get_user(int(u_id))
                    if user:
                        emb_pw= build_password_embed(evt)
                        try:
                            if user.dm_channel is None:
                                await user.create_dm()
                            await user.dm_channel.send(embed=emb_pw)
                        except Exception as ex:
                            print(f"[check_for_signup_closure] DM-Fehler an {u_id}: {ex}")

                # Mark pw_sent=1
                c2.execute("UPDATE events SET pw_sent=1 WHERE id=?", (evt_id,))
                conn.commit()

            # Buttons disablen => add to queue
            add_event_to_update_queue(evt_id)

    conn.close()

@check_for_signup_closure.before_loop
async def before_check_for_signup_closure():
    await bot.wait_until_ready()

@tasks.loop(minutes=30)
async def check_for_recurring_events():
    """
    Falls du Recurrence-Logik brauchst: 
    date_eventstart< now => recurrence_pattern != 'none' => new events ...
    """
    now= datetime.now()
    conn= get_connection()
    c= conn.cursor()
    c.execute("""
        SELECT id
        FROM events
        WHERE date_eventstart < ?
          AND recurrence_pattern != 'none'
          AND spawned_next_event=0
    """,(now,))
    rows= c.fetchall()
    if not rows:
        conn.close()
        print("[check_for_recurring_events] Keine abgelaufenen Recurring-Events.")
        return
    print(f"[check_for_recurring_events] {len(rows)} abgelaufene => Erzeuge Folgetermine ...")
    # ...
    conn.close()

@check_for_recurring_events.before_loop
async def before_recur():
    await bot.wait_until_ready()

@tasks.loop(minutes=30)
async def check_events_for_password():
    """
    Falls du noch separate 24h-Logik willst - optional.
    """
    # ...
    pass

@check_events_for_password.before_loop
async def before_pw():
    await bot.wait_until_ready()

#########################################
# on_ready
#########################################

@bot.event
async def on_ready():
    print(f"[on_ready] Bot {bot.user} ist online.")
    ensure_event_columns_exist()
    load_event_channel_id()

    # Registriere DM-Abmelde-View global
    bot.add_view(PersistentCancelView())

    # Starte update_queue-Task
    if not process_update_queue.is_running():
        process_update_queue.start()

    # Optionale Wiederherstellung persistenter Views 
    await restore_sign_up_views()

    # ggf. ungepostete Events posten
    await post_all_unposted_events()

    # Slash commands sync
    try:
        synced= await bot.tree.sync()
        print(f"[on_ready] Slash Commands synced: {len(synced)}")
    except Exception as e:
        print(f"[on_ready] Sync Fehler: {e}")

    # Tasks
    if not check_for_new_events.is_running():
        check_for_new_events.start()
    if not check_for_signup_closure.is_running():
        check_for_signup_closure.start()
    if not check_for_recurring_events.is_running():
        check_for_recurring_events.start()
    if not check_events_for_password.is_running():
        check_events_for_password.start()

#########################################
# PERSISTENTE SIGNUP-VIEWS WIEDERHERSTELLEN
#########################################

async def restore_sign_up_views():
    conn= get_connection()
    c= conn.cursor()
    c.execute("""
        SELECT id, axis_message_id
        FROM events
        WHERE posted_in_discord=1
          AND axis_message_id IS NOT NULL
    """)
    rows= c.fetchall()
    conn.close()

    for (evt_id, axis_id) in rows:
        try:
            view= SignUpButtonViewMulti(evt_id)
            bot.add_view(view, message_id=int(axis_id))
            print(f"[restore_sign_up_views] Persistente View re-registered, event={evt_id}")
        except Exception as e:
            print(f"[restore_sign_up_views] Fehler: {e}")

#########################################
# /set_event_channel
#########################################

@bot.tree.command(name="set_event_channel", description="Setzt den Kanal für Events.")
@app_commands.describe(channel="Discord-Kanal")
async def set_event_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    save_event_channel_id(channel.id)
    await interaction.response.send_message(f"Event-Kanal => {channel.mention}", ephemeral=True)

#########################################
# START
#########################################

def run_discord_bot():
    bot.run(DISCORD_BOT_TOKEN)
