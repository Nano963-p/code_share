import os
from flask import (
    render_template, request, redirect, url_for, flash, abort,
    send_file, session, current_app
)

from db import fetchone, fetchall, execute
from utils import (
    login_required, require_project_role, current_user,
    is_project_owner, save_upload, log_activity
,
    get_project_role
)

import shutil

import re

# -----------------------
# Tags helpers
# -----------------------
TAG_RE = re.compile(r"^[a-zA-Z0-9_\-]{1,50}$")

def parse_tags_input(raw: str):
    """Parse a user input string into a de-duplicated list of tag names.
    Accepts comma/space separated tags and optional leading '#'.
    """
    if not raw:
        return []
    # Normalize separators to spaces, then split
    cleaned = raw.replace(",", " ").replace(";", " ").replace("\n", " ").replace("\t", " ")
    parts = [p.strip() for p in cleaned.split(" ") if p.strip()]
    out = []
    seen = set()
    for p in parts:
        if p.startswith("#"):
            p = p[1:]
        if not p:
            continue
        if len(p) > 50:
            continue
        if not TAG_RE.match(p):
            continue
        key = p.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out

def upsert_tag(name: str) -> int:
    """Insert a tag if needed and return its id."""
    # MySQL trick: return existing id via LAST_INSERT_ID
    tag_id = execute(
        """
        INSERT INTO tags (name)
        VALUES (%s)
        ON DUPLICATE KEY UPDATE id = LAST_INSERT_ID(id), name = VALUES(name)
        """,
        (name,),
    )
    return tag_id


