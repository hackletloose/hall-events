import os
import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
from dotenv import load_dotenv
from datetime import datetime, timedelta

# DB-Funktionen
from webapp.db import get_connection
# Hilfsfunktionen für Rollen- und Slot-Logik
from webapp.routes_utils import (
    create_signup,
    cancel_signup,
    get_active_event,
    get_slots_for_role,
    count_signups
)

load_dotenv()
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

############################################
# GLOBALE VARIABLEN: BOT-STATE
############################################

EVENT_CHANNEL_ID = None
CURRENT_EVENT_ID = None

CURRENT_INFO_MESSAGE_ID = None
CURRENT_ALLIES_MESSAGE_ID = None
CURRENT_AXIS_MESSAGE_ID = None

############################################
# DATUMSFORMAT-HILFSFUNKTION
############################################

def german_datetime_format(dt_str):
    if not dt_str:
        return ""
    try:
        dt = datetime.fromisoformat(dt_str)
        return dt.strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return str(dt_str)

############################################
# LOAD / SAVE BOT STATE
############################################

def load_bot_state():
    global EVENT_CHANNEL_ID, CURRENT_EVENT_ID
    global CURRENT_INFO_MESSAGE_ID, CURRENT_ALLIES_MESSAGE_ID, CURRENT_AXIS_MESSAGE_ID

    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT
            event_channel_id,
            current_event_id,
            current_info_message_id,
            current_allies_message_id,
            current_axis_message_id
        FROM bot_state
        WHERE id=1
    """)
    row = c.fetchone()
    conn.close()

    if row:
        ch_str, ev_str, info_msg_str, allies_msg_str, axis_msg_str = row
        EVENT_CHANNEL_ID = int(ch_str) if ch_str else None
        CURRENT_EVENT_ID = int(ev_str) if ev_str else None
        CURRENT_INFO_MESSAGE_ID = int(info_msg_str) if info_msg_str else None
        CURRENT_ALLIES_MESSAGE_ID = int(allies_msg_str) if allies_msg_str else None
        CURRENT_AXIS_MESSAGE_ID = int(axis_msg_str) if axis_msg_str else None

        print(
            f"[load_bot_state] channel={EVENT_CHANNEL_ID}, "
            f"event={CURRENT_EVENT_ID}, info_msg={CURRENT_INFO_MESSAGE_ID}, "
            f"allies_msg={CURRENT_ALLIES_MESSAGE_ID}, axis_msg={CURRENT_AXIS_MESSAGE_ID}"
        )

def save_bot_state(
    event_channel_id,
    current_event_id,
    info_msg_id,
    allies_msg_id,
    axis_msg_id
):
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
    UPDATE bot_state
    SET
      event_channel_id=?,
      current_event_id=?,
      current_info_message_id=?,
      current_allies_message_id=?,
      current_axis_message_id=?
    WHERE id=1
    """, (
        str(event_channel_id) if event_channel_id else None,
        str(current_event_id) if current_event_id else None,
        str(info_msg_id) if info_msg_id else None,
        str(allies_msg_id) if allies_msg_id else None,
        str(axis_msg_id) if axis_msg_id else None
    ))
    conn.commit()
    conn.close()
    print(
        f"[save_bot_state] channel={event_channel_id}, event={current_event_id}, "
        f"info_msg={info_msg_id}, allies_msg={allies_msg_id}, axis_msg={axis_msg_id}"
    )

############################################
# HILFSFUNKTIONEN: EVENT-DATEN
############################################

def get_event_dict(event_id: int) -> dict:
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM events WHERE id=?", (event_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return {}
    cols = [desc[0] for desc in c.description]
    event = dict(zip(cols, row))
    conn.close()
    return event

def get_signups(event_id: int):
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT user_name, seite, rolle
        FROM signups
        WHERE event_id=? AND status='active'
        ORDER BY id ASC
    """, (event_id,))
    rows = c.fetchall()
    conn.close()
    return rows

def user_already_signed_up(event_id: int, user_id: str) -> bool:
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT COUNT(*)
        FROM signups
        WHERE event_id = ?
          AND user_id = ?
          AND status IN ('active', 'waiting')
    """, (event_id, user_id))
    count = c.fetchone()[0]
    conn.close()
    return count > 0

