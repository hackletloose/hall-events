# Datei: webapp/db.py

import os
import sqlite3
import bcrypt
import secrets
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
DB_PATH = os.getenv("DB_PATH", "events.db")

def get_connection():
    """
    Stellt eine Verbindung zur SQLite-Datenbank her.
    """
    return sqlite3.connect(DB_PATH)

def init_db():
    """
    Erzeugt (falls nicht vorhanden) alle benötigten Tabellen,
    inkl. der Spalten 'recurrence_pattern', 'spawned_next_event',
    'posted_in_discord' in 'events'.
    Außerdem einmaligen Superadmin-User (manager).
    """
    conn = get_connection()
    c = conn.cursor()

    # Tabelle: Events
    c.execute("""
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        description TEXT,
        date_briefing DATETIME,
        date_eventstart DATETIME,
        date_gamestart DATETIME,
        server_info TEXT,
        password TEXT,

        inf_squads_allies INTEGER,
        tank_squads_allies INTEGER,
        sniper_squads_allies INTEGER,

        inf_squads_axis INTEGER,
        tank_squads_axis INTEGER,
        sniper_squads_axis INTEGER,

        max_commanders_allies INTEGER,
        max_commanders_axis  INTEGER,

        created_at DATETIME,

        -- Für Wiederholungen
        recurrence_pattern TEXT DEFAULT 'none',
        spawned_next_event INTEGER DEFAULT 0,

        -- Damit wir Events erst 7 Tage vor dem Start posten:
        posted_in_discord  INTEGER DEFAULT 0
    )
    """)

    # Tabelle: Signups
    c.execute("""
    CREATE TABLE IF NOT EXISTS signups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id INTEGER,
        user_id TEXT,
        user_name TEXT,
        seite TEXT,
        rolle TEXT,
        status TEXT,
        created_at DATETIME
    )
    """)

    # Tabelle: Bot-State
    c.execute("""
    CREATE TABLE IF NOT EXISTS bot_state (
        id INTEGER PRIMARY KEY CHECK (id=1),
        event_channel_id TEXT,
        current_event_id INTEGER,
        current_info_message_id TEXT,
        current_allies_message_id TEXT,
        current_axis_message_id TEXT
    )
    """)
    # Sicherstellen, dass Datensatz id=1 existiert
    c.execute("SELECT id FROM bot_state WHERE id=1")
    row = c.fetchone()
    if not row:
        c.execute("""
            INSERT INTO bot_state (
                id,
                event_channel_id,
                current_event_id,
                current_info_message_id,
                current_allies_message_id,
                current_axis_message_id
            ) VALUES (1, NULL, NULL, NULL, NULL, NULL)
        """)

    # Tabelle: Users
    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password_hash TEXT,
        role TEXT DEFAULT 'user'
    )
    """)

    # Tabelle: invites
    c.execute("""
    CREATE TABLE IF NOT EXISTS invites (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        token TEXT UNIQUE,
        used BOOLEAN DEFAULT 0,
        created_at DATETIME
    )
    """)

    # Zusatztabelle: system_settings
    c.execute("""
    CREATE TABLE IF NOT EXISTS system_settings (
        id INTEGER PRIMARY KEY CHECK(id=1),
        superadmin_deleted BOOLEAN DEFAULT 0
    )
    """)
    c.execute("SELECT superadmin_deleted FROM system_settings WHERE id=1")
    row2 = c.fetchone()
    if not row2:
        c.execute("INSERT INTO system_settings (id, superadmin_deleted) VALUES (1, 0)")

    # Superadmin-Check
    c.execute("SELECT superadmin_deleted FROM system_settings WHERE id=1")
    superadmin_deleted = c.fetchone()[0]  # 0 oder 1

    if not superadmin_deleted:
        c.execute("SELECT id FROM users WHERE username = 'superadmin'")
        su = c.fetchone()
        if not su:
            # superadmin noch nicht angelegt -> anlegen
            random_pw = secrets.token_urlsafe(10)
            hashed_pw = bcrypt.hashpw(random_pw.encode("utf-8"), bcrypt.gensalt())
            c.execute("""
                INSERT INTO users (username, password_hash, role)
                VALUES (?,?,?)
            """, ("superadmin", hashed_pw, "manager"))

            print("="*50)
            print(" SUPERADMIN-USER WURDE ANGELEGT (ROLLE = 'manager') ")
            print(f" Benutzername: superadmin")
            print(f" Passwort:     {random_pw}")
            print(" Bitte notiere dir das Passwort (es wird nicht erneut angezeigt).")
            print("="*50)

    conn.commit()
    conn.close()

    print("[init_db] Datenbank initialisiert.")

#
# Wenn du bereits eine bestehende DB hast und nur die Spalte posted_in_discord
# ergänzen willst, kannst du in einer SQLite-Konsole (o.ä.) Folgendes ausführen:
#
# ALTER TABLE events ADD COLUMN posted_in_discord INTEGER DEFAULT 0;
#
# Falls du 'recurrence_pattern' und 'spawned_next_event' ebenfalls nachträglich
# brauchst:
#
# ALTER TABLE events ADD COLUMN recurrence_pattern TEXT DEFAULT 'none';
# ALTER TABLE events ADD COLUMN spawned_next_event INTEGER DEFAULT 0;
#
