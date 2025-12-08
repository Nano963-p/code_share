import mysql.connector
import os
from flask import g

DB_CONFIG = {
    'host': os.environ.get('DB_HOST', 'localhost'),
    'user': os.environ.get('DB_USER', 'root'),
    'password': os.environ.get('DB_PASSWORD', 'REDACTED'),
    'database': os.environ.get('DB_NAME', 'mini_github'),
    'autocommit': False
}

def get_db():
    """Obtient une connexion à la base de données"""
    if 'db' not in g:
        try:
            g.db = mysql.connector.connect(**DB_CONFIG)
        except mysql.connector.Error as err:
            print(f"Erreur de connexion à la base de données: {err}")
            raise
    return g.db

def close_db(e=None):
    """Ferme la connexion à la base de données"""
    db = g.pop('db', None)
    if db is not None and db.is_connected():
        db.close()

def init_app(app):
    """Initialise l'application Flask avec la gestion de la base de données"""
    app.teardown_appcontext(close_db)