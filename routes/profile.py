from flask import render_template, redirect, url_for, flash, abort

from db import fetchone, fetchall, execute
from utils import login_required, current_user


@login_required
def profile():
    """Current user's profile page."""
    u = current_user()
    uid = u["id"]

    project_count = fetchone(
        "SELECT COUNT(*) AS c FROM projects WHERE owner_id=%s",
        (uid,),
    )["c"]

    comment_count = fetchone(
        "SELECT COUNT(*) AS c FROM comments WHERE user_id=%s",
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
          u2.username AS target
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
def user_profile(user_id: int):
    """Public profile of a user."""
    viewer = current_user()
    viewer_id = viewer["id"]

    target = fetchone(
        "SELECT id, username, email, created_at FROM users WHERE id=%s",
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
