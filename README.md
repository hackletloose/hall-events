# Discord Event Manager

Dieses Repository enthält eine Anwendung, die einen Discord-Bot und eine Flask-Webapp kombiniert, um Events zu verwalten. Der Bot ermöglicht es Nutzern, sich über Discord für Events anzumelden, und die Web-App stellt zusätzliche Verwaltungsfunktionen bereit – etwa zur Datenbankinitialisierung und zur Verwaltung von wiederkehrenden Events.

## Inhaltsverzeichnis

- [Funktionen](#funktionen)
- [Installation](#installation)
- [Konfiguration](#konfiguration)
- [Start der Anwendung](#start-der-anwendung)
- [Projektstruktur](#projektstruktur)
- [Beitrag & Lizenz](#beitrag--lizenz)

## Funktionen

- **Flask Web-App:** Startet im Hintergrund und initialisiert die Datenbank (sofern nicht vorhanden).
- **Discord Bot:**  
  - Registrierung und Verwaltung von Anmeldungen für Events über interaktive Buttons und Dropdowns.
  - Anzeige von Event-Infos, Lineups (Allies & Axis) und dynamische Aktualisierung von Embeds.
  - Automatische Erinnerungen (z. B. Versand des Event-Passworts 24 Stunden vor Beginn).
  - Unterstützung wiederkehrender Events mit automatischer Erzeugung und Discord-Posting des Folgetermins.
- **Persistente Bot-States:** Speichert den aktuellen Zustand des Bots (u.a. Nachrichten-IDs, Kanal-ID) in der Datenbank.

## Installation

1. **Repository klonen:**

   ```bash
   git clone https://github.com/hackletloose/hall-events.git
   cd hall-events
   ```

2. Virtuelle Umgebung erstellen (optional, aber empfohlen):
  ```bash
  source venv/bin/activate
  ```

3. Abhängigkeiten installieren:
   ```bash
   pip install -r requirements.txt
   ```

## Konfiguration
Erstelle eine `.env`-Datei im Root-Verzeichnis mit den folgenden Umgebungsvariablen:
```env
# Flask Konfiguration
FLASK_HOST=127.0.0.1
FLASK_PORT=5000

# Discord Bot Token
DISCORD_BOT_TOKEN=dein_discord_bot_token
```
## Start der Anwendung
```bash
python main.py
```
## Beitrag & Lizenz
Beiträge sind willkommen! Bitte eröffne ein Issue oder einen Pull Request, um Verbesserungen vorzuschlagen.
Dieses Projekt wird unter der MIT-Lizenz veröffentlicht.
