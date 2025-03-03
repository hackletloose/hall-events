# Datei: webapp/auth.py

from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from functools import wraps
from datetime import datetime
import bcrypt
import secrets

from .db import get_connection

bp = Blueprint("auth", __name__)

def login_required(f):
    """
    Dekorator, um geschützte Routen zu kennzeichnen. 
    Wenn der Nutzer nicht eingeloggt ist, wird er zur Login-Seite umgeleitet.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated_function

def manager_required(f):
    """
    Dekorator für die Userverwaltung. 
    Erlaubt Zugriff, wenn role in ['admin','manager'].
    Da 'superadmin' jetzt mit role='manager' angelegt ist, 
    hat er automatisch Zugriffsrechte.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("logged_in"):
            flash("Bitte einloggen.", "warning")
            return redirect(url_for("auth.login"))
        user_role = session.get("role")
        if user_role not in ["admin", "manager"]:
            flash("Keine Berechtigung für die Userverwaltung.", "danger")
            return redirect(url_for("routes.index"))
        return f(*args, **kwargs)
    return decorated_function


@bp.route("/login", methods=["GET", "POST"])
def login():
    """
    Zeigt das Login-Formular und prüft die Logindaten. 
    Bei Erfolg: Session (username, logged_in, role).
    """
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        conn = get_connection()
        c = conn.cursor()
        c.execute("""
            SELECT id, username, password_hash, role
            FROM users
            WHERE username = ?
        """, (username,))
        row = c.fetchone()
        conn.close()

        if row:
            user_id, db_username, db_password_hash, db_role = row
            if bcrypt.checkpw(password.encode("utf-8"), db_password_hash):
                session["logged_in"] = True
                session["username"] = db_username
                session["role"] = db_role
                flash("Login erfolgreich!", "success")
                return redirect(url_for("routes.index"))
        
        flash("Falscher Benutzername oder Passwort!", "danger")
        return redirect(url_for("auth.login"))

    return render_template("login.html")


@bp.route("/logout")
def logout():
    """
    Löscht die Session, so dass der Nutzer ausgeloggt ist.
    """
    session.clear()
    flash("Du wurdest ausgeloggt.", "info")
    return redirect(url_for("auth.login"))


# --- USER-VERWALTUNG ---

@bp.route("/admin/users")
@manager_required
def list_users():
    """
    Zeigt alle Benutzer in der Datenbank an.
    Nur für Admin/Manager (=> schließt superadmin = manager ein).
    """
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT id, username, role FROM users ORDER BY id ASC")
    all_users = c.fetchall()
    conn.close()
    return render_template("admin_users.html", all_users=all_users)


@bp.route("/admin/users/delete/<int:user_id>", methods=["POST"])
@manager_required
def delete_user(user_id):
    """
    Löscht einen Benutzer anhand seiner ID.
    Falls der Benutzer 'superadmin' ist, wird system_settings.superadmin_deleted=1 gesetzt,
    sodass er nicht erneut erzeugt wird.
    """
    conn = get_connection()
    c = conn.cursor()

    c.execute("SELECT username FROM users WHERE id = ?", (user_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        flash("Benutzer nicht gefunden.", "warning")
        return redirect(url_for("auth.list_users"))

    del_username = row[0]

    # Falls 'superadmin', => superadmin_deleted=1
    if del_username == "superadmin":
        c.execute("UPDATE system_settings SET superadmin_deleted=1 WHERE id=1")

    c.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()

    flash(f"Benutzer '{del_username}' wurde gelöscht.", "info")
    return redirect(url_for("auth.list_users"))


@bp.route("/admin/users/change_role/<int:user_id>", methods=["GET", "POST"])
@manager_required
def change_role(user_id):
    """
    Ändert die Rolle eines Users.
    """
    conn = get_connection()
    c = conn.cursor()

    c.execute("SELECT id, username, role FROM users WHERE id = ?", (user_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        flash("Benutzer nicht gefunden.", "warning")
        return redirect(url_for("auth.list_users"))

    current_id, current_username, current_role = row

    if request.method == "POST":
        new_role = request.form.get("role")
        c.execute("UPDATE users SET role=? WHERE id=?", (new_role, user_id))
        conn.commit()
        conn.close()

        flash(f"Rolle von Benutzer '{current_username}' wurde geändert zu '{new_role}'.", "success")
        return redirect(url_for("auth.list_users"))
    else:
        conn.close()
        return render_template("change_role.html",
                               user_id=current_id,
                               username=current_username,
                               role=current_role)


# --- EINLADUNGEN ---

@bp.route("/admin/users/invite")
@manager_required
def invite_user():
    """
    Erzeugt einen neuen Token und zeigt ihn als Link an.
    Der Empfänger dieses Links kann sich selber registrieren.
    Nur für Admin/Manager.
    """
    token = secrets.token_urlsafe(16)
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        INSERT INTO invites (token, used, created_at)
        VALUES (?,?,?)
    """, (token, False, datetime.now()))
    conn.commit()
    conn.close()

    invite_link = url_for('auth.register_via_invite', token=token, _external=True)
    return render_template("invite_created.html", invite_link=invite_link)


@bp.route("/register/<token>", methods=["GET", "POST"])
def register_via_invite(token):
    """
    Registrierungs-Route für neue User per Einladungslink. 
    Prüft, ob der Token existiert und ungenutzt ist.
    Legt mit role='user' an.
    """
    conn = get_connection()
    c = conn.cursor()

    c.execute("SELECT id, used FROM invites WHERE token=?", (token,))
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
        new_username = request.form.get("username")
        new_password = request.form.get("password")

        # Prüfen, ob Username schon existiert
        c.execute("SELECT id FROM users WHERE username = ?", (new_username,))
        user_row = c.fetchone()
        if user_row:
            flash("Benutzername bereits vergeben!", "warning")
            conn.close()
            return redirect(request.url)

        hashed_pw = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt())
        c.execute("""
            INSERT INTO users (username, password_hash, role)
            VALUES (?,?,?)
        """, (new_username, hashed_pw, "user"))

        c.execute("UPDATE invites SET used=1 WHERE id=?", (invite_id,))
        conn.commit()
        conn.close()

        flash("Registrierung erfolgreich! Du kannst dich jetzt einloggen.", "success")
        return redirect(url_for("auth.login"))

    conn.close()
    return render_template("register.html", token=token)