############################################
# EMBED-BAU: Info-, Allies-, Axis-Embeds
############################################

def build_event_info_embed(event_id: int) -> discord.Embed:
    event = get_event_dict(event_id)
    if not event:
        return discord.Embed(title="Event nicht gefunden", description="Fehlerhafte Event-ID")

    briefing_str = german_datetime_format(event.get("date_briefing"))
    eventstart_str = german_datetime_format(event.get("date_eventstart"))
    gamestart_str = german_datetime_format(event.get("date_gamestart"))

    desc_text = event.get("description") or ""
    server_line = event.get("server_info") or ""

    embed = discord.Embed(
        title=f"🎉 Event: {event['name']}",
        description="Hier findest du alle wichtigen Infos zum kommenden Event!",
        color=discord.Color.blue()
    )
    embed.set_thumbnail(url="https://via.placeholder.com/80x80.png?text=Event")

    termine_text = (
        f"**Briefing:** {briefing_str if briefing_str else 'n/a'}\n"
        f"**Eventstart:** {eventstart_str if eventstart_str else 'n/a'}\n"
        f"**Spielstart:** {gamestart_str if gamestart_str else 'n/a'}"
    )
    embed.add_field(name="📅 Termine", value=termine_text, inline=False)

    if server_line.strip():
        server_text = f"{server_line}\n(Passwort kommt 24h vorher per DM!)"
    else:
        server_text = "Keine Server-Info hinterlegt."
    embed.add_field(name="🌐 Server-Info", value=server_text, inline=False)

    if desc_text.strip():
        embed.add_field(name="ℹ️ Beschreibung", value=desc_text, inline=False)
    else:
        embed.add_field(name="ℹ️ Beschreibung", value="Keine Beschreibung vorhanden.", inline=False)

    # Recurrence-Hinweis auf Deutsch
    rpat = event.get("recurrence_pattern", "none")
    if rpat and rpat != "none":
        pattern_map = {
            "weekly": "Wöchentlich",
            "biweekly": "Alle 2 Wochen",
            "monthly": "Monatlich",
            "quarterly": "Quartalsweise"
        }
        german_rpat = pattern_map.get(rpat, rpat)
        embed.add_field(name="🔁 Wiederholung", value=german_rpat, inline=False)

    embed.set_footer(text="Klicke auf 'Anmelden', um dich zu registrieren.")
    return embed

def build_allies_embed(event_id: int) -> discord.Embed:
    event = get_event_dict(event_id)
    if not event:
        return discord.Embed(title="Allies", description="Event nicht gefunden.")

    signups = get_signups(event_id)
    allies_roles = {
        "inf": [],
        "tank": [],
        "sniper": [],
        "commander": []
    }
    for user_name, seite, rolle in signups:
        if seite == "allies" and rolle in allies_roles:
            allies_roles[rolle].append(user_name)

    embed = discord.Embed(title="Alliierte Lineup", color=discord.Color.blue())
    embed.set_thumbnail(url="https://via.placeholder.com/80x80.png?text=Allies")

    role_emoji = {
        "inf": "🪖",
        "tank": "🛡️",
        "sniper": "🎯",
        "commander": "⭐"
    }

    def chunk(lst, size):
        return [lst[i:i+size] for i in range(0, len(lst), size)]

    roles_order = ["inf", "tank", "sniper", "commander"]
    roles_label = {
        "inf": "Infanterie",
        "tank": "Panzer",
        "sniper": "Sniper",
        "commander": "Commander"
    }
    squad_sizes = {"inf": 6, "tank": 3, "sniper": 2, "commander": 1}

    total_allies = 0
    for r in roles_order:
        players = allies_roles[r]
        total_allies += len(players)
        squads = chunk(players, squad_sizes[r])
        if squads:
            for idx, squad in enumerate(squads, start=1):
                squad_title = f"{role_emoji[r]} {roles_label[r]}-Squad #{idx}"
                squad_players = "\n".join(f"- {p}" for p in squad) if squad else "Keine Spieler"
                embed.add_field(name=squad_title, value=squad_players, inline=True)
        else:
            embed.add_field(
                name=f"{role_emoji[r]} {roles_label[r]}",
                value="Keine Spieler",
                inline=True
            )

    # 1 Admin-Abzug, falls gewünscht
    if total_allies > 0:
        total_allies -= 1

    embed.set_footer(text=f"Allies - Gesamt: {total_allies} Spieler (1 Admin abgezogen)")
    return embed

