import os
import sqlite3
import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
from dotenv import load_dotenv
from datetime import datetime, timedelta

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

#########################################
# 1) Spalten anlegen, falls sie fehlen
#########################################

def ensure_event_columns_exist():
    """
    Prüft, ob info_message_id in events existiert.
    Falls nicht, legen wir info_message_id, allies_message_id, axis_message_id,
    posted_in_discord an. So vermeiden wir 'no such column' Fehler.
    """
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("SELECT info_message_id FROM events LIMIT 1")
    except sqlite3.OperationalError:
        print("[ensure_event_columns_exist] info_message_id fehlt. Lege fehlende Spalten an...")
        try:
            c.execute("ALTER TABLE events ADD COLUMN info_message_id TEXT")
            c.execute("ALTER TABLE events ADD COLUMN allies_message_id TEXT")
            c.execute("ALTER TABLE events ADD COLUMN axis_message_id TEXT")
            c.execute("ALTER TABLE events ADD COLUMN posted_in_discord INTEGER DEFAULT 0")
            conn.commit()
            print("[ensure_event_columns_exist] Spalten info_message_id, allies_message_id, axis_message_id, posted_in_discord angelegt.")
        except Exception as e:
            print(f"[ensure_event_columns_exist] Fehler beim ALTER TABLE: {e}")
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
    c.execute("UPDATE bot_state SET event_channel_id=? WHERE id=1",(str(channel_id),))
    conn.commit()
    conn.close()
    print(f"[save_event_channel_id] EVENT_CHANNEL_ID={EVENT_CHANNEL_ID} in DB gespeichert.")

#########################################
# 3) DB-Funktionen
#########################################

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

def get_event_dict(event_id: int) -> dict:
    conn= get_connection()
    c= conn.cursor()
    c.execute("SELECT * FROM events WHERE id=?",(event_id,))
    row= c.fetchone()
    if not row:
        conn.close()
        return {}
    cols = [desc[0] for desc in c.description]
    data= dict(zip(cols,row))
    conn.close()
    return data

#########################################
# chunk(...) -> Hilfsfunktion
#########################################

def chunk(lst, size):
    return [lst[i:i+size] for i in range(0,len(lst),size)]

#########################################
# DATUMSFORMAT
#########################################

def german_datetime_format(dt_str):
    if not dt_str:
        return ""
    try:
        dt= datetime.fromisoformat(dt_str)
        return dt.strftime("%d.%m.%Y %H:%M")
    except:
        return str(dt_str)

#########################################
# EMBED-Funktionen: Info, Allies, Axis
#########################################

def build_info_embed(evt: dict) -> discord.Embed:
    nm  = evt.get("name","(NoName)")
    dtb = german_datetime_format(evt.get("date_briefing"))
    dts = german_datetime_format(evt.get("date_eventstart"))
    dtg = german_datetime_format(evt.get("date_gamestart"))
    srv = evt.get("server_info","")
    desc= evt.get("description","")
    rp  = evt.get("recurrence_pattern","none")

    embed= discord.Embed(title=f"Event: {nm}",color=discord.Color.blue())
    embed.set_thumbnail(url="https://via.placeholder.com/80x80.png?text=Event")

    lines= (
        f"**Briefing:** {dtb}\n"
        f"**Eventstart:** {dts}\n"
        f"**Spielstart:** {dtg}"
    )
    embed.add_field(name="Termine", value=lines, inline=False)

    if srv.strip():
        embed.add_field(name="Server", value=f"{srv}\n(PW 24h vorher)", inline=False)
    if desc.strip():
        embed.add_field(name="Beschreibung", value=desc, inline=False)
    if rp and rp!="none":
        embed.add_field(name="Wiederholung", value=rp, inline=False)

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

#########################################
# POSTEN EINES EVENTS
#########################################

