from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import mysql.connector
from mysql.connector import Error
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "REDACTED"

DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "REDACTED",          # <-- put your mysql password
    "database": "codeshare",
    "charset": "utf8mb4",
    "collation": "utf8mb4_unicode_ci",
}

# -------------------------
# DB helpers
# -------------------------
def get_conn():
    return mysql.connector.connect(**DB_CONFIG)

def q_all(sql, params=None):
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute(sql, params or ())
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

def q_one(sql, params=None):
    conn = get_conn()
    cur = conn.cursor(dictionary=True)
    cur.execute(sql, params or ())
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row

def exec_sql(sql, params=None):
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(sql, params or ())
        conn.commit()
        last_id = cur.lastrowid
        cur.close()
        conn.close()
        return last_id, None
    except Error as e:
        conn.rollback()
        cur.close()
        conn.close()
        return None, str(e)

def exec_many(sql, params_seq):
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.executemany(sql, params_seq)
        conn.commit()
        cur.close()
        conn.close()
        return None
    except Error as e:
        conn.rollback()
        cur.close()
        conn.close()
        return str(e)

def log_activity(actor_id, project_id, action, entity_type, entity_id=None, details_json=None):
    exec_sql(
        """
        INSERT INTO activity_log(actor_id, project_id, action, entity_type, entity_id, details)
        VALUES (%s,%s,%s,%s,%s,%s)
        """,
        (actor_id, project_id, action, entity_type, entity_id, details_json),
    )

# -------------------------
# Auth helpers
# -------------------------
def me():
    uid = session.get("user_id")
    if not uid:
        return None
    return q_one("SELECT id, username, email, bio, followers_count, following_count FROM users WHERE id=%s", (uid,))

def login_required():
    if not session.get("user_id"):
        flash("Please login first.", "warn")
        return False
    return True

@app.context_processor
def inject_globals():
    return {"me": me(), "path": request.path}

# -------------------------
# Routes
# -------------------------
@app.route("/")
def index():
    return redirect(url_for("dashboard" if session.get("user_id") else "login"))