def build_axis_embed(event_id: int) -> discord.Embed:
    event = get_event_dict(event_id)
    if not event:
        return discord.Embed(title="Axis", description="Event nicht gefunden.")

    signups = get_signups(event_id)
    axis_roles = {
        "inf": [],
        "tank": [],
        "sniper": [],
        "commander": []
    }
    for user_name, seite, rolle in signups:
        if seite == "axis" and rolle in axis_roles:
            axis_roles[rolle].append(user_name)

    embed = discord.Embed(title="Achsenmächte Lineup", color=discord.Color.red())
    embed.set_thumbnail(url="https://via.placeholder.com/80x80.png?text=Axis")

    role_emoji = {
        "inf": "🪖",
        "tank": "🛡️",
        "sniper": "🎯",
        "commander": "⭐"
    }

    def chunk(lst, size):
        return [lst[i:i+size] for i in range(0, len(lst), size)]

    roles_order = ["inf", "tank", "sniper", "commander"]
    roles_label = {
        "inf": "Infanterie",
        "tank": "Panzer",
        "sniper": "Sniper",
        "commander": "Commander"
    }
    squad_sizes = {"inf": 6, "tank": 3, "sniper": 2, "commander": 1}

    total_axis = 0
    for r in roles_order:
        players = axis_roles[r]
        total_axis += len(players)
        squads = chunk(players, squad_sizes[r])
        if squads:
            for idx, squad in enumerate(squads, start=1):
                squad_title = f"{role_emoji[r]} {roles_label[r]}-Squad #{idx}"
                squad_players = "\n".join(f"- {p}" for p in squad) if squad else "Keine Spieler"
                embed.add_field(name=squad_title, value=squad_players, inline=True)
        else:
            embed.add_field(
                name=f"{role_emoji[r]} {roles_label[r]}",
                value="Keine Spieler",
                inline=True
            )

    # 1 Admin-Abzug, falls gewünscht
    if total_axis > 0:
        total_axis -= 1

    embed.set_footer(text=f"Axis - Gesamt: {total_axis} Spieler (1 Admin abgezogen)")
    return embed

############################################
# UPDATE EMBEDS
############################################

async def update_discord_event_embeds():
    global EVENT_CHANNEL_ID, CURRENT_EVENT_ID
    global CURRENT_INFO_MESSAGE_ID, CURRENT_ALLIES_MESSAGE_ID, CURRENT_AXIS_MESSAGE_ID

    if not CURRENT_EVENT_ID or not EVENT_CHANNEL_ID:
        return

    channel = bot.get_channel(EVENT_CHANNEL_ID)
    if not channel:
        return

    try:
        # INFO
        if CURRENT_INFO_MESSAGE_ID:
            info_msg = await channel.fetch_message(CURRENT_INFO_MESSAGE_ID)
            new_info_embed = build_event_info_embed(CURRENT_EVENT_ID)
            await info_msg.edit(embed=new_info_embed)

        # ALLIES
        if CURRENT_ALLIES_MESSAGE_ID:
            allies_msg = await channel.fetch_message(CURRENT_ALLIES_MESSAGE_ID)
            new_allies_embed = build_allies_embed(CURRENT_EVENT_ID)
            await allies_msg.edit(embed=new_allies_embed)

        # AXIS
        if CURRENT_AXIS_MESSAGE_ID:
            axis_msg = await channel.fetch_message(CURRENT_AXIS_MESSAGE_ID)
            new_axis_embed = build_axis_embed(CURRENT_EVENT_ID)
            # Button-View erneut anhängen
            await axis_msg.edit(embed=new_axis_embed, view=PersistentSignUpButtonView())

    except discord.NotFound:
        print("[update_discord_event_embeds] Mindestens eine Nachricht wurde nicht gefunden!")
    except discord.HTTPException as e:
        print(f"[update_discord_event_embeds] HTTP-Fehler: {e}")

############################################
# SIGNUP-BUTTONS & DROPDOWNS
############################################

