# Datei: webapp/routes.py

import asyncio
from flask import Blueprint, render_template, request, redirect, url_for, flash
from datetime import datetime
import secrets

from .db import get_connection
from webapp.auth import login_required
from .routes_utils import get_event_dict  # neu definierte Funktion
# (oder init_data_for_event etc. falls du anderes brauchst)

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
    """
    Zeigt alle Events in absteigender Reihenfolge
    """
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT id, name, date_eventstart FROM events ORDER BY id DESC")
    events = c.fetchall()
    conn.close()
    return render_template("index.html", events=events)

@bp.route("/create_event", methods=["GET","POST"])
@login_required
def create_event():
    """
    Legt ein neues Event an (posted_in_discord=0)
    => Bot postet es später automatisch
    """
    if request.method=="POST":
        name = request.form.get("name")
        description = request.form.get("description")
        date_briefing = request.form.get("date_briefing")
        date_eventstart = request.form.get("date_eventstart")
        date_gamestart = request.form.get("date_gamestart")
        server_info = request.form.get("server_info")
        password = request.form.get("password")

        inf_a = int(request.form.get("inf_squads_allies"))
        tank_a= int(request.form.get("tank_squads_allies"))
        snp_a = int(request.form.get("sniper_squads_allies"))
        inf_x = int(request.form.get("inf_squads_axis"))
        tank_x= int(request.form.get("tank_squads_axis"))
        snp_x = int(request.form.get("sniper_squads_axis"))
        cmd_a = int(request.form.get("max_commanders_allies"))
        cmd_x = int(request.form.get("max_commanders_axis"))

        rec_pat= request.form.get("recurrence_pattern","none")

        conn= get_connection()
        c= conn.cursor()
        c.execute("""
            INSERT INTO events (
                name, description, date_briefing, date_eventstart, date_gamestart,
                server_info, password,
                inf_squads_allies, tank_squads_allies, sniper_squads_allies,
                inf_squads_axis, tank_squads_axis, sniper_squads_axis,
                max_commanders_allies, max_commanders_axis,
                created_at,
                recurrence_pattern,
                spawned_next_event,
                posted_in_discord
            )
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,
                    ?,?,?)
        """,(
            name, description,
            date_briefing, date_eventstart, date_gamestart,
            server_info, password,
            inf_a, tank_a, snp_a,
            inf_x, tank_x, snp_x,
            cmd_a, cmd_x,
            datetime.now(),
            rec_pat,
            0,
            0  # posted_in_discord=0 => Bot postet es
        ))
        conn.commit()
        conn.close()

        return redirect(url_for("routes.index"))
    else:
        return render_template("create_event.html")

@bp.route("/edit_event/<int:event_id>", methods=["GET","POST"])
@login_required
def edit_event(event_id):
    """
    Bearbeitet ein vorhandenes Event
    """
    conn= get_connection()
    c= conn.cursor()
    c.execute("SELECT * FROM events WHERE id=?", (event_id,))
    row= c.fetchone()
    if not row:
        conn.close()
        return "Event nicht gefunden",404

    cols= [desc[0] for desc in c.description]
    event_data= dict(zip(cols,row))
    conn.close()

    if request.method=="POST":
        new_name= request.form.get("name")
        new_desc= request.form.get("description")
        new_brief= request.form.get("date_briefing")
        new_evst = request.form.get("date_eventstart")
        new_gmst = request.form.get("date_gamestart")
        new_serv = request.form.get("server_info")
        new_pw   = request.form.get("password")

        new_inf_a = int(request.form.get("inf_squads_allies"))
        new_tnk_a = int(request.form.get("tank_squads_allies"))
        new_snp_a = int(request.form.get("sniper_squads_allies"))
        new_inf_x = int(request.form.get("inf_squads_axis"))
        new_tnk_x = int(request.form.get("tank_squads_axis"))
        new_snp_x = int(request.form.get("sniper_squads_axis"))
        new_cmd_a = int(request.form.get("max_commanders_allies"))
        new_cmd_x = int(request.form.get("max_commanders_axis"))

        new_recur= request.form.get("recurrence_pattern","none")

        conn2= get_connection()
        c2= conn2.cursor()
        c2.execute("""
            UPDATE events
            SET
                name=?,
                description=?,
                date_briefing=?,
                date_eventstart=?,
                date_gamestart=?,
                server_info=?,
                password=?,
                inf_squads_allies=?,
                tank_squads_allies=?,
                sniper_squads_allies=?,
                inf_squads_axis=?,
                tank_squads_axis=?,
                sniper_squads_axis=?,
                max_commanders_allies=?,
                max_commanders_axis=?,
                recurrence_pattern=?
            WHERE id=?
        """,(
            new_name,new_desc,
            new_brief,new_evst,new_gmst,
            new_serv,new_pw,
            new_inf_a,new_tnk_a,new_snp_a,
            new_inf_x,new_tnk_x,new_snp_x,
            new_cmd_a,new_cmd_x,
            new_recur,
            event_id
        ))
        conn2.commit()
        conn2.close()

        return redirect(url_for("routes.event_detail", event_id=event_id))
    else:
        return render_template("edit_event.html", event=event_data)

