from datetime import datetime
from .db import get_connection

def get_event_dict(event_id: int):
    """
    Lädt alle Spalten des Events mit der angegebenen ID.
    Gibt ein Dict oder None zurück.
    """
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM events WHERE id=?", (event_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return None  # oder {}
    cols = [desc[0] for desc in c.description]
    result = dict(zip(cols, row))
    conn.close()
    return result

def init_data_for_event(event_id=None):
    """
    Dummy-Funktion, damit kein Importfehler entsteht.
    """
    data = {
        "info": "init_data_for_event wurde aufgerufen",
        "event_id": event_id
    }
    return data

def get_active_event():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM events ORDER BY id DESC LIMIT 1")
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    cols = [desc[0] for desc in c.description]
    return dict(zip(cols, row))

def get_slots_for_role(event_dict, seite, rolle):
    """
    Berechnet anhand der Event-Daten, wie viele 'active' Slots für (seite, rolle) existieren.
    seite: 'allies' oder 'axis'
    rolle: 'inf', 'tank', 'sniper', 'commander'
    """
    if rolle == "inf":
        return event_dict["inf_squads_allies"] * 6 if seite == "allies" else event_dict["inf_squads_axis"] * 6
    elif rolle == "tank":
        return event_dict["tank_squads_allies"] * 3 if seite == "allies" else event_dict["tank_squads_axis"] * 3
    elif rolle == "sniper":
        return event_dict["sniper_squads_allies"] * 2 if seite == "allies" else event_dict["sniper_squads_axis"] * 2
    elif rolle == "commander":
        return event_dict["max_commanders_allies"] if seite == "allies" else event_dict["max_commanders_axis"]
    # admin entfällt komplett
    return 0

def count_signups(event_id, seite, rolle):
    """
    Zählt, wie viele 'active' Anmeldungen es für (seite, rolle) bei dem Event (event_id) gibt.
    """
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT COUNT(*)
        FROM signups
        WHERE event_id = ?
          AND seite = ?
          AND rolle = ?
          AND status = 'active'
    """, (event_id, seite, rolle))
    count_active = c.fetchone()[0]
    conn.close()
    return count_active

def create_signup(event_id, user_id, user_name, seite, rolle, status="active"):
    """
    Legt einen Eintrag in signups an.
    """
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        INSERT INTO signups (event_id, user_id, user_name, seite, rolle, status, created_at)
        VALUES (?,?,?,?,?,?,?)
    """, (event_id, user_id, user_name, seite, rolle, status, datetime.now()))
    conn.commit()
    conn.close()

def activate_waiting_signup(event_id, seite, rolle):
    """
    Aktiviert den ältesten 'waiting'-Eintrag für (seite, rolle).
    Gibt (wait_id, user_id) zurück, falls ein Eintrag gefunden wurde, sonst None.
    """
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT id, user_id
        FROM signups
        WHERE event_id = ?
          AND seite = ?
          AND rolle = ?
          AND status = 'waiting'
        ORDER BY id ASC
        LIMIT 1
    """, (event_id, seite, rolle))
    row = c.fetchone()
    if row:
        wait_id, wait_user_id = row
        c.execute("UPDATE signups SET status = 'active' WHERE id = ?", (wait_id,))
        conn.commit()
        conn.close()
        return (wait_id, wait_user_id)
    conn.close()
    return None

def cancel_signup(user_id):
    """
    Markiert die neueste 'active'-Anmeldung des Users als 'cancelled'
    und ruft ggf. den ersten Wartelistenplatz auf.
    
    Gibt (signup_id, event_id, seite, rolle, wait_row) zurück,
    oder None, wenn der User nicht 'active' war.
    """
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT id, event_id, seite, rolle
        FROM signups
        WHERE user_id = ?
          AND status = 'active'
        ORDER BY id DESC
        LIMIT 1
    """, (user_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return None

    signup_id, event_id, seite, rolle = row
    c.execute("UPDATE signups SET status = 'cancelled' WHERE id = ?", (signup_id,))
    conn.commit()

    # Nachrücker
    c.execute("""
        SELECT id, user_id
        FROM signups
        WHERE event_id = ?
          AND seite = ?
          AND rolle = ?
          AND status = 'waiting'
        ORDER BY id ASC
        LIMIT 1
    """, (event_id, seite, rolle))
    wait_row = c.fetchone()
    if wait_row:
        wait_id, wait_user_id = wait_row
        c.execute("UPDATE signups SET status = 'active' WHERE id = ?", (wait_id,))
        conn.commit()

    conn.close()
    return (signup_id, event_id, seite, rolle, wait_row)