class PersistentSignUpButtonView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Alliierte beitreten",
        style=discord.ButtonStyle.success,
        custom_id="signup_button_allies"
    )
    async def sign_up_allies_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = AlliesRoleSelectViewEphemeral(user_id=interaction.user.id)
        await interaction.response.send_message(
            "Wähle deine Rolle als Alliierter:",
            ephemeral=True,
            view=view
        )

    @discord.ui.button(
        label="Achsenmächte beitreten",
        style=discord.ButtonStyle.danger,
        custom_id="signup_button_axis"
    )
    async def sign_up_axis_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = AxisRoleSelectViewEphemeral(user_id=interaction.user.id)
        await interaction.response.send_message(
            "Wähle deine Rolle als Achsenmächte:",
            ephemeral=True,
            view=view
        )

class AlliesRoleSelectViewEphemeral(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=180)
        self.user_id = user_id

        self.select_menu = discord.ui.Select(
            placeholder="Wähle deine Rolle (Allies)...",
            min_values=1,
            max_values=1,
            custom_id="role_select_ephemeral_allies"
        )
        self.build_select_options()
        self.select_menu.callback = self.select_callback
        self.add_item(self.select_menu)

    def build_select_options(self):
        if not CURRENT_EVENT_ID:
            self.select_menu.options.append(
                discord.SelectOption(label="Kein aktives Event", value="none_none")
            )
            return

        event_dict = get_event_dict(CURRENT_EVENT_ID)
        if not event_dict:
            self.select_menu.options.append(
                discord.SelectOption(label="Event nicht gefunden", value="none_none")
            )
            return

        possible_roles = ["inf", "tank", "sniper", "commander"]
        label_map = {
            "inf": "Infanterie",
            "tank": "Panzer",
            "sniper": "Sniper",
            "commander": "Commander"
        }

        side = "allies"
        for role_key in possible_roles:
            max_slots = get_slots_for_role(event_dict, side, role_key)
            if max_slots <= 0:
                continue

            current_count = count_signups(CURRENT_EVENT_ID, side, role_key)
            if current_count >= max_slots:
                display_label = f"{label_map[role_key]} [voll]"
                val = f"{side}_{role_key}_waiting"
            else:
                display_label = label_map[role_key]
                val = f"{side}_{role_key}_active"

            self.select_menu.options.append(
                discord.SelectOption(label=display_label, value=val)
            )

        # Falls gar keine regulären Rollen zur Auswahl => Warteliste
        if not self.select_menu.options:
            self.select_menu.options.append(
                discord.SelectOption(
                    label="Allies - Warteliste",
                    value="allies_warteliste",
                    description="Keine regulären Slots verfügbar"
                )
            )

    async def select_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Nicht dein Auswahl-Menü!", ephemeral=True)
            return

        if not CURRENT_EVENT_ID:
            await interaction.response.send_message("Kein aktives Event!", ephemeral=True)
            return

        # Prüfen, ob User schon angemeldet
        if user_already_signed_up(CURRENT_EVENT_ID, str(interaction.user.id)):
            await interaction.response.send_message(
                "Du bist bereits angemeldet. Bitte melde dich zuerst ab!",
                ephemeral=True
            )
            return

        val = self.select_menu.values[0]
        if val == "none_none":
            await interaction.response.send_message("Keine Rollen verfügbar...", ephemeral=True)
            return

        if val == "allies_warteliste":
            create_signup(
                CURRENT_EVENT_ID,
                str(interaction.user.id),
                interaction.user.display_name,
                "allies", "warteliste", "waiting"
            )
            await interaction.response.send_message(
                "Du bist auf der Warteliste (Allies).", ephemeral=True
            )
            await send_signup_dm(interaction.user, "allies", "warteliste", "waiting")
            await update_discord_event_embeds()
            return

        seite, rolle, status_marker = val.split("_", 2)
        if status_marker == "active":
            status = "active"
            msg = f"Du bist jetzt als {rolle.upper()} auf Seite Allies angemeldet!"
        else:
            status = "waiting"
            msg = f"{rolle.upper()} auf Seite Allies ist voll. Du bist jetzt wartend."

        create_signup(
            CURRENT_EVENT_ID, str(interaction.user.id),
            interaction.user.display_name, seite, rolle, status
        )

        await interaction.response.send_message(msg, ephemeral=True)
        await send_signup_dm(interaction.user, seite, rolle, status)
        await update_discord_event_embeds()