# ---- AUTH ----
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not username or not email or not password:
            flash("All fields are required.", "danger")
            return redirect(url_for("register"))

        pw_hash = generate_password_hash(password)

        new_id, err = exec_sql(
            "INSERT INTO users(username, email, password_hash, bio) VALUES (%s,%s,%s,%s)",
            (username, email, pw_hash, "Hello, I'm new on CodeShare."),
        )
        if err:
            flash(f"Register failed: {err}", "danger")
            return redirect(url_for("register"))

        session["user_id"] = new_id
        flash("Account created. Welcome!", "success")
        log_activity(new_id, None, "REGISTER", "USER", new_id, None)
        return redirect(url_for("dashboard"))

    return render_template("auth_register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        user = q_one("SELECT id, password_hash, is_active FROM users WHERE email=%s", (email,))
        if not user or not user["is_active"]:
            flash("Invalid credentials.", "danger")
            return redirect(url_for("login"))

        if not check_password_hash(user["password_hash"], password):
            flash("Invalid credentials.", "danger")
            return redirect(url_for("login"))

        session["user_id"] = user["id"]
        flash("Welcome back!", "success")
        log_activity(user["id"], None, "LOGIN", "USER", user["id"], None)
        return redirect(url_for("dashboard"))

    return render_template("auth_login.html")

@app.route("/logout")
def logout():
    uid = session.get("user_id")
    session.clear()
    if uid:
        log_activity(uid, None, "LOGOUT", "USER", uid, None)
    flash("Logged out.", "info")
    return redirect(url_for("login"))

# ---- DASHBOARD ----
@app.route("/dashboard")
def dashboard():
    if not login_required():
        return redirect(url_for("login"))

    uid = session["user_id"]

    # My summary cards
    my_projects_count = q_one(
        "SELECT COUNT(*) AS c FROM projects WHERE owner_id=%s",
        (uid,),
    )["c"]

    stars_received = q_one(
        """
        SELECT COALESCE(SUM(p.stars_count),0) AS s
        FROM projects p
        WHERE p.owner_id=%s
        """,
        (uid,),
    )["s"]

    followers_count = q_one("SELECT followers_count AS f FROM users WHERE id=%s", (uid,))["f"]

    # My projects list (owner view)
    my_projects = q_all(
        """
        SELECT id, name, description, stars_count, members_count, status, updated_at
        FROM projects
        WHERE owner_id=%s
        ORDER BY updated_at DESC
        LIMIT 10
        """,
        (uid,),
    )

    # Recent activity (actor = me)
    recent_activity = q_all(
        """
        SELECT al.created_at, al.action, al.entity_type, al.entity_id, al.project_id,
               p.name AS project_name
        FROM activity_log al
        LEFT JOIN projects p ON p.id = al.project_id
        WHERE al.actor_id=%s
        ORDER BY al.created_at DESC
        LIMIT 8
        """,
        (uid,),
    )

    # Popular public projects
    popular = q_all(
        """
        SELECT p.id, p.name, p.stars_count, p.members_count,
               u.username AS owner_username
        FROM projects p
        JOIN users u ON u.id = p.owner_id
        WHERE p.visibility='PUBLIC'
        ORDER BY p.stars_count DESC, p.views_count DESC
        LIMIT 3
        """
    )

    # Latest comments (global)
    latest_comments = q_all(
        """
        SELECT ic.created_at, ic.body,
               u.username,
               i.id AS issue_id, i.title AS issue_title,
               p.id AS project_id, p.name AS project_name
        FROM issue_comments ic
        JOIN users u ON u.id = ic.author_id
        JOIN issues i ON i.id = ic.issue_id
        JOIN projects p ON p.id = i.project_id
        ORDER BY ic.created_at DESC
        LIMIT 3
        """
    )

    return render_template(
        "dashboard.html",
        my_projects_count=my_projects_count,
        stars_received=stars_received,
        followers_count=followers_count,
        my_projects=my_projects,
        recent_activity=recent_activity,
        popular=popular,
        latest_comments=latest_comments,
    )

# ---- EXPLORE ----
@app.route("/explore")
def explore():
    if not login_required():
        return redirect(url_for("login"))

    q = request.args.get("q", "").strip()
    lang = request.args.get("lang", "").strip()

    sql = """
        SELECT p.id, p.name, p.description, p.language, p.stars_count, p.members_count, p.views_count,
               u.username AS owner_username
        FROM projects p
        JOIN users u ON u.id = p.owner_id
        WHERE p.visibility='PUBLIC'
    """
    params = []
    if q:
        sql += " AND (p.name LIKE %s OR p.description LIKE %s OR u.username LIKE %s)"
        like = f"%{q}%"
        params.extend([like, like, like])
    if lang:
        sql += " AND p.language = %s"
        params.append(lang)

    sql += " ORDER BY p.stars_count DESC, p.views_count DESC LIMIT 30"

    projects = q_all(sql, tuple(params))
    languages = q_all(
        "SELECT DISTINCT language FROM projects WHERE language IS NOT NULL AND language<>'' ORDER BY language"
    )

    return render_template("explore.html", projects=projects, q=q, lang=lang, languages=languages)

# ---- MY PROJECTS ----
@app.route("/my-projects")
def my_projects():
    if not login_required():
        return redirect(url_for("login"))

    uid = session["user_id"]
    projects = q_all(
        """
        SELECT p.*, (p.owner_id=%s) AS is_owner
        FROM projects p
        WHERE p.owner_id=%s
        ORDER BY p.updated_at DESC
        """,
        (uid, uid),
    )
    return render_template("my_projects.html", projects=projects)

# ---- CREATE PROJECT ----
@app.route("/projects/new", methods=["GET", "POST"])
def project_new():
    if not login_required():
        return redirect(url_for("login"))

    if request.method == "POST":
        uid = session["user_id"]
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        language = request.form.get("language", "").strip() or None
        license_name = request.form.get("license", "").strip() or None
        visibility = request.form.get("visibility", "PUBLIC").strip().upper()

        if visibility not in ("PUBLIC", "PRIVATE"):
            visibility = "PUBLIC"

        if not name:
            flash("Project name is required.", "danger")
            return redirect(url_for("project_new"))

        pid, err = exec_sql(
            """
            INSERT INTO projects(owner_id, name, description, language, license, visibility)
            VALUES (%s,%s,%s,%s,%s,%s)
            """,
            (uid, name, description, language, license_name, visibility),
        )
        if err:
            flash(f"Create project failed: {err}", "danger")
            return redirect(url_for("project_new"))

        # Owner membership + log is handled by triggers
        flash("Project created.", "success")
        return redirect(url_for("project_view", project_id=pid))

    return render_template("project_new.html")

# ---- VIEW PROJECT ----
@app.route("/projects/<int:project_id>")
def project_view(project_id):
    if not login_required():
        return redirect(url_for("login"))

    uid = session["user_id"]

    project = q_one(
        """
        SELECT p.*, u.username AS owner_username
        FROM projects p
        JOIN users u ON u.id = p.owner_id
        WHERE p.id=%s
        """,
        (project_id,),
    )
    if not project:
        flash("Project not found.", "danger")
        return redirect(url_for("dashboard"))

    # visibility control: if private, only owner or member can view
    is_member = q_one(
        "SELECT 1 AS ok FROM project_members WHERE project_id=%s AND user_id=%s",
        (project_id, uid),
    )
    if project["visibility"] == "PRIVATE" and (not is_member) and project["owner_id"] != uid:
        flash("This project is private.", "warn")
        return redirect(url_for("dashboard"))

    # register a view (counter handled by trigger)
    exec_sql("INSERT INTO views(project_id, viewer_id) VALUES (%s,%s)", (project_id, uid))

    # starred by me?
    starred = q_one(
        "SELECT 1 AS ok FROM stars WHERE project_id=%s AND user_id=%s",
        (project_id, uid),
    )
    is_starred = bool(starred)

    # owner follow status (follow owner)
    if project["owner_id"] == uid:
        is_following_owner = False
    else:
        is_following_owner = bool(
            q_one(
                "SELECT 1 AS ok FROM followers WHERE follower_id=%s AND followed_id=%s",
                (uid, project["owner_id"]),
            )
        )

    members = q_all(
        """
        SELECT pm.role, u.id, u.username
        FROM project_members pm
        JOIN users u ON u.id = pm.user_id
        WHERE pm.project_id=%s
        ORDER BY FIELD(pm.role,'OWNER','MAINTAINER','DEVELOPER','VIEWER'), u.username
        """,
        (project_id,),
    )

    files = q_all(
        """
        SELECT f.id, f.path, f.updated_at, u.username AS editor
        FROM files f
        JOIN users u ON u.id = f.last_editor_id
        WHERE f.project_id=%s
        ORDER BY f.updated_at DESC
        LIMIT 15
        """,
        (project_id,),
    )

    issues = q_all(
        """
        SELECT i.id, i.title, i.status, i.priority, i.created_at,
               u.username AS creator,
               ua.username AS assignee
        FROM issues i
        JOIN users u ON u.id = i.creator_id
        LEFT JOIN users ua ON ua.id = i.assignee_id
        WHERE i.project_id=%s
        ORDER BY i.created_at DESC
        LIMIT 10
        """,
        (project_id,),
    )

    prs = q_all(
        """
        SELECT pr.id, pr.title, pr.status, pr.source_branch, pr.target_branch, pr.created_at,
               u.username AS author
        FROM pull_requests pr
        JOIN users u ON u.id = pr.author_id
        WHERE pr.project_id=%s
        ORDER BY pr.created_at DESC
        LIMIT 10
        """,
        (project_id,),
    )

    can_manage = (project["owner_id"] == uid)

    return render_template(
        "project_view.html",
        project=project,
        is_starred=is_starred,
        is_following_owner=is_following_owner,
        members=members,
        files=files,
        issues=issues,
        prs=prs,
        can_manage=can_manage,
    )

# ---- STAR / UNSTAR (AJAX) ----
@app.route("/api/projects/<int:project_id>/star", methods=["POST"])
def api_star(project_id):
    if not login_required():
        return jsonify({"ok": False, "error": "Not logged in"}), 401
    uid = session["user_id"]

    exists = q_one("SELECT 1 AS ok FROM stars WHERE user_id=%s AND project_id=%s", (uid, project_id))
    if exists:
        _, err = exec_sql("DELETE FROM stars WHERE user_id=%s AND project_id=%s", (uid, project_id))
        if err:
            return jsonify({"ok": False, "error": err}), 400
        p = q_one("SELECT stars_count FROM projects WHERE id=%s", (project_id,))
        return jsonify({"ok": True, "starred": False, "stars_count": p["stars_count"]})

    _, err = exec_sql("INSERT INTO stars(user_id, project_id) VALUES (%s,%s)", (uid, project_id))
    if err:
        return jsonify({"ok": False, "error": err}), 400
    p = q_one("SELECT stars_count FROM projects WHERE id=%s", (project_id,))
    return jsonify({"ok": True, "starred": True, "stars_count": p["stars_count"]})

# ---- FOLLOW / UNFOLLOW OWNER (AJAX) ----
@app.route("/api/users/<int:user_id>/follow", methods=["POST"])
def api_follow(user_id):
    if not login_required():
        return jsonify({"ok": False, "error": "Not logged in"}), 401
    uid = session["user_id"]

    exists = q_one("SELECT 1 AS ok FROM followers WHERE follower_id=%s AND followed_id=%s", (uid, user_id))
    if exists:
        _, err = exec_sql("DELETE FROM followers WHERE follower_id=%s AND followed_id=%s", (uid, user_id))
        if err:
            return jsonify({"ok": False, "error": err}), 400
        m = q_one("SELECT followers_count FROM users WHERE id=%s", (user_id,))
        return jsonify({"ok": True, "following": False, "followers_count": m["followers_count"]})

    _, err = exec_sql("INSERT INTO followers(follower_id, followed_id) VALUES (%s,%s)", (uid, user_id))
    if err:
        return jsonify({"ok": False, "error": err}), 400
    m = q_one("SELECT followers_count FROM users WHERE id=%s", (user_id,))
    return jsonify({"ok": True, "following": True, "followers_count": m["followers_count"]})

# ---- ARCHIVE / UNARCHIVE ----
@app.route("/projects/<int:project_id>/archive", methods=["POST"])
def project_archive(project_id):
    if not login_required():
        return redirect(url_for("login"))

    uid = session["user_id"]
    p = q_one("SELECT id, owner_id, status FROM projects WHERE id=%s", (project_id,))
    if not p:
        flash("Project not found.", "danger")
        return redirect(url_for("dashboard"))
    if p["owner_id"] != uid:
        flash("Only the owner can archive this project.", "danger")
        return redirect(url_for("project_view", project_id=project_id))

    new_status = "ARCHIVED" if p["status"] == "ACTIVE" else "ACTIVE"
    _, err = exec_sql("UPDATE projects SET status=%s WHERE id=%s", (new_status, project_id))
    if err:
        flash(f"Failed: {err}", "danger")
    else:
        flash(f"Project set to {new_status}.", "success")
        log_activity(uid, project_id, "STATUS_CHANGE", "PROJECT", project_id, None)

    return redirect(url_for("project_view", project_id=project_id))

# ---- FILES: create/update a file (simple editor) ----
@app.route("/projects/<int:project_id>/files/save", methods=["POST"])
def file_save(project_id):
    if not login_required():
        return redirect(url_for("login"))
    uid = session["user_id"]

    path = request.form.get("path", "").strip()
    content = request.form.get("content", "")

    if not path:
        flash("File path is required.", "danger")
        return redirect(url_for("project_view", project_id=project_id))

    # owner or member required
    member = q_one("SELECT 1 AS ok FROM project_members WHERE project_id=%s AND user_id=%s", (project_id, uid))
    if not member:
        flash("You must be a project member to edit files.", "danger")
        return redirect(url_for("project_view", project_id=project_id))

    # upsert by unique (project_id, path)
    existing = q_one("SELECT id FROM files WHERE project_id=%s AND path=%s", (project_id, path))
    if existing:
        _, err = exec_sql(
            "UPDATE files SET content=%s, last_editor_id=%s WHERE id=%s",
            (content, uid, existing["id"]),
        )
        if err:
            flash(f"Save failed: {err}", "danger")
        else:
            flash("File updated.", "success")
            log_activity(uid, project_id, "UPDATE", "FILE", existing["id"], None)
    else:
        fid, err = exec_sql(
            "INSERT INTO files(project_id, path, content, last_editor_id) VALUES (%s,%s,%s,%s)",
            (project_id, path, content, uid),
        )
        if err:
            flash(f"Save failed: {err}", "danger")
        else:
            flash("File created.", "success")
            log_activity(uid, project_id, "CREATE", "FILE", fid, None)

    return redirect(url_for("project_view", project_id=project_id))

# ---- ISSUES: create ----
@app.route("/projects/<int:project_id>/issues/new", methods=["POST"])
def issue_new(project_id):
    if not login_required():
        return redirect(url_for("login"))
    uid = session["user_id"]

    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    priority = request.form.get("priority", "MEDIUM").strip().upper()
    assignee_id = request.form.get("assignee_id", "").strip()

    if not title:
        flash("Issue title is required.", "danger")
        return redirect(url_for("project_view", project_id=project_id))

    assignee_val = int(assignee_id) if assignee_id.isdigit() else None

    _, err = exec_sql(
        """
        INSERT INTO issues(project_id, creator_id, assignee_id, title, description, priority)
        VALUES (%s,%s,%s,%s,%s,%s)
        """,
        (project_id, uid, assignee_val, title, description, priority),
    )
    if err:
        flash(f"Issue create failed: {err}", "danger")
    else:
        flash("Issue created.", "success")

    return redirect(url_for("project_view", project_id=project_id))

# ---- PR: create ----
@app.route("/projects/<int:project_id>/prs/new", methods=["POST"])
def pr_new(project_id):
    if not login_required():
        return redirect(url_for("login"))
    uid = session["user_id"]

    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    source_branch = request.form.get("source_branch", "").strip()
    target_branch = request.form.get("target_branch", "main").strip()

    if not title or not source_branch:
        flash("PR title and source branch are required.", "danger")
        return redirect(url_for("project_view", project_id=project_id))

    _, err = exec_sql(
        """
        INSERT INTO pull_requests(project_id, author_id, title, description, source_branch, target_branch, status)
        VALUES (%s,%s,%s,%s,%s,%s,'IN_REVIEW')
        """,
        (project_id, uid, title, description, source_branch, target_branch),
    )
    if err:
        flash(f"PR create failed: {err}", "danger")
    else:
        flash("Pull request created.", "success")

    return redirect(url_for("project_view", project_id=project_id))

# ---- PROFILE ----
@app.route("/profile", methods=["GET", "POST"])
def profile():
    if not login_required():
        return redirect(url_for("login"))
    uid = session["user_id"]

    if request.method == "POST":
        bio = request.form.get("bio", "").strip()
        username = request.form.get("username", "").strip()

        # update username + bio (username has checks)
        _, err = exec_sql("UPDATE users SET username=%s, bio=%s WHERE id=%s", (username, bio, uid))
        if err:
            flash(f"Update failed: {err}", "danger")
        else:
            flash("Profile updated.", "success")
            log_activity(uid, None, "UPDATE", "USER", uid, None)

        return redirect(url_for("profile"))

    user = q_one("SELECT id, username, email, bio, followers_count, following_count FROM users WHERE id=%s", (uid,))
    return render_template("profile.html", user=user)

if __name__ == "__main__":
    app.run(debug=True)
