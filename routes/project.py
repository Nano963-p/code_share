import os
from flask import (
    render_template, request, redirect, url_for, flash, abort,
    send_file, session, current_app
)

from db import fetchone, fetchall, execute
from utils import (
    login_required, require_project_role, current_user,
    is_project_owner, save_upload, log_activity
)


@login_required
def create_project():
    u = current_user()
    uid = u["id"]

    title = (request.form.get("title") or "").strip()
    description = (request.form.get("description") or "").strip()
    # HTML checkbox usually submits "on" (or nothing if unchecked)
    is_private = 1 if (request.form.get("is_private") or "").lower() in {"1", "on", "true", "yes"} else 0

    if len(title) < 3:
        flash("Title must be at least 3 characters.", "error")
        return redirect(url_for("dashboard"))

    pid = execute(
        """
        INSERT INTO projects (owner_id, title, description, is_private)
        VALUES (%s, %s, %s, %s)
        """,
        (uid, title, description or None, is_private),
    )

    log_activity(pid, uid, "created_project", "project", pid)
    return redirect(url_for("project", pid=pid))


@login_required
def project(pid: int):
    u = current_user()
    uid = u["id"]

    # Project info
    p = fetchone(
        """
        SELECT
          p.id, p.title, p.description, p.created_at, p.is_private,
          o.username AS owner_username, p.status
        FROM projects p
        JOIN users o ON o.id=p.owner_id
        WHERE p.id=%s
        """,
        (pid,),
    )
    if not p:
        abort(404)

    # Access rule:
    # - public: any logged user can view
    # - private: must be member
    if p["is_private"]:
        require_project_role(pid, "member")

    # POST actions inside project page:
    if request.method == "POST":
        # upload file
        if "file" in request.files and (request.files["file"].filename or ""):
            require_project_role(pid, "member")
            f = request.files["file"]

            try:
                filename, relpath, size, digest = save_upload(pid, f)
            except ValueError as e:
                flash(str(e), "error")
                return redirect(url_for("project", pid=pid))

            fid = execute(
                """
                INSERT INTO files (project_id, uploaded_by, filename, filepath, filesize, sha256)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (pid, uid, filename, relpath, size, digest),
            )
            log_activity(pid, uid, "uploaded_file", "file", fid)
            flash("File uploaded.", "success")
            return redirect(url_for("project", pid=pid))

        # add comment
        msg = (request.form.get("message") or "").strip()
        if msg:
            require_project_role(pid, "member")
            cid = execute(
                "INSERT INTO comments (project_id, user_id, message) VALUES (%s, %s, %s)",
                (pid, uid, msg),
            )
            log_activity(pid, uid, "commented", "comment", cid)
            flash("Comment added.", "success")
            return redirect(url_for("project", pid=pid))

        return redirect(url_for("project", pid=pid))

    # Owner flag for template
    owner_flag = is_project_owner(pid, uid)

    # User liked?
    liked = fetchone(
        "SELECT 1 AS x FROM stars WHERE user_id=%s AND project_id=%s",
        (uid, pid),
    )
    user_liked = bool(liked)

    like_count = fetchone(
        "SELECT COUNT(*) AS c FROM stars WHERE project_id=%s",
        (pid,),
    )["c"]

    members = fetchall(
        """
        SELECT u.id AS user_id, u.username, pm.role
        FROM project_members pm
        JOIN users u ON u.id=pm.user_id
        WHERE pm.project_id=%s
        ORDER BY FIELD(pm.role,'owner','admin','member'), u.username
        """,
        (pid,),
    )

    files = fetchall(
        """
        SELECT f.id AS file_id, f.filename, f.uploaded_at, u.username AS uploader
        FROM files f
        JOIN users u ON u.id=f.uploaded_by
        WHERE f.project_id=%s
        ORDER BY f.uploaded_at DESC
        """,
        (pid,),
    )

    comments = fetchall(
        """
        SELECT c.id AS comment_id, c.message, c.created_at, u.username
        FROM comments c
        JOIN users u ON u.id=c.user_id
        WHERE c.project_id=%s
        ORDER BY c.created_at DESC
        """,
        (pid,),
    )

    # IMPORTANT: project.html uses tuple indexes:
    # project[0]=id, [1]=title, [2]=description, [5]=owner username
    project_tuple = (
        p["id"], p["title"], p["description"], p["created_at"],
        p["is_private"], p["owner_username"], p["status"]
    )

    # Convert dict rows to tuples for the template (member[0], member[1], member[2]) etc.
    members_t = [(m["user_id"], m["username"], m["role"]) for m in members]
    files_t = [(f["file_id"], f["filename"], f["uploaded_at"], f["uploader"]) for f in files]
    comments_t = [(c["comment_id"], c["message"], c["created_at"], c["username"]) for c in comments]

    return render_template(
        "project.html",
        user=u,
        project=project_tuple,
        is_owner=owner_flag,
        user_liked=user_liked,
        like_count=like_count,
        members=members_t,
        files=files_t,
        comments=comments_t,
    )


@login_required
def add_member(pid: int):
    u = current_user()
    uid = u["id"]

    # owner only
    if not is_project_owner(pid, uid):
        abort(403)

    username = (request.form.get("username") or "").strip()
    role = (request.form.get("role") or "member").strip()
    if role not in ("admin", "member"):
        role = "member"

    target = fetchone(
        "SELECT id FROM users WHERE username_norm=LOWER(TRIM(%s))",
        (username,),
    )
    if not target:
        flash("User not found.", "error")
        return redirect(url_for("project", pid=pid))

    # Prevent adding duplicate
    exists = fetchone(
        "SELECT 1 AS x FROM project_members WHERE project_id=%s AND user_id=%s",
        (pid, target["id"]),
    )
    if exists:
        flash("User already in project.", "error")
        return redirect(url_for("project", pid=pid))

    execute(
        "INSERT INTO project_members (project_id, user_id, role) VALUES (%s, %s, %s)",
        (pid, target["id"], role),
    )
    log_activity(pid, uid, "joined_project", "member", target["id"])
    flash("Member added.", "success")
    return redirect(url_for("project", pid=pid))


@login_required
def remove_member(pid: int, member_id: int):
    u = current_user()
    uid = u["id"]

    if not is_project_owner(pid, uid):
        abort(403)

    role_row = fetchone(
        "SELECT role FROM project_members WHERE project_id=%s AND user_id=%s",
        (pid, member_id),
    )
    if not role_row:
        return redirect(url_for("project", pid=pid))

    if role_row["role"] == "owner":
        flash("You cannot remove the owner.", "error")
        return redirect(url_for("project", pid=pid))

    execute(
        "DELETE FROM project_members WHERE project_id=%s AND user_id=%s",
        (pid, member_id),
    )
    log_activity(pid, uid, "left_project", "member", member_id)
    flash("Member removed.", "success")
    return redirect(url_for("project", pid=pid))


@login_required
def like(pid: int):
    u = current_user()
    uid = u["id"]

    p = fetchone("SELECT is_private FROM projects WHERE id=%s", (pid,))
    if not p:
        abort(404)

    if p["is_private"]:
        require_project_role(pid, "member")

    exists = fetchone(
        "SELECT 1 AS x FROM stars WHERE user_id=%s AND project_id=%s",
        (uid, pid),
    )

    if exists:
        execute("DELETE FROM stars WHERE user_id=%s AND project_id=%s", (uid, pid))
    else:
        execute("INSERT INTO stars (user_id, project_id) VALUES (%s, %s)", (uid, pid))
        log_activity(pid, uid, "starred", "star", None)

    return redirect(url_for("project", pid=pid))


@login_required
def download_file(file_id: int):
    uid = session.get("user_id")

    f = fetchone(
        """
        SELECT f.filepath, f.filename, p.id AS project_id, p.is_private
        FROM files f
        JOIN projects p ON p.id=f.project_id
        WHERE f.id=%s
        """,
        (file_id,),
    )
    if not f:
        abort(404)

    if f["is_private"]:
        require_project_role(f["project_id"], "member")

    abs_path = os.path.join(current_app.root_path, f["filepath"].replace("/", os.sep))
    if not os.path.exists(abs_path):
        abort(404)

    return send_file(abs_path, as_attachment=True, download_name=f["filename"])


@login_required
def delete_file(file_id: int):
    u = current_user()
    uid = u["id"]

    f = fetchone(
        """
        SELECT f.id, f.filepath, f.project_id
        FROM files f
        WHERE f.id=%s
        """,
        (file_id,),
    )
    if not f:
        abort(404)

    # owner only (matches template showing delete only to owner)
    if not is_project_owner(f["project_id"], uid):
        abort(403)

    abs_path = os.path.join(current_app.root_path, f["filepath"].replace("/", os.sep))
    execute("DELETE FROM files WHERE id=%s", (file_id,))
    if os.path.exists(abs_path):
        try:
            os.remove(abs_path)
        except OSError:
            pass

    flash("File deleted.", "success")
    return redirect(url_for("project", pid=f["project_id"]))