async def post_event_in_discord(event_id: int, channel: discord.TextChannel):
    evt= get_event_dict(event_id)
    if not evt:
        print(f"[post_event_in_discord] Event {event_id} nicht gefunden.")
        return

    emb_info   = build_info_embed(evt)
    emb_allies = build_allies_embed(evt)
    emb_axis   = build_axis_embed(evt)

    # Persistente Buttons -> sign_up_view
    sign_up_view= SignUpButtonViewMulti(event_id)

    msg_info   = await channel.send(embed=emb_info)
    msg_allies = await channel.send(embed=emb_allies)
    msg_axis   = await channel.send(embed=emb_axis, view=sign_up_view)

    info_id   = str(msg_info.id)
    allies_id = str(msg_allies.id)
    axis_id   = str(msg_axis.id)

    conn= get_connection()
    c= conn.cursor()
    c.execute("""
        UPDATE events
        SET info_message_id=?,
            allies_message_id=?,
            axis_message_id=?,
            posted_in_discord=1
        WHERE id=?
    """,(info_id,allies_id,axis_id,event_id))
    conn.commit()
    conn.close()

    print(f"[post_event_in_discord] Event {event_id} gepostet => (MsgIDs={info_id}/{allies_id}/{axis_id})")

async def post_all_unposted_events():
    if not EVENT_CHANNEL_ID:
        print("[post_all_unposted_events] Kein EVENT_CHANNEL_ID, Abbruch.")
        return
    channel= bot.get_channel(EVENT_CHANNEL_ID)
    if not channel:
        print(f"[post_all_unposted_events] Channel {EVENT_CHANNEL_ID} nicht gefunden.")
        return

    conn= get_connection()
    c= conn.cursor()
    c.execute("SELECT id FROM events WHERE posted_in_discord=0 ORDER BY id ASC")
    rows= c.fetchall()
    conn.close()

    if not rows:
        return

    print(f"[post_all_unposted_events] Poste {len(rows)} ungepostete Event(s).")
    for (evt_id,) in rows:
        await post_event_in_discord(evt_id, channel)

#########################################
# EMBEDS UPDATEN
#########################################

async def update_event_embeds(event_id: int):
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
        print(f"[update_event_embeds] Event {event_id} nicht gefunden.")
        return
    info_id, allies_id, axis_id= row
    if not info_id or not allies_id or not axis_id:
        print(f"[update_event_embeds] Keine Msg-IDs für Event {event_id}.")
        return

    evt= get_event_dict(event_id)
    if not evt:
        return

    if not EVENT_CHANNEL_ID:
        print("[update_event_embeds] Kein EVENT_CHANNEL_ID.")
        return
    channel= bot.get_channel(EVENT_CHANNEL_ID)
    if not channel:
        print("[update_event_embeds] Channel nicht gefunden.")
        return

    emb_info   = build_info_embed(evt)
    emb_allies = build_allies_embed(evt)
    emb_axis   = build_axis_embed(evt)
    sign_up_view= SignUpButtonViewMulti(event_id)

    try:
        msg_info   = await channel.fetch_message(int(info_id))
        msg_allies = await channel.fetch_message(int(allies_id))
        msg_axis   = await channel.fetch_message(int(axis_id))

        await msg_info.edit(embed=emb_info)
        await msg_allies.edit(embed=emb_allies)
        await msg_axis.edit(embed=emb_axis, view=sign_up_view)

        print(f"[update_event_embeds] Event {event_id} - Embeds aktualisiert.")
    except discord.NotFound:
        print("[update_event_embeds] Mind. eine Nachricht nicht gefunden.")
    except discord.HTTPException as e:
        print(f"[update_event_embeds] HTTP-Fehler: {e}")

#########################################
# SIGNUP-VIEWS (Allies, Axis) => persistent
#########################################

