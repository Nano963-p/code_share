import mysql.connector
from flask import g
import os

def get_db():
    """Obtient une connexion à la base de données"""
    if 'db' not in g:
        g.db = mysql.connector.connect(
            host=os.environ.get('DB_HOST', 'localhost'),
            user=os.environ.get('DB_USER', 'root'),
            password=os.environ.get('DB_PASSWORD', 'REDACTED'),
            database=os.environ.get('DB_NAME', 'codeshare'),
            autocommit=False
        )
    return g.db

def close_db(e=None):
    """Ferme la connexion à la base de données"""
    db = g.pop('db', None)
    if db is not None:
        db.close()

def init_app(app):
    """Initialise l'application avec la base de données"""
    app.teardown_appcontext(close_db)