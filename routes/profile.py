from flask import render_template, redirect, url_for, flash, abort
from db import fetchone, fetchall, execute
from utils import login_required, current_user


def _profile_stats(uid: int) -> dict:
    """Return basic profile counters for a given user id."""
    project_count = fetchone(
        """
        SELECT COUNT(*) AS c
        FROM projects
        WHERE owner_id=%s
        """,
        (uid,),
    )["c"]

    comment_count = fetchone(
        "SELECT COUNT(*) AS c FROM comments WHERE user_id=%s",
        (uid,),
    )["c"]

    # NOTE: your schema uses 'stars' for project stars
    like_count = fetchone(
        "SELECT COUNT(*) AS c FROM stars WHERE user_id=%s",
        (uid,),
    )["c"]

    followers_count = fetchone(
        "SELECT COUNT(*) AS c FROM followers WHERE following_id=%s",
        (uid,),
    )["c"]

    following_count = fetchone(
        "SELECT COUNT(*) AS c FROM followers WHERE follower_id=%s",
        (uid,),
    )["c"]

    return {
        "project_count": project_count,
        "comment_count": comment_count,
        "like_count": like_count,
        "followers_count": followers_count,
        "following_count": following_count,
    }


@login_required
def profile():
    """Profile page for the currently logged-in user."""
    u = current_user()
    if not u:
        abort(403)

    stats = _profile_stats(u["id"])

    return render_template(
        "profile.html",
        user=u,
        **stats,
    )


@login_required
def user_profile(user_id: int):
    """Public profile page for a user."""
    viewer = current_user()
    if not viewer:
        abort(403)

    target = fetchone(
        "SELECT id, username, email, created_at FROM users WHERE id=%s",
        (user_id,),
    )
    if not target:
        abort(404)

    # Is viewer following target?
    is_following = False
    if viewer["id"] != target["id"]:
        row = fetchone(
            "SELECT 1 AS ok FROM followers WHERE follower_id=%s AND following_id=%s",
            (viewer["id"], target["id"]),
        )
        is_following = bool(row)

    stats = _profile_stats(target["id"])

    # Projects visible to viewer:
    # - public projects always visible
    # - private projects visible if viewer is owner or a member
    projects = fetchall(
        """
        SELECT
          p.id,
          p.title,
          p.description,
          p.updated_at,
          p.is_private,
          (SELECT COUNT(*) FROM stars s WHERE s.project_id=p.id) AS stars
        FROM projects p
        LEFT JOIN project_members pm
          ON pm.project_id=p.id AND pm.user_id=%s
        WHERE p.owner_id=%s
          AND (p.is_private=0 OR p.owner_id=%s OR pm.user_id IS NOT NULL)
        ORDER BY p.updated_at DESC
        LIMIT 50
        """,
        (viewer["id"], target["id"], viewer["id"]),
    )

    return render_template(
        "user_profile.html",
        user=viewer,
        target=target,
        is_following=is_following,
        projects=projects,
        **stats,
    )


@login_required
def follow_user(user_id: int):
    viewer = current_user()
    if not viewer:
        abort(403)

    follower_id = viewer["id"]
    following_id = user_id

    if follower_id == following_id:
        flash("You cannot follow yourself.", "warning")
        return redirect(url_for("user_profile", user_id=user_id))

    # Prevent duplicates (PRIMARY KEY (follower_id, following_id))
    try:
        execute(
            "INSERT INTO followers (follower_id, following_id) VALUES (%s, %s)",
            (follower_id, following_id),
        )
        flash("Followed.", "success")
    except Exception:
        # If already following (duplicate PK) or other DB constraint error,
        # just treat as no-op for UX.
        flash("Already following.", "info")

    return redirect(url_for("user_profile", user_id=user_id))


@login_required
def unfollow_user(user_id: int):
    viewer = current_user()
    if not viewer:
        abort(403)

    follower_id = viewer["id"]
    following_id = user_id

    execute(
        "DELETE FROM followers WHERE follower_id=%s AND following_id=%s",
        (follower_id, following_id),
    )

    flash("Unfollowed.", "success")
    return redirect(url_for("user_profile", user_id=user_id))