@bp.route("/delete_event/<int:event_id>", methods=["GET","POST"])
@login_required
def delete_event(event_id):
    """
    Löscht das Event + zugehörige Signups
    """
    if request.method=="POST":
        conn= get_connection()
        c= conn.cursor()
        c.execute("DELETE FROM signups WHERE event_id=?", (event_id,))
        c.execute("DELETE FROM events WHERE id=?", (event_id,))
        conn.commit()
        conn.close()
        return redirect(url_for("routes.index"))
    else:
        return render_template("confirm_delete.html", event_id=event_id)

#
# Hilfs-Funktion, um eine Liste players in 6er,3er,2er etc. zu chunk-en:
#
def chunk_players_into_squads(player_names, chunk_size):
    return [
        player_names[i:i+chunk_size]
        for i in range(0, len(player_names), chunk_size)
    ]

@bp.route("/event/<int:event_id>")
@login_required
def event_detail(event_id):
    """
    Zeigt Detailseite: Briefing, Server etc. plus Allies/Axis-Squads
    """
    event_row = get_event_dict(event_id)
    if not event_row:
        return "Event nicht gefunden",404

    # Datumsformat
    event_row["date_briefing"]   = german_datetime_format(event_row["date_briefing"])
    event_row["date_eventstart"] = german_datetime_format(event_row["date_eventstart"])
    event_row["date_gamestart"]  = german_datetime_format(event_row["date_gamestart"])

    # Anmeldungen
    conn= get_connection()
    c= conn.cursor()
    c.execute("""
        SELECT user_name, seite, rolle, status
        FROM signups
        WHERE event_id=?
          AND status='active'
        ORDER BY id ASC
    """,(event_id,))
    signups= c.fetchall()
    conn.close()

    # Temporär Allies / Axis
    allies_temp = {
        "inf": [],
        "tank": [],
        "sniper": [],
        "commander": []
    }
    axis_temp = {
        "inf": [],
        "tank": [],
        "sniper": [],
        "commander": []
    }

    for user_name, seite, rolle, st in signups:
        if seite=="allies" and rolle in allies_temp:
            allies_temp[rolle].append(user_name)
        elif seite=="axis" and rolle in axis_temp:
            axis_temp[rolle].append(user_name)

    # Squadgrößen
    squad_sizes= {
        "inf": 6,
        "tank": 3,
        "sniper": 2,
        "commander": 1
    }

    # Allies final:
    allies_data= {
        "inf": [],
        "tank": [],
        "sniper": [],
        "commander": []
    }
    for rolle, player_list in allies_temp.items():
        # wir chunk-en die gesammelten Namen in 6er,3er,2er,1er Listen
        s_size= squad_sizes.get(rolle, 6)
        allies_data[rolle] = chunk_players_into_squads(player_list, s_size)

    # Axis final:
    axis_data= {
        "inf": [],
        "tank": [],
        "sniper": [],
        "commander": []
    }
    for rolle, player_list in axis_temp.items():
        s_size= squad_sizes.get(rolle, 6)
        axis_data[rolle] = chunk_players_into_squads(player_list, s_size)

    return render_template(
        "event_detail.html",
        event=event_row,
        allies_data=allies_data,
        axis_data=axis_data
    )

@bp.route("/register/<token>", methods=["GET","POST"])
def register_via_invite(token):
    """
    Registrierung per Einladungslink /register/<token>
    """
    conn= get_connection()
    c= conn.cursor()
    c.execute("SELECT id, used FROM invites WHERE token=?", (token,))
    row= c.fetchone()
    if not row:
        conn.close()
        flash("Ungültiger oder abgelaufener Einladungs-Link!", "danger")
        return redirect(url_for("auth.login"))

    invite_id, used_flag= row
    if used_flag:
        conn.close()
        flash("Dieser Einladungscode wurde bereits benutzt.", "danger")
        return redirect(url_for("auth.login"))

    if request.method=="POST":
        username= request.form.get("username")
        password= request.form.get("password")

        c.execute("SELECT id FROM users WHERE username=?",(username,))
        existing= c.fetchone()
        if existing:
            flash("Benutzername bereits vergeben!", "warning")
            conn.close()
            return redirect(request.url)

        import bcrypt
        hashed_pw= bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
        c.execute("""
            INSERT INTO users (username, password_hash)
            VALUES (?,?)
        """,(username, hashed_pw))
        c.execute("""
            UPDATE invites
            SET used=1
            WHERE id=?
        """,(invite_id,))
        conn.commit()
        conn.close()

        flash("Registrierung erfolgreich! Du kannst dich jetzt einloggen.", "success")
        return redirect(url_for("auth.login"))

    conn.close()
    return render_template("register.html", token=token)
