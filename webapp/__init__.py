from flask import Flask
from .db import init_db
from .routes import bp as routes_bp
from webapp.auth import bp as auth_bp

def create_app():
    app = Flask(__name__)
    app.secret_key = "irgendein-string"  # Für Session/CSRF
    
    init_db()  # Stelle sicher, dass DB existiert
    
    # Routen / Blueprint registrieren
    app.register_blueprint(routes_bp)
    app.register_blueprint(auth_bp)        # unser neues auth.py
    
    return app