class AxisRoleSelectViewEphemeral(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=180)
        self.user_id = user_id

        self.select_menu = discord.ui.Select(
            placeholder="Wähle deine Rolle (Achsenmächte)...",
            min_values=1,
            max_values=1,
            custom_id="role_select_ephemeral_axis"
        )
        self.build_select_options()
        self.select_menu.callback = self.select_callback
        self.add_item(self.select_menu)

    def build_select_options(self):
        if not CURRENT_EVENT_ID:
            self.select_menu.options.append(
                discord.SelectOption(label="Kein aktives Event", value="none_none")
            )
            return

        event_dict = get_event_dict(CURRENT_EVENT_ID)
        if not event_dict:
            self.select_menu.options.append(
                discord.SelectOption(label="Event nicht gefunden", value="none_none")
            )
            return

        possible_roles = ["inf", "tank", "sniper", "commander"]
        label_map = {
            "inf": "Infanterie",
            "tank": "Panzer",
            "sniper": "Sniper",
            "commander": "Commander"
        }

        side = "axis"
        for role_key in possible_roles:
            max_slots = get_slots_for_role(event_dict, side, role_key)
            if max_slots <= 0:
                continue

            current_count = count_signups(CURRENT_EVENT_ID, side, role_key)
            if current_count >= max_slots:
                display_label = f"{label_map[role_key]} [voll]"
                val = f"{side}_{role_key}_waiting"
            else:
                display_label = label_map[role_key]
                val = f"{side}_{role_key}_active"

            self.select_menu.options.append(
                discord.SelectOption(label=display_label, value=val)
            )

        # Falls gar keine regulären Rollen => Warteliste
        if not self.select_menu.options:
            self.select_menu.options.append(
                discord.SelectOption(
                    label="Axis - Warteliste",
                    value="axis_warteliste",
                    description="Keine regulären Slots verfügbar"
                )
            )

    async def select_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Nicht dein Auswahl-Menü!", ephemeral=True)
            return

        if not CURRENT_EVENT_ID:
            await interaction.response.send_message("Kein aktives Event!", ephemeral=True)
            return

        if user_already_signed_up(CURRENT_EVENT_ID, str(interaction.user.id)):
            await interaction.response.send_message(
                "Du bist bereits angemeldet. Bitte melde dich zuerst ab!",
                ephemeral=True
            )
            return

        val = self.select_menu.values[0]
        if val == "none_none":
            await interaction.response.send_message("Keine Rollen verfügbar...", ephemeral=True)
            return

        if val == "axis_warteliste":
            create_signup(
                CURRENT_EVENT_ID,
                str(interaction.user.id),
                interaction.user.display_name,
                "axis", "warteliste", "waiting"
            )
            await interaction.response.send_message(
                "Du bist auf der Warteliste (Axis).", ephemeral=True
            )
            await send_signup_dm(interaction.user, "axis", "warteliste", "waiting")
            await update_discord_event_embeds()
            return

        seite, rolle, status_marker = val.split("_", 2)
        if status_marker == "active":
            status = "active"
            msg = f"Du bist jetzt als {rolle.upper()} auf Seite Achsenmächte angemeldet!"
        else:
            status = "waiting"
            msg = f"{rolle.upper()} auf Seite Achsenmächte ist voll. Du bist jetzt wartend."

        create_signup(
            CURRENT_EVENT_ID, str(interaction.user.id),
            interaction.user.display_name, seite, rolle, status
        )

        await interaction.response.send_message(msg, ephemeral=True)
        await send_signup_dm(interaction.user, seite, rolle, status)
        await update_discord_event_embeds()

###################################
# PERSISTENTE "ABMELDEN"-VIEW FÜR DM
###################################

class PersistentCancelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Abmelden",
        style=discord.ButtonStyle.danger,
        custom_id="cancel_dm_button"
    )
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        res = cancel_signup(str(interaction.user.id))
        if not res:
            await interaction.response.send_message(
                "Du warst nicht aktiv angemeldet oder bereits abgemeldet!",
                ephemeral=True
            )
            return

        signup_id, event_id, seite, rolle, wait_row = res
        await interaction.response.send_message(
            f"Abmeldung erfolgreich ({seite}/{rolle}).",
            ephemeral=True
        )

        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)

        await update_discord_event_embeds()