@login_required
def create_project():
    u = current_user()
    uid = u["id"]

    title = (request.form.get("title") or "").strip()
    description = (request.form.get("description") or "").strip()

    # Multi-language support (select multiple + optional custom comma-separated)
    languages = [
        (x or "").strip()
        for x in request.form.getlist("languages")
        if (x or "").strip()
    ]
    custom_langs_raw = (request.form.get("custom_languages") or "").strip()
    if custom_langs_raw:
        # Accept comma-separated custom entries
        for part in custom_langs_raw.split(","):
            part = (part or "").strip()
            if part:
                languages.append(part)

    # Deduplicate (case/space insensitive), keep first occurrence
    seen = set()
    languages_clean = []
    for lang in languages:
        key = lang.strip().lower()
        if key and key not in seen:
            seen.add(key)
            languages_clean.append(lang.strip())

    # HTML checkbox usually submits "on" (or nothing if unchecked)
    is_private = 1 if (request.form.get("is_private") or "").lower() in {"1", "on", "true", "yes"} else 0

    if not languages_clean:
        flash("Please select at least one programming language (or type custom languages).", "error")
        return redirect(url_for("dashboard"))

    if len(title) < 3:
        flash("Title must be at least 3 characters.", "error")
        return redirect(url_for("dashboard"))

    # Backward-compatible: store the first language in projects.language
    primary_language = languages_clean[0] if languages_clean else None

    pid = execute(
        """
        INSERT INTO projects (owner_id, title, description, language, is_private)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (uid, title, description or None, primary_language, is_private),
    )

    # Persist languages (multi-language)
    for lang in languages_clean:
        try:
            execute(
                "INSERT IGNORE INTO project_languages (project_id, language) VALUES (%s, %s)",
                (pid, lang),
            )
        except Exception:
            # If a language fails validation (rare), skip it to avoid blocking project creation
            pass

    log_activity(pid, uid, "created_project", "project", pid)
    return redirect(url_for("project", pid=pid))


@login_required
def edit_project(pid: int):
    """Edit basic project metadata + multi-language selection.
    Allowed roles: owner, admin.
    """
    u = current_user()
    uid = u["id"]

    role = get_project_role(pid, uid)
    if role not in ("owner", "admin"):
        abort(403)

    p = fetchone(
        """
        SELECT id, owner_id, title, description, is_private, status
        FROM projects
        WHERE id=%s
        """,
        (pid,),
    )
    if not p:
        abort(404)

    current_lang_rows = fetchall(
        """
        SELECT language
        FROM project_languages
        WHERE project_id=%s
        ORDER BY language_norm
        """,
        (pid,),
    )
    current_languages = [r["language"] for r in current_lang_rows]

    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        description = (request.form.get("description") or "").strip()
        status = (request.form.get("status") or "active").strip().lower()
        if status not in ("active", "archived"):
            status = "active"

        languages = [
            (x or "").strip()
            for x in request.form.getlist("languages")
            if (x or "").strip()
        ]
        custom_langs_raw = (request.form.get("custom_languages") or "").strip()
        if custom_langs_raw:
            for part in custom_langs_raw.split(","):
                part = (part or "").strip()
                if part:
                    languages.append(part)

        # Deduplicate (case/space insensitive)
        seen = set()
        languages_clean = []
        for lang in languages:
            key = lang.strip().lower()
            if key and key not in seen:
                seen.add(key)
                languages_clean.append(lang.strip())

        is_private = 1 if (request.form.get("is_private") or "").lower() in {"1", "on", "true", "yes"} else 0

        if len(title) < 3:
            flash("Title must be at least 3 characters.", "error")
            return redirect(url_for("edit_project", pid=pid))

        if not languages_clean:
            flash("Please select at least one programming language (or type custom languages).", "error")
            return redirect(url_for("edit_project", pid=pid))

        primary_language = languages_clean[0]

        execute(
            """
            UPDATE projects
            SET title=%s, description=%s, language=%s, is_private=%s, status=%s
            WHERE id=%s
            """,
            (title, description or None, primary_language, is_private, status, pid),
        )

        # Replace language list
        execute("DELETE FROM project_languages WHERE project_id=%s", (pid,))
        for lang in languages_clean:
            try:
                execute(
                    "INSERT IGNORE INTO project_languages (project_id, language) VALUES (%s, %s)",
                    (pid, lang),
                )
            except Exception:
                continue

        log_activity(pid, uid, "updated_project", "project", pid)
        flash("Project updated.", "success")
        return redirect(url_for("project", pid=pid))

    return render_template(
        "edit_project.html",
        user=u,
        project=p,
        current_languages=current_languages,
        language_choices=current_app.config.get("PROJECT_LANGUAGE_CHOICES", []),
    )


@login_required
def project(pid: int):
    u = current_user()
    uid = u["id"]

    # Project info
    p = fetchone(
        """
        SELECT
          p.id, p.title, p.description, p.created_at, p.is_private,
          p.owner_id AS owner_id,
          o.username AS owner_username, p.status, p.owner_id
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
    project_owner_id = p["owner_id"]

    owner_followers = fetchone(
        "SELECT COUNT(*) AS c FROM followers WHERE following_id=%s",
        (project_owner_id,),
    )["c"]

    is_following_owner = bool(
        fetchone(
            "SELECT 1 AS x FROM followers WHERE follower_id=%s AND following_id=%s",
            (uid, project_owner_id),
        )
    )
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
        SELECT f.id AS file_id, f.filename, f.uploaded_at, u.username AS uploader, u.id AS uploader_id
        FROM files f
        JOIN users u ON u.id=f.uploaded_by
        WHERE f.project_id=%s
        ORDER BY f.uploaded_at DESC
        """,
        (pid,),
    )

    comments = fetchall(
        """
        SELECT c.id AS comment_id, c.message, c.created_at, u.username, u.id AS user_id
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
    files_t = [(f["file_id"], f["filename"], f["uploaded_at"], f["uploader"], f["uploader_id"]) for f in files]
    comments_t = [(c["comment_id"], c["message"], c["created_at"], c["username"], c["user_id"]) for c in comments]

    languages = fetchall(
        """
        SELECT language
        FROM project_languages
        WHERE project_id=%s
        ORDER BY language_norm
        """,
        (pid,),
    )
    languages_list = [r["language"] for r in languages]


    tags = fetchall(
        """
        SELECT t.id, t.name
        FROM project_tags pt
        JOIN tags t ON t.id = pt.tag_id
        WHERE pt.project_id=%s
        ORDER BY t.name_norm
        """,
        (pid,),
    )
    tags_list = [(t["id"], t["name"]) for t in tags]


    role = get_project_role(pid, uid)
    can_edit_tags = role in ("owner", "admin")
    can_edit_project = role in ("owner", "admin")

    return render_template(
        "project.html",
        user=u,
        owner_id=p["owner_id"],
        project=project_tuple,
        is_owner=owner_flag,
        user_liked=user_liked,
        like_count=like_count,
        members=members_t,
        files=files_t,
        comments=comments_t,
        project_owner_id=project_owner_id,
        owner_followers=owner_followers,
        is_following_owner=is_following_owner,
        project_languages=languages_list,
        tags=tags_list,
        can_edit_tags=can_edit_tags,
        can_edit_project=can_edit_project,
    )



@login_required
def add_project_tags(pid: int):
    u = current_user()
    uid = u["id"]

    role = get_project_role(pid, uid)
    if role not in ("owner", "admin"):
        abort(403)

    # Choice-based tags: select existing tags (tag_ids) and/or create new tags (new_tag).
    tag_ids_raw = request.form.getlist("tag_ids")  # from <select multiple>
    new_tag_raw = (request.form.get("new_tag") or "").strip()

    # Backward compatibility (older UI): free text field named "tags"
    raw = (request.form.get("tags") or "").strip()

    names = []
    if new_tag_raw:
        names.extend(parse_tags_input(new_tag_raw))
    if raw:
        names.extend(parse_tags_input(raw))

    tag_ids = []
    for x in tag_ids_raw:
        try:
            tag_ids.append(int(x))
        except Exception:
            continue

    if not names and not tag_ids:
        flash("Please select at least one tag, or create a new tag.", "error")
        return redirect(url_for("project", pid=pid))

    added = 0

    # Add selected existing tag ids (validate existence)
    if tag_ids:
        rows = fetchall(
            "SELECT id FROM tags WHERE id IN (" + ",".join(["%s"] * len(tag_ids)) + ")",
            tuple(tag_ids),
        )
        valid_ids = [r["id"] for r in rows]
        for tid in valid_ids:
            try:
                execute(
                    "INSERT IGNORE INTO project_tags (project_id, tag_id) VALUES (%s, %s)",
                    (pid, tid),
                )
                added += 1
            except Exception:
                continue

    # Create (if needed) and add new tag names
    for name in names:
        try:
            tag_id = upsert_tag(name)
            execute(
                "INSERT IGNORE INTO project_tags (project_id, tag_id) VALUES (%s, %s)",
                (pid, tag_id),
            )
            added += 1
        except Exception:
            continue

    if added:
        flash(f"Tags updated (+{added}).", "success")
    else:
        flash("No tags were added (they may already exist).", "info")

    return redirect(url_for("project", pid=pid))


    added = 0
    for name in tags:
        try:
            tag_id = upsert_tag(name)
            execute(
                "INSERT IGNORE INTO project_tags (project_id, tag_id) VALUES (%s, %s)",
                (pid, tag_id),
            )
            added += 1
        except Exception:
            # Ignore unexpected duplicates/edge cases; user gets partial success
            continue

    if added:
        flash(f"Tags updated (+{added}).", "success")
    else:
        flash("No tags were added (they may already exist).", "info")

    return redirect(url_for("project", pid=pid))


@login_required
def remove_project_tag(pid: int, tag_id: int):
    u = current_user()
    uid = u["id"]

    role = get_project_role(pid, uid)
    if role not in ("owner", "admin"):
        abort(403)

    execute(
        "DELETE FROM project_tags WHERE project_id=%s AND tag_id=%s",
        (pid, tag_id),
    )
    flash("Tag removed.", "success")
    return redirect(url_for("project", pid=pid))


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


@login_required
def delete_project(pid: int):
    """Delete an entire project (owner only).

    We rely on FK ON DELETE CASCADE to remove dependent rows (files, members, comments,
    stars, tags, activities, languages). We also remove the uploads/<pid> directory on disk.
    """
    u = current_user()
    uid = u["id"]

    # Ensure project exists and obtain owner_id for authorization
    p = fetchone("SELECT id, owner_id FROM projects WHERE id=%s", (pid,))
    if not p:
        abort(404)

    if p["owner_id"] != uid:
        abort(403)

    # Remove uploaded files on disk (if any)
    upload_dir = os.path.join(current_app.config["UPLOAD_FOLDER"], str(pid))
    if os.path.isdir(upload_dir):
        try:
            shutil.rmtree(upload_dir)
        except OSError:
            # Non-fatal; DB deletion still proceeds
            pass

    # Delete project (cascades to dependent rows)
    execute("DELETE FROM projects WHERE id=%s", (pid,))
    flash("Project deleted.", "success")
    return redirect(url_for("dashboard"))

@login_required
def project_stargazers(pid: int):
    """List users who starred a project (only if viewer can access project)."""
    viewer = current_user()
    viewer_id = viewer["id"]

    project = fetchone(
        """
        SELECT
          p.id, p.title, p.is_private,
          (SELECT COUNT(*) FROM stars s WHERE s.project_id=p.id) AS stars
        FROM projects p
        LEFT JOIN project_members pm
          ON pm.project_id = p.id AND pm.user_id = %s
        WHERE p.id = %s
          AND (p.is_private = 0 OR pm.user_id IS NOT NULL)
        """,
        (viewer_id, pid),
    )
    if not project:
        abort(404)

    users = fetchall(
        """
        SELECT u.id, u.username, s.created_at
        FROM stars s
        JOIN users u ON u.id = s.user_id
        WHERE s.project_id = %s
        ORDER BY s.created_at DESC
        """,
        (pid,),
    )

    return render_template(
        "project_stargazers.html",
        user=viewer,
        project=project,
        users=users,
    )
