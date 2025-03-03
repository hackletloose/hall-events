import asyncio
from flask import Blueprint, render_template, request, redirect, url_for, flash
from datetime import datetime
import secrets
from .db import get_connection
from webapp.auth import login_required
from .routes_utils import init_data_for_event
# Bot und Variablen importieren
from bot.bot import bot, update_discord_event_embeds, CURRENT_EVENT_ID, trigger_embed_update

bp = Blueprint("routes", __name__)

def german_datetime_format(dt_str):
    if not dt_str:
        return ""
    try:
        dt = datetime.fromisoformat(dt_str)
        return dt.strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return str(dt_str)

@bp.route("/")
@login_required
def index():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT id, name, date_eventstart FROM events ORDER BY id DESC")
    events = c.fetchall()
    conn.close()
    return render_template("index.html", events=events)

@bp.route("/create_event", methods=["GET", "POST"])
@login_required
def create_event():
    """
    Ein neues Event anlegen, inklusive optionalem Wiederholungsmuster.
    """
    if request.method == "POST":
        name = request.form.get("name")
        description = request.form.get("description")
        date_briefing = request.form.get("date_briefing")
        date_eventstart = request.form.get("date_eventstart")
        date_gamestart = request.form.get("date_gamestart")
        server_info = request.form.get("server_info")
        password = request.form.get("password")

        inf_a = int(request.form.get("inf_squads_allies"))
        tank_a = int(request.form.get("tank_squads_allies"))
        sniper_a = int(request.form.get("sniper_squads_allies"))
        inf_x = int(request.form.get("inf_squads_axis"))
        tank_x = int(request.form.get("tank_squads_axis"))
        sniper_x = int(request.form.get("sniper_squads_axis"))
        cmd_a = int(request.form.get("max_commanders_allies"))
        cmd_x = int(request.form.get("max_commanders_axis"))

        recurrence_pattern = request.form.get("recurrence_pattern", "none")

        conn = get_connection()
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO events (
                name, description, date_briefing, date_eventstart, date_gamestart,
                server_info, password,
                inf_squads_allies, tank_squads_allies, sniper_squads_allies,
                inf_squads_axis, tank_squads_axis, sniper_squads_axis,
                max_commanders_allies, max_commanders_axis,
                created_at,
                recurrence_pattern,
                spawned_next_event
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,
                     ?,?)
            """,
            (
                name, description, date_briefing, date_eventstart, date_gamestart,
                server_info, password,
                inf_a, tank_a, sniper_a,
                inf_x, tank_x, sniper_x,
                cmd_a, cmd_x,
                datetime.now(),
                recurrence_pattern,
                0  # spawned_next_event=0
            ),
        )
        conn.commit()
        conn.close()

        return redirect(url_for("routes.index"))
    else:
        return render_template("create_event.html")

@bp.route("/edit_event/<int:event_id>", methods=["GET", "POST"])
@login_required
def edit_event(event_id):
    """
    Formular zum Bearbeiten eines bestehenden Events.
    Ändert die DB und aktualisiert bei Bedarf den Discord-Embed.
    """
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM events WHERE id = ?", (event_id,))
    row = c.fetchone()

    if not row:
        conn.close()
        return "Event nicht gefunden.", 404

    columns = [desc[0] for desc in c.description]
    event_data = dict(zip(columns, row))
    conn.close()

    if request.method == "POST":
        new_name = request.form.get("name")
        new_description = request.form.get("description")
        new_briefing = request.form.get("date_briefing")
        new_eventstart = request.form.get("date_eventstart")
        new_gamestart = request.form.get("date_gamestart")
        new_server_info = request.form.get("server_info")
        new_password = request.form.get("password")

        new_inf_a = int(request.form.get("inf_squads_allies"))
        new_tank_a = int(request.form.get("tank_squads_allies"))
        new_sniper_a = int(request.form.get("sniper_squads_allies"))
        new_inf_x = int(request.form.get("inf_squads_axis"))
        new_tank_x = int(request.form.get("tank_squads_axis"))
        new_sniper_x = int(request.form.get("sniper_squads_axis"))
        new_cmd_a = int(request.form.get("max_commanders_allies"))
        new_cmd_x = int(request.form.get("max_commanders_axis"))

        new_recurrence = request.form.get("recurrence_pattern", "none")

        conn2 = get_connection()
        c2 = conn2.cursor()
        c2.execute(
            """
            UPDATE events
            SET
                name = ?,
                description = ?,
                date_briefing = ?,
                date_eventstart = ?,
                date_gamestart = ?,
                server_info = ?,
                password = ?,
                inf_squads_allies = ?,
                tank_squads_allies = ?,
                sniper_squads_allies = ?,
                inf_squads_axis = ?,
                tank_squads_axis = ?,
                sniper_squads_axis = ?,
                max_commanders_allies = ?,
                max_commanders_axis = ?,
                recurrence_pattern = ?
            WHERE id = ?
            """,
            (
                new_name,
                new_description,
                new_briefing,
                new_eventstart,
                new_gamestart,
                new_server_info,
                new_password,
                new_inf_a,
                new_tank_a,
                new_sniper_a,
                new_inf_x,
                new_tank_x,
                new_sniper_x,
                new_cmd_a,
                new_cmd_x,
                new_recurrence,
                event_id
            ),
        )
        conn2.commit()
        conn2.close()

        # Falls dieses Event das aktuelle im Bot ist, Embeds aktualisieren
        if event_id == CURRENT_EVENT_ID:
            trigger_embed_update()

        return redirect(url_for("routes.event_detail", event_id=event_id))
    else:
        # GET => Edit-Form anzeigen (Daten vorbefüllt)
        return render_template("edit_event.html", event=event_data)

@bp.route("/delete_event/<int:event_id>", methods=["GET", "POST"])
@login_required
def delete_event(event_id):
    """
    Löscht ein Event (und zugehörige Signups) nach Bestätigung.
    """
    if request.method == "POST":
        conn = get_connection()
        c = conn.cursor()
        c.execute("DELETE FROM signups WHERE event_id = ?", (event_id,))
        c.execute("DELETE FROM events WHERE id = ?", (event_id,))
        conn.commit()
        conn.close()
        return redirect(url_for("routes.index"))
    else:
        return render_template("confirm_delete.html", event_id=event_id)

@bp.route("/event/<int:event_id>")
@login_required
def event_detail(event_id):
    """
    Detailseite mit Anzeige aller Anmeldungen (aktive).
    """
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM events WHERE id = ?", (event_id,))
    event_row = c.fetchone()
    if not event_row:
        conn.close()
        return "Event nicht gefunden.", 404

    columns = [desc[0] for desc in c.description]
    event_data = dict(zip(columns, event_row))

    event_data["date_briefing"] = german_datetime_format(event_data["date_briefing"])
    event_data["date_eventstart"] = german_datetime_format(event_data["date_eventstart"])
    event_data["date_gamestart"] = german_datetime_format(event_data["date_gamestart"])

    c.execute(
        """
        SELECT user_name, seite, rolle, status
        FROM signups
        WHERE event_id = ?
          AND status = 'active'
        ORDER BY id ASC
        """,
        (event_id,),
    )
    signups = c.fetchall()
    conn.close()

    allies_data = {
        "inf": [],
        "tank": [],
        "sniper": [],
        "commander": []
    }
    axis_data = {
        "inf": [],
        "tank": [],
        "sniper": [],
        "commander": []
    }

    squad_sizes = {
        "inf": 6,
        "tank": 3,
        "sniper": 2,
        "commander": 1
    }

    def chunk_players_into_squads(player_names, chunk_size):
        return [
            player_names[i:i+chunk_size]
            for i in range(0, len(player_names), chunk_size)
        ]

    allies_temp = { "inf": [], "tank": [], "sniper": [], "commander": [] }
    axis_temp = { "inf": [], "tank": [], "sniper": [], "commander": [] }

    for user_name, seite, rolle, status in signups:
        if seite == "allies" and rolle in allies_temp:
            allies_temp[rolle].append(user_name)
        elif seite == "axis" and rolle in axis_temp:
            axis_temp[rolle].append(user_name)

    for rolle, names in allies_temp.items():
        allies_data[rolle] = chunk_players_into_squads(names, squad_sizes.get(rolle, 6))
    for rolle, names in axis_temp.items():
        axis_data[rolle] = chunk_players_into_squads(names, squad_sizes.get(rolle, 6))

    return render_template(
        "event_detail.html",
        event=event_data,
        allies_data=allies_data,
        axis_data=axis_data
    )

@bp.route("/register/<token>", methods=["GET", "POST"])
def register_via_invite(token):
    """
    Registriert einen neuen User per Einladungslink (token).
    """
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT id, used FROM invites WHERE token = ?", (token,))
    row = c.fetchone()
    if not row:
        conn.close()
        flash("Ungültiger oder abgelaufener Einladungs-Link!", "danger")
        return redirect(url_for("auth.login"))

    invite_id, used_flag = row
    if used_flag:
        conn.close()
        flash("Dieser Einladungscode wurde bereits benutzt.", "danger")
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        # Prüfen, ob Username schon existiert
        c.execute("SELECT id FROM users WHERE username = ?", (username,))
        user_row = c.fetchone()
        if user_row:
            flash("Benutzername bereits vergeben!", "warning")
            conn.close()
            return redirect(request.url)

        import bcrypt
        hashed_pw = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
        c.execute("INSERT INTO users (username, password_hash) VALUES (?,?)", (username, hashed_pw))

        c.execute("UPDATE invites SET used=1 WHERE id=?", (invite_id,))
        conn.commit()
        conn.close()

        flash("Registrierung erfolgreich! Du kannst dich jetzt einloggen.", "success")
        return redirect(url_for("auth.login"))

    conn.close()
    return render_template("register.html", token=token)