############################################
# DM-BENACHRICHTIGUNG
############################################

async def send_signup_dm(user: discord.User, seite: str, rolle: str, status: str):
    try:
        if user.dm_channel is None:
            await user.create_dm()
        warte_hinweis = ""
        if status == "waiting":
            warte_hinweis = " (Warteliste)"

        await user.dm_channel.send(
            f"Du hast dich für **{seite}** / **{rolle}**{warte_hinweis} angemeldet.\n"
            "Passwort kommt 24h vorher per DM.\n"
            "Klicke 'Abmelden', wenn du dich wieder abmelden willst.",
            view=PersistentCancelView()
        )
    except Exception as e:
        print(f"[send_signup_dm] Konnte keine DM senden: {e}")

############################################
# BOT-EVENTS
############################################

@bot.event
async def on_ready():
    print(f"Bot {bot.user} ist online.")
    load_bot_state()

    # Registriere persistente Views
    bot.add_view(PersistentSignUpButtonView())
    bot.add_view(PersistentCancelView())
    print("[on_ready] PersistentSignUpButtonView und PersistentCancelView registriert.")

    # Falls ein CURRENT_EVENT_ID existiert, stelle sicher, dass die Nachrichten existieren
    await ensure_event_messages()

    # Slash Commands synchronisieren
    try:
        synced = await bot.tree.sync()
        print(f"Slash Commands synced: {len(synced)} Befehle.")
    except Exception as e:
        print(f"Fehler beim Sync: {e}")

    # Tasks starten
    if not check_for_recurring_events.is_running():
        check_for_recurring_events.start()
    if not check_events_for_password.is_running():
        check_events_for_password.start()

async def ensure_event_messages():
    """
    Stellt sicher, dass für das CURRENT_EVENT_ID die drei Embed-Nachrichten
    (Info, Allies, Axis) existieren. Falls nicht (z.B. Bot-Crash),
    werden sie neu erzeugt.
    """
    global CURRENT_EVENT_ID
    global CURRENT_INFO_MESSAGE_ID
    global CURRENT_ALLIES_MESSAGE_ID
    global CURRENT_AXIS_MESSAGE_ID

    if not CURRENT_EVENT_ID:
        return

    channel = bot.get_channel(EVENT_CHANNEL_ID) if EVENT_CHANNEL_ID else None
    if not channel:
        return

    need_new_info = False
    need_new_allies = False
    need_new_axis = False

    if CURRENT_INFO_MESSAGE_ID:
        try:
            await channel.fetch_message(CURRENT_INFO_MESSAGE_ID)
        except:
            need_new_info = True
            CURRENT_INFO_MESSAGE_ID = None
    else:
        need_new_info = True

    if CURRENT_ALLIES_MESSAGE_ID:
        try:
            await channel.fetch_message(CURRENT_ALLIES_MESSAGE_ID)
        except:
            need_new_allies = True
            CURRENT_ALLIES_MESSAGE_ID = None
    else:
        need_new_allies = True

    if CURRENT_AXIS_MESSAGE_ID:
        try:
            await channel.fetch_message(CURRENT_AXIS_MESSAGE_ID)
        except:
            need_new_axis = True
            CURRENT_AXIS_MESSAGE_ID = None
    else:
        need_new_axis = True

    if need_new_info or need_new_allies or need_new_axis:
        print("[ensure_event_messages] Mindestens eine Nachricht wird neu erstellt.")
        info_embed = build_event_info_embed(CURRENT_EVENT_ID)
        allies_embed = build_allies_embed(CURRENT_EVENT_ID)
        axis_embed = build_axis_embed(CURRENT_EVENT_ID)

        if need_new_info:
            msg_info = await channel.send(embed=info_embed)
            CURRENT_INFO_MESSAGE_ID = msg_info.id

        if need_new_allies:
            msg_allies = await channel.send(embed=allies_embed)
            CURRENT_ALLIES_MESSAGE_ID = msg_allies.id

        if need_new_axis:
            msg_axis = await channel.send(embed=axis_embed, view=PersistentSignUpButtonView())
            CURRENT_AXIS_MESSAGE_ID = msg_axis.id

        save_bot_state(
            EVENT_CHANNEL_ID,
            CURRENT_EVENT_ID,
            CURRENT_INFO_MESSAGE_ID,
            CURRENT_ALLIES_MESSAGE_ID,
            CURRENT_AXIS_MESSAGE_ID
        )

