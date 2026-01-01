import re
import os

from flask import render_template, redirect, url_for, flash, abort, request, current_app
from werkzeug.utils import secure_filename

from db import fetchone, fetchall, execute
from utils import login_required, current_user, hash_password, verify_password


_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,30}$")
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}


def _profile_upload_dir(user_id: int) -> str:
    folder = os.path.join(current_app.config["UPLOAD_FOLDER"], "avatars", str(user_id))
    os.makedirs(folder, exist_ok=True)
    return folder


def _save_profile_image(user_id: int, file_storage) -> str:
    filename = secure_filename(file_storage.filename or "")
    if not filename:
        raise ValueError("Please select a valid image file.")

    if "." not in filename:
        raise ValueError("Profile photo must have a valid file extension.")

    ext = filename.rsplit(".", 1)[1].lower()
    if ext not in _IMAGE_EXTENSIONS:
        raise ValueError("Profile photo must be a PNG, JPG, GIF, or WEBP image.")

    folder = _profile_upload_dir(user_id)
    dst = os.path.join(folder, filename)

    if os.path.exists(dst):
        name, extension = os.path.splitext(filename)
        i = 2
        while True:
            candidate = f"{name}_{i}{extension}"
            dst = os.path.join(folder, candidate)
            if not os.path.exists(dst):
                filename = candidate
                break
            i += 1

    file_storage.save(dst)
    return os.path.relpath(dst, current_app.config["UPLOAD_FOLDER"]).replace("\\", "/")


def _remove_profile_image(path: str | None) -> None:
    if not path:
        return
    abs_path = os.path.join(current_app.config["UPLOAD_FOLDER"], path.replace("/", os.sep))
    if os.path.exists(abs_path):
        try:
            os.remove(abs_path)
        except OSError:
            pass


@login_required
def profile():
    """Current user's profile page."""
    u = current_user()
    uid = u["id"]

    project_count = fetchone(
        "SELECT COUNT(*) AS c FROM projects WHERE owner_id=%s",
        (uid,),
    )["c"]

    # Comments authored by the user.
    # This must match what the UI label says ("Comments").
    # Use COUNT(id) so the intent is explicit, and COALESCE to avoid None.
    comment_count = fetchone(
        "SELECT COALESCE(COUNT(c.id), 0) AS c FROM comments c WHERE c.user_id=%s",
        (uid,),
    )["c"]

    like_count = fetchone(
        "SELECT COUNT(*) AS c FROM stars WHERE user_id=%s",
        (uid,),
    )["c"]

    # Recent user activity (follow/unfollow)
    activities = fetchall(
        """
        SELECT
          ua.action,
          ua.created_at,
          u1.username AS actor,
          u1.id AS actor_id,
          u2.username AS target,
          u2.id AS target_id
        FROM user_activity ua
        JOIN users u1 ON u1.id = ua.user_id
        JOIN users u2 ON u2.id = ua.target_user_id
        WHERE ua.user_id = %s
        ORDER BY ua.created_at DESC
        LIMIT 15
        """,
        (uid,),
    )

    return render_template(
        "profile.html",
        user=u,
        project_count=project_count,
        comment_count=comment_count,
        like_count=like_count,
        activities=activities,
    )


