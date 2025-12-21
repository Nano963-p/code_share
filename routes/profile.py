from flask import render_template
from db import fetchone
from utils import login_required, current_user


@login_required
def profile():
    u = current_user()
    uid = u["id"]

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

    like_count = fetchone(
        "SELECT COUNT(*) AS c FROM stars WHERE user_id=%s",
        (uid,),
    )["c"]

    return render_template(
        "profile.html",
        user=u,
        project_count=project_count,
        comment_count=comment_count,
        like_count=like_count,
    )
