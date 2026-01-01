from flask import render_template, current_app
from db import fetchall, fetchone
from utils import login_required, current_user


@login_required
def dashboard():
    u = current_user()
    uid = u["id"]

    # Stats
    stats_projects = fetchone(
        "SELECT COUNT(*) AS c FROM project_members WHERE user_id=%s",
        (uid,),
    )["c"]

    stats_stars = fetchone(
        """
        SELECT COUNT(*) AS c
        FROM stars s
        JOIN projects p ON p.id = s.project_id
        WHERE p.owner_id = %s
        """,
        (uid,),
    )["c"]

    stats_followers = fetchone(
        "SELECT COUNT(*) AS c FROM followers WHERE following_id=%s",
        (uid,),
    )["c"]

    # My projects (membership)
    my_projects = fetchall(
        """
        SELECT
          p.id, p.title, p.status, p.created_at,
          (SELECT COUNT(*) FROM stars s WHERE s.project_id=p.id) AS stars,
          (SELECT COUNT(*) FROM project_members pm2 WHERE pm2.project_id=p.id) AS members
        FROM projects p
        JOIN project_members pm ON pm.project_id=p.id
        WHERE pm.user_id=%s
        ORDER BY p.created_at DESC
        LIMIT 20
        """,
        (uid,),
    )

    # Recent activity (last 10)
    activities = fetchall(
        """
        SELECT
          pa.project_id,
          p.title AS project_title,
          COALESCE(u.username, 'System') AS actor,
          u.id AS actor_id,
          pa.action,
          pa.created_at
        FROM project_activity pa
        JOIN projects p ON p.id=pa.project_id
        LEFT JOIN users u ON u.id=pa.user_id
        WHERE
          (p.is_private=0)
          OR EXISTS (
            SELECT 1 FROM project_members pm
            WHERE pm.project_id=p.id AND pm.user_id=%s
          )
        ORDER BY pa.created_at DESC
        LIMIT 10
        """,
        (uid,),
    )

    # Popular projects (top 5 by stars)
    popular_projects = fetchall(
        """
        SELECT
          p.id, p.title,
          (SELECT COUNT(*) FROM stars s WHERE s.project_id=p.id) AS stars,
          (SELECT COUNT(*) FROM project_members pm WHERE pm.project_id=p.id) AS members
        FROM projects p
        WHERE p.is_private=0
        ORDER BY stars DESC, p.created_at DESC
        LIMIT 5
        """
    )

    # Latest comments (top 5)
    latest_comments = fetchall(
        """
        SELECT
          c.project_id,
          p.title AS project_title,
          u.username AS author,
          u.id AS author_id,
          c.message,
          c.created_at
        FROM comments c
        JOIN users u ON u.id=c.user_id
        JOIN projects p ON p.id=c.project_id
        WHERE
          (p.is_private=0)
          OR EXISTS (
            SELECT 1 FROM project_members pm
            WHERE pm.project_id=p.id AND pm.user_id=%s
          )
        ORDER BY c.created_at DESC
        LIMIT 5
        """,
        (uid,),
    )

    return render_template(
        "dashboard.html",
        user=u,  # dict: user.username works
        stats_projects=stats_projects,
        stats_stars=stats_stars,
        stats_followers=stats_followers,
        my_projects=my_projects,
        activities=activities,
        popular_projects=popular_projects,
        latest_comments=latest_comments,
        language_choices=current_app.config.get("PROJECT_LANGUAGE_CHOICES", []),
    )