@login_required
def edit_profile():
    """Edit current user's account details (username, email, password)."""
    u = current_user()
    uid = u["id"]

    if request.method == "GET":
        return render_template("edit_profile.html", user=u)

    # --- Read inputs ---
    new_username = (request.form.get("username") or "").strip()
    new_email = (request.form.get("email") or "").strip()
    current_pw = request.form.get("current_password") or ""
    new_pw = request.form.get("new_password") or ""
    confirm_pw = request.form.get("confirm_password") or ""
    remove_photo = request.form.get("remove_profile_image") == "1"
    uploaded_photo = request.files.get("profile_image")

    # --- Basic validation ---
    if not _USERNAME_RE.match(new_username):
        flash("Username must be 3–30 characters and contain only letters, numbers, or underscore.", "error")
        return redirect(url_for("edit_profile"))

    if not _EMAIL_RE.match(new_email):
        flash("Please enter a valid email address.", "error")
        return redirect(url_for("edit_profile"))

    # Username/email uniqueness (exclude self)
    exists = fetchone(
        """
        SELECT id
        FROM users
        WHERE (username_norm = LOWER(TRIM(%s)) OR email_norm = LOWER(TRIM(%s)))
          AND id <> %s
        """,
        (new_username, new_email, uid),
    )
    if exists:
        flash("Username or email already in use.", "error")
        return redirect(url_for("edit_profile"))

    # Password change is optional; if requested, verify current password.
    password_hash = None
    if new_pw or confirm_pw:
        if not new_pw or not confirm_pw:
            flash("Please fill both new password fields.", "error")
            return redirect(url_for("edit_profile"))
        if new_pw != confirm_pw:
            flash("New passwords do not match.", "error")
            return redirect(url_for("edit_profile"))

        row = fetchone("SELECT password_hash FROM users WHERE id=%s", (uid,))
        if not row or not verify_password(current_pw, row["password_hash"]):
            flash("Current password is incorrect.", "error")
            return redirect(url_for("edit_profile"))

        if len(new_pw) < 6:
            flash("New password must be at least 6 characters.", "error")
            return redirect(url_for("edit_profile"))

        password_hash = hash_password(new_pw)

    # --- Persist ---
    new_profile_image = None
    if uploaded_photo and uploaded_photo.filename:
        try:
            new_profile_image = _save_profile_image(uid, uploaded_photo)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("edit_profile"))

    updates = ["username=%s", "email=%s"]
    params = [new_username, new_email]

    if password_hash:
        updates.append("password_hash=%s")
        params.append(password_hash)

    if new_profile_image is not None:
        updates.append("profile_image=%s")
        params.append(new_profile_image)
        _remove_profile_image(u.get("profile_image"))
    elif remove_photo and u.get("profile_image"):
        updates.append("profile_image=%s")
        params.append(None)
        _remove_profile_image(u.get("profile_image"))

    params.append(uid)
    execute(
        f"UPDATE users SET {', '.join(updates)} WHERE id=%s",
        params,
    )

    flash("Profile updated.", "success")
    return redirect(url_for("profile"))


@login_required
def user_profile(user_id: int):
    """Public profile of a user."""
    viewer = current_user()
    viewer_id = viewer["id"]

    target = fetchone(
        "SELECT id, username, email, created_at, profile_image FROM users WHERE id=%s",
        (user_id,),
    )
    if not target:
        abort(404)

    followers_count = fetchone(
        "SELECT COUNT(*) AS c FROM followers WHERE following_id=%s",
        (user_id,),
    )["c"]

    following_count = fetchone(
        "SELECT COUNT(*) AS c FROM followers WHERE follower_id=%s",
        (user_id,),
    )["c"]

    is_following = bool(
        fetchone(
            "SELECT 1 AS x FROM followers WHERE follower_id=%s AND following_id=%s",
            (viewer_id, user_id),
        )
    )

    # Projects visible to viewer:
    # - public projects always visible
    # - private projects visible if viewer is owner or is a project member
    projects = fetchall(
        """
        SELECT
          p.id,
          p.title,
          p.description,
          p.created_at,
          p.updated_at,
          p.is_private,
          (SELECT COUNT(*) FROM stars s WHERE s.project_id=p.id) AS stars
        FROM projects p
        LEFT JOIN project_members pm
          ON pm.project_id = p.id AND pm.user_id = %s
        WHERE p.owner_id = %s
          AND (
            p.is_private = 0
            OR p.owner_id = %s
            OR pm.user_id IS NOT NULL
          )
        ORDER BY p.updated_at DESC
        LIMIT 50
        """,
        (viewer_id, user_id, viewer_id),
    )

    return render_template(
        "user_profile.html",
        user=viewer,
        target=target,
        followers_count=followers_count,
        following_count=following_count,
        is_following=is_following,
        projects=projects,
    )


@login_required
def follow_user(user_id: int):
    viewer = current_user()
    follower_id = viewer["id"]

    if follower_id == user_id:
        flash("You cannot follow yourself.", "error")
        return redirect(url_for("user_profile", user_id=user_id))

    # Ensure target exists
    target = fetchone("SELECT id FROM users WHERE id=%s", (user_id,))
    if not target:
        abort(404)

    # Avoid duplicate activity spam
    already = fetchone(
        "SELECT 1 AS x FROM followers WHERE follower_id=%s AND following_id=%s",
        (follower_id, user_id),
    )
    if not already:
        execute(
            """
            INSERT INTO followers (follower_id, following_id)
            VALUES (%s, %s)
            """,
            (follower_id, user_id),
        )
        execute(
            """
            INSERT INTO user_activity (user_id, action, target_user_id)
            VALUES (%s, 'followed', %s)
            """,
            (follower_id, user_id),
        )
        flash("Followed.", "success")
    else:
        flash("You already follow this user.", "info")

    return redirect(url_for("user_profile", user_id=user_id))


