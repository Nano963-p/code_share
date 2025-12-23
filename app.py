import os
from flask import Flask, redirect, url_for, render_template, request

from config import Config
from db import close_conn, fetchall
from utils import login_required, current_user

# Route handlers
from routes.auth import login, signup, logout
from routes.dashboard import dashboard
from routes.profile import (
    profile,
    edit_profile,
    user_profile,
    follow_user,
    unfollow_user,
    user_followers,
    user_following,
    user_projects,
    user_stars,
)
from routes.project import (
    project,
    create_project,
    add_member,
    remove_member,
    like,
    project_stargazers,
    download_file,
    delete_file,
)


def create_app():
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static"
    )
    app.config.from_object(Config)

    # Ensure upload directory exists
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    # Close DB connection after request
    app.teardown_appcontext(close_conn)

    # ================= HOME =================
    @app.route("/")
    def home():
        return redirect(url_for("dashboard"))

    # ================= AUTH =================
    app.add_url_rule("/login", "login", login, methods=["GET", "POST"])
    app.add_url_rule("/signup", "signup", signup, methods=["GET", "POST"])
    app.add_url_rule("/logout", "logout", logout)

    # ================= MAIN =================
    app.add_url_rule("/dashboard", "dashboard", dashboard)
    app.add_url_rule("/profile", "profile", profile)
    app.add_url_rule("/profile/edit", "edit_profile", edit_profile, methods=["GET", "POST"])
    app.add_url_rule("/users/<int:user_id>", "user_profile", user_profile)
    app.add_url_rule("/users/<int:user_id>/follow", "follow_user", follow_user, methods=["POST"])
    app.add_url_rule("/users/<int:user_id>/unfollow", "unfollow_user", unfollow_user, methods=["POST"])
    app.add_url_rule("/users/<int:user_id>/followers", "user_followers", user_followers)
    app.add_url_rule("/users/<int:user_id>/following", "user_following", user_following)
    app.add_url_rule("/users/<int:user_id>/projects", "user_projects", user_projects)
    app.add_url_rule("/users/<int:user_id>/stars", "user_stars", user_stars)

    # ================= PROJECTS =================
    app.add_url_rule(
        "/projects/create",
        "create_project",
        create_project,
        methods=["POST"],
    )

    app.add_url_rule(
        "/project/<int:pid>",
        "project",
        project,
        methods=["GET", "POST"],
    )

    app.add_url_rule(
        "/project/<int:pid>/members/add",
        "add_member",
        add_member,
        methods=["POST"],
    )

    app.add_url_rule(
        "/project/<int:pid>/members/<int:member_id>/remove",
        "remove_member",
        remove_member,
        methods=["POST"],
    )

    app.add_url_rule(
        "/project/<int:pid>/like",
        "like",
        like,
        methods=["POST"],
    )

    # Stargazers (who starred a project)
    app.add_url_rule(
        "/project/<int:pid>/stargazers",
        "project_stargazers",
        project_stargazers,
        methods=["GET"],
    )

    # ================= FILES =================
    app.add_url_rule(
        "/files/<int:file_id>/download",
        "download_file",
        download_file,
    )

    app.add_url_rule(
        "/files/<int:file_id>/delete",
        "delete_file",
        delete_file,
        methods=["POST"],
    )

    # ================= SEARCH =================
    @app.route("/search")
    @login_required
    def search():
        user = current_user()
        q = request.args.get("q", "").strip()

        if not q:
            return render_template(
                "search.html",
                user=user,
                query="",
                results=[],
                page=1,
                has_next=False
            )

        results = fetchall(
            """
            SELECT
                p.id,
                p.title,
                p.description,
                u.username AS owner,
                COUNT(s.user_id) AS stars
            FROM projects p
            JOIN users u ON u.id = p.owner_id
            LEFT JOIN stars s ON s.project_id = p.id
            LEFT JOIN project_members pm ON pm.project_id = p.id
            WHERE
                (
                    p.is_private = 0
                    OR pm.user_id = %s
                )
                AND (
                    p.title LIKE %s
                    OR p.description LIKE %s
                    OR u.username LIKE %s
                )
            GROUP BY p.id
            ORDER BY stars DESC, p.created_at DESC
            LIMIT 30
            """,
            (
                user["id"],
                f"%{q}%",
                f"%{q}%",
                f"%{q}%",
            ),
        )

        return render_template(
            "search.html",
            user=user,
            query=q,
            results=results,
        )

    # ================= ERRORS =================
    @app.errorhandler(403)
    def forbidden(_):
        return render_template("403.html"), 403

    @app.errorhandler(404)
    def not_found(_):
        return render_template("404.html"), 404

    @app.errorhandler(500)
    def server_error(_):
        return render_template("500.html"), 500

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True)