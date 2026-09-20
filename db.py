import mysql.connector
from contextlib import contextmanager
from functools import wraps
from flask import current_app, g, request, session


@contextmanager
def transaction():
    """Group writes and activity records in one request-local transaction."""
    if g.get("db_transaction") is not None:
        raise RuntimeError("Nested transactions are not supported")
    conn = get_conn()
    state = {"rollback": [], "commit": []}
    g.db_transaction = state
    try:
        yield
    except BaseException:
        try:
            conn.rollback()
        finally:
            for callback in reversed(state["rollback"]):
                callback()
        raise
    else:
        try:
            conn.commit()
        except Exception:
            # A lost connection can make the commit outcome unknowable. Keep
            # uploaded bytes: removing them could corrupt a committed record.
            current_app.logger.exception("Commit failed; retained files for reconciliation")
            conn.rollback()
            raise
        for callback in state["commit"]:
            callback()
    finally:
        g.pop("db_transaction", None)


def after_commit(callback):
    g.db_transaction["commit"].append(callback)


def after_rollback(callback):
    g.db_transaction["rollback"].append(callback)


def transactional(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if request.method != "POST":
            return view(*args, **kwargs)
        flashes = list(session.get("_flashes", []))
        try:
            with transaction():
                # Serialize project mutations, including uploads vs deletion.
                # Locking reads also see the latest committed ownership state.
                pid = kwargs.get("pid")
                if pid is not None:
                    fetchone("SELECT id FROM projects WHERE id=%s FOR UPDATE", (pid,))
                return view(*args, **kwargs)
        except Exception:
            session["_flashes"] = flashes
            raise
    return wrapper


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
    try:
        cur.execute(sql, params or ())
        return cur.fetchone()
    finally:
        cur.close()


def fetchall(sql, params=None):
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(sql, params or ())
        return cur.fetchall()
    finally:
        cur.close()


def execute(sql, params=None):
    """
    Execute one statement; commit only outside an explicit transaction.
    Returns lastrowid when available.
    """
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(sql, params or ())
        last_id = cur.lastrowid
        if g.get("db_transaction") is None:
            conn.commit()
        return last_id
    except Exception:
        if g.get("db_transaction") is None:
            conn.rollback()
        raise
    finally:
        cur.close()


def executemany(sql, seq_params):
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.executemany(sql, seq_params)
        if g.get("db_transaction") is None:
            conn.commit()
    except Exception:
        if g.get("db_transaction") is None:
            conn.rollback()
        raise
    finally:
        cur.close()