@login_required
def unfollow_user(user_id: int):
    viewer = current_user()
    follower_id = viewer["id"]

    existed = fetchone(
        "SELECT 1 AS x FROM followers WHERE follower_id=%s AND following_id=%s",
        (follower_id, user_id),
    )

    execute(
        "DELETE FROM followers WHERE follower_id=%s AND following_id=%s",
        (follower_id, user_id),
    )

    if existed:
        execute(
            """
            INSERT INTO user_activity (user_id, action, target_user_id)
            VALUES (%s, 'unfollowed', %s)
            """,
            (follower_id, user_id),
        )
        flash("Unfollowed.", "success")
    else:
        flash("You are not following this user.", "info")

    return redirect(url_for("user_profile", user_id=user_id))


@login_required
def user_followers(user_id: int):
    """List users who follow `user_id`."""
    viewer = current_user()
    viewer_id = viewer["id"]

    target = fetchone(
        "SELECT id, username, created_at FROM users WHERE id=%s",
        (user_id,),
    )
    if not target:
        abort(404)

    followers = fetchall(
        """
        SELECT
          u.id,
          u.username,
          u.created_at,
          f.created_at AS since,
          CASE WHEN mf.follower_id IS NULL THEN 0 ELSE 1 END AS i_follow
        FROM followers f
        JOIN users u ON u.id = f.follower_id
        LEFT JOIN followers mf
          ON mf.follower_id = %s AND mf.following_id = u.id
        WHERE f.following_id = %s
        ORDER BY f.created_at DESC
        """,
        (viewer_id, user_id),
    )

    return render_template(
        "followers_list.html",
        user=viewer,
        target=target,
        mode="followers",
        people=followers,
    )


@login_required
def user_following(user_id: int):
    """List users that `user_id` follows."""
    viewer = current_user()
    viewer_id = viewer["id"]

    target = fetchone(
        "SELECT id, username, created_at FROM users WHERE id=%s",
        (user_id,),
    )
    if not target:
        abort(404)

    following = fetchall(
        """
        SELECT
          u.id,
          u.username,
          u.created_at,
          f.created_at AS since,
          CASE WHEN mf.follower_id IS NULL THEN 0 ELSE 1 END AS i_follow
        FROM followers f
        JOIN users u ON u.id = f.following_id
        LEFT JOIN followers mf
          ON mf.follower_id = %s AND mf.following_id = u.id
        WHERE f.follower_id = %s
        ORDER BY f.created_at DESC
        """,
        (viewer_id, user_id),
    )

    return render_template(
        "followers_list.html",
        user=viewer,
        target=target,
        mode="following",
        people=following,
    )


@login_required
def user_projects(user_id: int):
    """List projects for a user (respecting visibility rules)."""
    viewer = current_user()
    viewer_id = viewer["id"]

    target = fetchone(
        "SELECT id, username, created_at FROM users WHERE id=%s",
        (user_id,),
    )
    if not target:
        abort(404)

    projects = fetchall(
        """
        SELECT
          p.id,
          p.title,
          p.description,
          p.created_at,
          p.updated_at,
          p.is_private,
          p.status,
          (SELECT COUNT(*) FROM stars s WHERE s.project_id=p.id) AS stars
        FROM projects p
        LEFT JOIN project_members pm
          ON pm.project_id = p.id AND pm.user_id = %s
        WHERE p.owner_id = %s
          AND (
            p.is_private = 0
            OR p.owner_id = %s
            OR pm.user_id IS NOT NULL
          )
        ORDER BY p.updated_at DESC
        LIMIT 100
        """,
        (viewer_id, user_id, viewer_id),
    )

    return render_template(
        "user_projects.html",
        user=viewer,
        target=target,
        projects=projects,
    )


@login_required
def user_stars(user_id: int):
    """List projects (owned by user) that received stars, respecting visibility."""
    viewer = current_user()
    viewer_id = viewer["id"]

    target = fetchone(
        "SELECT id, username, created_at FROM users WHERE id=%s",
        (user_id,),
    )
    if not target:
        abort(404)

    projects = fetchall(
        """
        SELECT
          p.id,
          p.title,
          p.description,
          p.created_at,
          p.updated_at,
          p.is_private,
          p.status,
          COUNT(s.user_id) AS star_count
        FROM projects p
        JOIN stars s ON s.project_id = p.id
        JOIN users su ON su.id = s.user_id
        LEFT JOIN project_members pm
          ON pm.project_id = p.id AND pm.user_id = %s
        WHERE p.owner_id = %s
          AND (
            p.is_private = 0
            OR p.owner_id = %s
            OR pm.user_id IS NOT NULL
          )
        GROUP BY p.id
        ORDER BY star_count DESC, p.updated_at DESC
        LIMIT 100
        """,
        (viewer_id, user_id, viewer_id),
    )

    return render_template(
        "user_stars.html",
        user=viewer,
        target=target,
        projects=projects,
    )