############################################
# SLASH COMMAND: /set_event_channel
############################################

@bot.tree.command(name="set_event_channel", description="Setzt den Textkanal für Event-Infos.")
@app_commands.describe(channel="Wähle den Textkanal")
async def set_event_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    global EVENT_CHANNEL_ID, CURRENT_EVENT_ID
    global CURRENT_INFO_MESSAGE_ID, CURRENT_ALLIES_MESSAGE_ID, CURRENT_AXIS_MESSAGE_ID

    EVENT_CHANNEL_ID = channel.id
    save_bot_state(
        EVENT_CHANNEL_ID,
        CURRENT_EVENT_ID,
        CURRENT_INFO_MESSAGE_ID,
        CURRENT_ALLIES_MESSAGE_ID,
        CURRENT_AXIS_MESSAGE_ID
    )
    await interaction.response.send_message(
        f"Event-Kanal wurde auf {channel.mention} gesetzt.",
        ephemeral=True
    )

############################################
# TASK: PASSWORT 24h VORHER
############################################

@tasks.loop(minutes=30)
async def check_events_for_password():
    now = datetime.now()
    soon_24h_min = now + timedelta(hours=24) - timedelta(minutes=15)
    soon_24h_max = now + timedelta(hours=24) + timedelta(minutes=15)

    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT id, name, date_eventstart, password
        FROM events
        WHERE date_eventstart BETWEEN ? AND ?
    """, (soon_24h_min, soon_24h_max))
    events_to_notify = c.fetchall()

    for evt in events_to_notify:
        event_id, event_name, date_evstart, pwd = evt
        c.execute("""
            SELECT user_id
            FROM signups
            WHERE event_id = ?
              AND status = 'active'
        """, (event_id,))
        signups_list = c.fetchall()
        for (user_id,) in signups_list:
            user = bot.get_user(int(user_id))
            if user:
                try:
                    if user.dm_channel is None:
                        await user.create_dm()
                    await user.dm_channel.send(
                        f"**Info zu Event '{event_name}'**\n"
                        f"Start: {date_evstart}\n"
                        f"Passwort: `{pwd}`\n"
                        "Bitte nicht weitergeben!"
                    )
                except Exception as e:
                    print(f"Fehler beim PW-Versand an {user_id}: {e}")

    conn.close()

@check_events_for_password.before_loop
async def before_check_events():
    await bot.wait_until_ready()

############################################
# WIEDERHOLUNGS-EVENTS: NEUE EVENT ERZEUGEN
# UND GLEICH POSTEN, SOBALD DAS ALTE VORBEI IST
############################################

@tasks.loop(minutes=30)
async def check_for_recurring_events():
    """
    Sucht alle Events, die in der Vergangenheit liegen, ein Wiederholungsmuster haben,
    und noch keinen Folgetermin erzeugt haben. Dann wird ein neuer Event-Datensatz 
    mit entsprechendem Zeitversatz angelegt - UND gleich im Discord-Kanal gepostet.
    Auf diese Weise ist das nächste Event sofort nach Ende des alten Events sichtbar.
    """
    now = datetime.now()
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT id, name, date_briefing, date_eventstart, date_gamestart,
               description, server_info, password,
               inf_squads_allies, tank_squads_allies, sniper_squads_allies,
               inf_squads_axis, tank_squads_axis, sniper_squads_axis,
               max_commanders_allies, max_commanders_axis,
               recurrence_pattern
        FROM events
        WHERE date_eventstart < ?
          AND recurrence_pattern != 'none'
          AND spawned_next_event=0
    """, (now,))
    rows = c.fetchall()

    if not rows:
        conn.close()
        return

    for row in rows:
        (old_id, name, dt_brief, dt_start, dt_game, descr, sinfo, pwd,
         ia, ta, sa, ix, tx, sx,
         ca, cx, rpat) = row

        # Bestimme Zeitversatz je nach Wiederholungsmuster
        offset_days = 0
        if rpat == "weekly":
            offset_days = 7
        elif rpat == "biweekly":
            offset_days = 14
        elif rpat == "monthly":
            offset_days = 30
        elif rpat == "quarterly":
            offset_days = 90

        def shift_date(date_str):
            if not date_str:
                return None
            try:
                dt = datetime.fromisoformat(date_str)
                dt_new = dt + timedelta(days=offset_days)
                return dt_new.isoformat(sep=" ")
            except:
                return date_str  # Fallback falls kaputtes Format

        new_brief = shift_date(dt_brief)
        new_start = shift_date(dt_start)
        new_game = shift_date(dt_game)

        c2 = conn.cursor()
        # Neues Event anlegen
        c2.execute("""
            INSERT INTO events (
                name, description,
                date_briefing, date_eventstart, date_gamestart,
                server_info, password,
                inf_squads_allies, tank_squads_allies, sniper_squads_allies,
                inf_squads_axis, tank_squads_axis, sniper_squads_axis,
                max_commanders_allies, max_commanders_axis,
                created_at,
                recurrence_pattern,
                spawned_next_event,
                posted_in_discord
            )
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            name, descr,
            new_brief, new_start, new_game,
            sinfo, pwd,
            ia, ta, sa,
            ix, tx, sx,
            ca, cx,
            datetime.now(),
            rpat,
            0,            # spawned_next_event für das NEUE Event = 0 (hat ja noch keinen Nachfolger)
            0             # posted_in_discord=0 (Standard, wir setzen es gleich auf 1 nach dem Post)
        ))
        new_event_id = c2.lastrowid

        # Altes Event als "hat Nachfolger erzeugt" markieren
        c2.execute("UPDATE events SET spawned_next_event=1 WHERE id=?", (old_id,))
        conn.commit()

        print(f"[check_for_recurring_events] Neues Event {new_event_id} erzeugt aus {old_id} ({rpat}).")

        # Direkt im Discord posten (sofort nach Erzeugung)
        # Wir setzen dieses neue Event als CURRENT_EVENT_ID.
        global CURRENT_EVENT_ID
        global CURRENT_INFO_MESSAGE_ID, CURRENT_ALLIES_MESSAGE_ID, CURRENT_AXIS_MESSAGE_ID
        global EVENT_CHANNEL_ID

        CURRENT_EVENT_ID = new_event_id
        CURRENT_INFO_MESSAGE_ID = None
        CURRENT_ALLIES_MESSAGE_ID = None
        CURRENT_AXIS_MESSAGE_ID = None

        channel = bot.get_channel(EVENT_CHANNEL_ID) if EVENT_CHANNEL_ID else None
        if channel:
            info_embed = build_event_info_embed(CURRENT_EVENT_ID)
            allies_embed = build_allies_embed(CURRENT_EVENT_ID)
            axis_embed = build_axis_embed(CURRENT_EVENT_ID)

            msg_info = await channel.send(embed=info_embed)
            CURRENT_INFO_MESSAGE_ID = msg_info.id

            msg_allies = await channel.send(embed=allies_embed)
            CURRENT_ALLIES_MESSAGE_ID = msg_allies.id

            msg_axis = await channel.send(embed=axis_embed, view=PersistentSignUpButtonView())
            CURRENT_AXIS_MESSAGE_ID = msg_axis.id

            # posted_in_discord = 1
            c2.execute("UPDATE events SET posted_in_discord=1 WHERE id=?", (new_event_id,))
            conn.commit()

            # Bot-State speichern
            save_bot_state(
                EVENT_CHANNEL_ID,
                CURRENT_EVENT_ID,
                CURRENT_INFO_MESSAGE_ID,
                CURRENT_ALLIES_MESSAGE_ID,
                CURRENT_AXIS_MESSAGE_ID
            )
        else:
            print("[check_for_recurring_events] Kein EVENT_CHANNEL_ID gesetzt oder Kanal nicht gefunden!")

    conn.close()

@check_for_recurring_events.before_loop
async def before_check_for_recurring_events():
    await bot.wait_until_ready()

############################################
# START-FUNKTION + EXTERNER TRIGGER
############################################

def run_discord_bot():
    bot.run(DISCORD_BOT_TOKEN)

def trigger_embed_update():
    future = asyncio.run_coroutine_threadsafe(
        update_discord_event_embeds(),
        bot.loop
    )
    try:
        future.result()
    except Exception as e:
        print(f"Fehler beim Aktualisieren der Embeds: {e}")