class SignUpButtonViewMulti(discord.ui.View):
    """
    Persistente Buttons (Alliierte/Achsenmächte).
    => fester custom_id => nach Neustart wieder benutzbar
    """
    def __init__(self, event_id: int):
        super().__init__(timeout=None)
        self.event_id= event_id

    @discord.ui.button(
        label="Alliierte beitreten",
        style=discord.ButtonStyle.success,
        custom_id="signup_button_allies"  # fester ID
    )
    async def allies_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        view= AlliesSelectViewMulti(interaction.user.id, self.event_id)
        await interaction.response.send_message(
            f"Rollen (Allies) für Event {self.event_id}:",
            ephemeral=True,
            view=view
        )

    @discord.ui.button(
        label="Achsenmächte beitreten",
        style=discord.ButtonStyle.danger,
        custom_id="signup_button_axis"  # fester ID
    )
    async def axis_button(self, interaction: discord.Interaction, button: discord.ui.Button):
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

        side= "allies"
        possible= ["inf","tank","sniper","commander"]
        label_map= {"inf":"Infanterie","tank":"Panzer","sniper":"Sniper","commander":"Commander"}

        for r in possible:
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
        if interaction.user.id!= self.user_id:
            await interaction.response.send_message("Nicht dein Menü!", ephemeral=True)
            return
        val= self.select.values[0]
        if val=="none_none":
            await interaction.response.send_message("Keine Allies-Slots", ephemeral=True)
            return

        if user_already_signedup(self.event_id, str(interaction.user.id)):
            await interaction.response.send_message("Bereits angemeldet!", ephemeral=True)
            return

        if val.endswith("_waiting"):
            rolle= val.split("_")[1]
            create_signup(self.event_id, str(interaction.user.id), interaction.user.display_name,
                          "allies", rolle,"waiting")
            await interaction.response.send_message(f"[Warteliste] Allies/{rolle}", ephemeral=True)
            await send_signup_dm(interaction.user,"allies",rolle,"waiting")
            await update_event_embeds(self.event_id)
            return

        # active
        _, rolle, marker= val.split("_",2)
        create_signup(self.event_id, str(interaction.user.id), interaction.user.display_name,
                      "allies", rolle, "active")
        await interaction.response.send_message(f"Allies/{rolle} = aktiv", ephemeral=True)
        await send_signup_dm(interaction.user,"allies",rolle,"active")
        await update_event_embeds(self.event_id)

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

        side= "axis"
        roles=["inf","tank","sniper","commander"]
        label_map={"inf":"Infanterie","tank":"Panzer","sniper":"Sniper","commander":"Commander"}

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
        if interaction.user.id!= self.user_id:
            await interaction.response.send_message("Nicht dein Menü!", ephemeral=True)
            return
        val= self.select.values[0]
        if val=="none_none":
            await interaction.response.send_message("Keine Axis-Slots", ephemeral=True)
            return

        if user_already_signedup(self.event_id, str(interaction.user.id)):
            await interaction.response.send_message("Bereits angemeldet!", ephemeral=True)
            return

        if val.endswith("_waiting"):
            rolle= val.split("_")[1]
            create_signup(self.event_id, str(interaction.user.id), interaction.user.display_name,
                          "axis", rolle,"waiting")
            await interaction.response.send_message(f"[Warteliste] Axis/{rolle}", ephemeral=True)
            await send_signup_dm(interaction.user,"axis",rolle,"waiting")
            await update_event_embeds(self.event_id)
            return

        _, rolle, marker= val.split("_",2)
        create_signup(self.event_id, str(interaction.user.id), interaction.user.display_name,
                      "axis", rolle,"active")
        await interaction.response.send_message(f"Axis/{rolle} = aktiv", ephemeral=True)
        await send_signup_dm(interaction.user,"axis",rolle,"active")
        await update_event_embeds(self.event_id)

#########################################
# CANCEL-VIEW (DM) => Persistenter Button
#########################################

class PersistentCancelView(discord.ui.View):
    """
    Damit nach Neustart auch der DM-Abmelde-Button persistiert.
    """
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Abmelden",
        style=discord.ButtonStyle.danger,
        custom_id="cancel_dm_button" 
    )
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        from webapp.routes_utils import cancel_signup
        res= cancel_signup(str(interaction.user.id))
        if not res:
            await interaction.response.send_message("Nicht aktiv angemeldet!", ephemeral=True)
            return
        signup_id, event_id, seite, rolle, wait_row= res
        await interaction.response.send_message(f"Abmeldung OK: {seite}/{rolle}, Event={event_id}", ephemeral=True)

        for child in self.children:
            child.disabled= True
        await interaction.message.edit(view=self)

        await update_event_embeds(event_id)

#########################################
# SIGNUP-DM
#########################################

async def send_signup_dm(user: discord.User, side: str, rolle: str, status: str):
    try:
        if user.dm_channel is None:
            await user.create_dm()
        w= " (Warteliste)" if status=="waiting" else ""
        text= (
            f"Du hast dich angemeldet: {side}/{rolle}{w}.\n"
            "Abmelden -> 'Abmelden'-Button:"
        )
        # persistente Abmelde-View
        await user.dm_channel.send(text, view=PersistentCancelView())
    except Exception as e:
        print(f"[send_signup_dm] Konnte DM an {user.id} nicht senden: {e}")

