import hashlib
import os
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask import session, redirect, url_for, flash, abort, current_app, request, send_file

from db import fetchone, execute


# -----------------------
# Auth helpers
# -----------------------
def hash_password(password: str) -> str:
    return generate_password_hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return check_password_hash(password_hash, password)


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapper


def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    return fetchone(
        "SELECT id, username, email, created_at, profile_image FROM users WHERE id=%s",
        (uid,),
    )


# -----------------------
# Role / permissions
# -----------------------
ROLE_LEVEL = {"member": 1, "admin": 2, "owner": 3}


def get_project_role(project_id: int, user_id: int):
    row = fetchone(
        "SELECT role FROM project_members WHERE project_id=%s AND user_id=%s",
        (project_id, user_id),
    )
    return row["role"] if row else None


def require_project_role(project_id: int, min_role: str):
    """
    Ensures logged-in user has at least min_role in the project.
    """
    uid = session.get("user_id")
    if not uid:
        return redirect(url_for("login"))

    role = get_project_role(project_id, uid)
    if not role:
        abort(403)

    if ROLE_LEVEL.get(role, 0) < ROLE_LEVEL.get(min_role, 999):
        abort(403)


def is_project_owner(project_id: int, user_id: int) -> bool:
    role = get_project_role(project_id, user_id)
    return role == "owner"


# -----------------------
# Upload helpers
# -----------------------
def resolve_upload_path(path: str) -> str:
    """Resolve an upload path and reject escapes, including symlinks."""
    base = os.path.realpath(current_app.config["UPLOAD_FOLDER"])
    resolved = os.path.realpath(os.path.join(base, path))
    try:
        contained = os.path.commonpath([base, resolved]) == base
    except ValueError:
        contained = False
    if not contained or not os.path.isfile(resolved):
        abort(404)
    return resolved


def send_upload(path: str, *, download_name=None, mimetype=None):
    response = send_file(
        path, as_attachment=download_name is not None,
        download_name=download_name, mimetype=mimetype,
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = "sandbox; default-src 'none'"
    response.headers["Cache-Control"] = "private, no-store"
    return response


def allowed_file(filename: str) -> bool:
    if "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in current_app.config["ALLOWED_EXTENSIONS"]


def ensure_project_upload_dir(project_id: int) -> str:
    base = current_app.config["UPLOAD_FOLDER"]
    folder = os.path.join(base, str(project_id))
    os.makedirs(folder, exist_ok=True)
    return folder


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def save_upload(project_id: int, file_storage):
    """
    Saves upload to uploads/<project_id>/<secure_filename>
    Returns (filename, filepath, filesize, sha256)
    """
    filename = secure_filename(file_storage.filename or "")
    if not filename:
        raise ValueError("Invalid filename")

    if not allowed_file(filename):
        raise ValueError("File type not allowed")

    folder = ensure_project_upload_dir(project_id)
    dst = os.path.join(folder, filename)

    # If file exists, make a unique name
    if os.path.exists(dst):
        name, ext = os.path.splitext(filename)
        i = 2
        while True:
            candidate = f"{name}_{i}{ext}"
            dst = os.path.join(folder, candidate)
            if not os.path.exists(dst):
                filename = candidate
                break
            i += 1

    file_storage.save(dst)
    size = os.path.getsize(dst)
    digest = sha256_file(dst)

    # Store relative path in DB (portable)
    relpath = os.path.relpath(dst, current_app.root_path).replace("\\", "/")
    return filename, relpath, size, digest


# -----------------------
# Activity log
# -----------------------
def log_activity(project_id: int, user_id: int | None, action: str, entity_type: str, entity_id: int | None):
    execute(
        """
        INSERT INTO project_activity (project_id, user_id, action, entity_type, entity_id)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (project_id, user_id, action, entity_type, entity_id),
    )
