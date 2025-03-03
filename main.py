# main.py
import os
import threading
from dotenv import load_dotenv

from webapp import create_app
from bot.bot import run_discord_bot

load_dotenv()

def run_flask_app():
    """Erstellt und startet die Flask-App."""
    from webapp.db import init_db
    init_db()  # DB anlegen (wenn nicht vorhanden)
    
    app = create_app()
    host = os.getenv("FLASK_HOST", "127.0.0.1")
    port = int(os.getenv("FLASK_PORT", 5000))
    # WICHTIG: debug=False, weil sonst der Flask-Reloader 2 Threads macht
    app.run(host=host, port=port, debug=False)

if __name__ == "__main__":
    # 1) Flask im Hintergrund starten
    flask_thread = threading.Thread(target=run_flask_app, daemon=True)
    flask_thread.start()

    # 2) Den Bot starten (blockiert, bis Programm beendet wird)
    run_discord_bot()