#########################################
# TASKS: Recurring + PW
#########################################

@tasks.loop(minutes=30)
async def check_for_recurring_events():
    now= datetime.now()
    conn= get_connection()
    c= conn.cursor()
    c.execute("""
        SELECT id, date_eventstart, recurrence_pattern, spawned_next_event
        FROM events
        WHERE date_eventstart< ?
          AND recurrence_pattern!='none'
          AND spawned_next_event=0
    """,(now,))
    rows= c.fetchall()
    if not rows:
        conn.close()
        print("[check_for_recurring_events] Keine abgelaufenen Recurring-Events.")
        return
    print(f"[check_for_recurring_events] {len(rows)} abgelaufene Recurring-Events.")
    conn.close()

@check_for_recurring_events.before_loop
async def before_recur():
    await bot.wait_until_ready()

@tasks.loop(minutes=30)
async def check_events_for_password():
    now= datetime.now()
    soon_min= now + timedelta(hours=24) - timedelta(minutes=15)
    soon_max= now + timedelta(hours=24) + timedelta(minutes=15)

    conn= get_connection()
    c= conn.cursor()
    c.execute("""
        SELECT id, name, date_eventstart, password
        FROM events
        WHERE date_eventstart BETWEEN ? AND ?
    """,(soon_min,soon_max))
    rows= c.fetchall()
    if rows:
        print(f"[check_events_for_password] {len(rows)} Events ~24h.")
    else:
        print("[check_events_for_password] Keine Events in ~24h.")

    for (evt_id, evt_name, evt_dt, pw) in rows:
        c.execute("""
            SELECT user_id
            FROM signups
            WHERE event_id=?
              AND status='active'
        """,(evt_id,))
        user_rows= c.fetchall()
        for (u_id,) in user_rows:
            user= bot.get_user(int(u_id))
            if user:
                try:
                    if user.dm_channel is None:
                        await user.create_dm()
                    text= f"**PW für Event '{evt_name}'**\nStart: {evt_dt}\nPasswort: `{pw}`"
                    await user.dm_channel.send(text)
                except Exception as exc:
                    print(f"[check_events_for_password] Fehler DM an {u_id}: {exc}")
    conn.close()

@check_events_for_password.before_loop
async def before_pw():
    await bot.wait_until_ready()

#########################################
# check_for_new_events => z. B. alle 120s
#########################################

@tasks.loop(seconds=120)
async def check_for_new_events():
    await post_all_unposted_events()

@check_for_new_events.before_loop
async def before_check_for_new_events():
    await bot.wait_until_ready()

#########################################
# on_ready
#########################################

async def restore_sign_up_views():
    """
    Lädt alle bereits geposteten Events aus DB, 
    registriert SignUpButtonViewMulti(...) erneut.
    Damit bleiben die Buttons (Alliierte/Achsen...) 
    nach einem Neustart anklickbar.
    """
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
            # Registriere persistente View => message_id=axis_id
            view= SignUpButtonViewMulti(evt_id)
            bot.add_view(view, message_id=int(axis_id))
            print(f"[restore_sign_up_views] Persistente SignUp-View für Event {evt_id} re-registered.")
        except Exception as e:
            print(f"[restore_sign_up_views] Fehler: {e}")

@bot.event
async def on_ready():
    print(f"[on_ready] Bot {bot.user} ist online.")
    ensure_event_columns_exist()
    load_event_channel_id()

    # Registriere die DM-Abmelde-View (damit alte DMs Abmelde-Button behalten)
    bot.add_view(PersistentCancelView())

    # Restore persistent signup-views für alle Events
    await restore_sign_up_views()

    # ggf. einmalig ungepostete Events senden
    await post_all_unposted_events()

    # Slash-Commands
    try:
        synced= await bot.tree.sync()
        print(f"[on_ready] Slash Commands synced: {len(synced)}")
    except Exception as e:
        print(f"[on_ready] Sync Fehler: {e}")

    # Start tasks
    if not check_for_recurring_events.is_running():
        check_for_recurring_events.start()
    if not check_events_for_password.is_running():
        check_events_for_password.start()
    if not check_for_new_events.is_running():
        check_for_new_events.start()

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
