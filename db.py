import mysql.connector
from flask import current_app, g


def get_conn():
    """
    One MySQL connection per request (stored in flask.g).
    """
    if "db_conn" not in g:
        cfg = current_app.config
        g.db_conn = mysql.connector.connect(
            host=cfg["DB_HOST"],
            port=cfg["DB_PORT"],
            user=cfg["DB_USER"],
            password=cfg["DB_PASSWORD"],
            database=cfg["DB_NAME"],
            autocommit=False,
        )
    return g.db_conn


def close_conn(_err=None):
    conn = g.pop("db_conn", None)
    if conn is not None:
        conn.close()


def fetchone(sql, params=None):
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute(sql, params or ())
    row = cur.fetchone()
    cur.close()
    return row


def fetchall(sql, params=None):
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute(sql, params or ())
    rows = cur.fetchall()
    cur.close()
    return rows


def execute(sql, params=None):
    """
    Execute one statement and commit.
    Returns lastrowid when available.
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(sql, params or ())
    last_id = cur.lastrowid
    conn.commit()
    cur.close()
    return last_id


def executemany(sql, seq_params):
    conn = get_conn()
    cur = conn.cursor()
    cur.executemany(sql, seq_params)
    conn.commit()
    cur.close()
