# ...existing code...
import os
import logging
from datetime import datetime
from functools import wraps

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    session,
    url_for,
    flash,
    send_file,
)
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

from db import get_db, init_app

# --- config / logging ---
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "REDACTED")

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10 MB

init_app(app)

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "pdf", "txt", "py", "js", "html", "css", "md"}


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def login_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            flash("Vous devez être connecté pour accéder à cette page.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)

    return wrapped


def get_current_user():
    """Return small dict for templates (id, username, email) or None."""
    uid = session.get("user_id")
    if not uid:
        return None
    db = get_db()
    cur = db.cursor()
    try:
        cur.execute("SELECT id, username, email FROM users WHERE id = %s", (uid,))
        row = cur.fetchone()
        if not row:
            return None
        return {"id": row[0], "username": row[1], "email": row[2]}
    except Exception as e:
        logger.error("get_current_user error: %s", e)
        return None
    finally:
        cur.close()


# ---------------- AUTH ----------------

@app.route("/", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        if not username or not password:
            flash("Veuillez remplir tous les champs.", "danger")
            return render_template("login.html")

        db = get_db()
        cur = db.cursor()
        try:
            cur.execute("SELECT id, password FROM users WHERE username = %s", (username,))
            row = cur.fetchone()
            if row and check_password_hash(row[1], password):
                session.clear()
                session["user_id"] = row[0]
                flash(f"Bienvenue {username}!", "success")
                return redirect(url_for("dashboard"))
            flash("Nom d'utilisateur ou mot de passe incorrect.", "danger")
        except Exception as e:
            logger.error("Login error: %s", e)
            flash("Une erreur est survenue. Veuillez réessayer.", "danger")
        finally:
            cur.close()

    return render_template("login.html")


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        email = (request.form.get("email") or "").strip()
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm_password") or ""

        if not username or not email or not password:
            flash("Tous les champs sont obligatoires.", "danger")
            return render_template("signup.html")
        if password != confirm:
            flash("Les mots de passe ne correspondent pas.", "danger")
            return render_template("signup.html")
        if len(password) < 6:
            flash("Le mot de passe doit contenir au moins 6 caractères.", "danger")
            return render_template("signup.html")

        db = get_db()
        cur = db.cursor()
        try:
            cur.execute("SELECT id FROM users WHERE username = %s OR email = %s", (username, email))
            if cur.fetchone():
                flash("Ce nom d'utilisateur ou email est déjà utilisé.", "danger")
                return render_template("signup.html")

            hashed = generate_password_hash(password)
            cur.execute("INSERT INTO users (username, email, password) VALUES (%s, %s, %s)", (username, email, hashed))
            db.commit()
            flash("Compte créé avec succès! Vous pouvez maintenant vous connecter.", "success")
            return redirect(url_for("login"))
        except Exception as e:
            db.rollback()
            logger.error("Signup error: %s", e)
            flash("Une erreur est survenue lors de la création du compte.", "danger")
        finally:
            cur.close()

    return render_template("signup.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Vous avez été déconnecté.", "info")
    return redirect(url_for("login"))


# ---------------- DASHBOARD ----------------

@app.route("/dashboard", methods=["GET", "POST"])
@login_required
def dashboard():
    db = get_db()
    uid = session.get("user_id")

    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        description = (request.form.get("description") or "").strip()
        if not title:
            flash("Le titre du projet est obligatoire.", "danger")
            return redirect(url_for("dashboard"))
        cur = db.cursor()
        try:
            cur.execute("INSERT INTO projects (title, description, owner_id) VALUES (%s, %s, %s)", (title, description, uid))
            project_id = cur.lastrowid
            cur.execute("INSERT INTO project_members (project_id, user_id, role) VALUES (%s, %s, %s)", (project_id, uid, "owner"))
            db.commit()
            flash("Projet créé avec succès!", "success")
            return redirect(url_for("project", pid=project_id))
        except Exception as e:
            db.rollback()
            logger.error("Create project error: %s", e)
            flash("Erreur lors de la création du projet.", "danger")
        finally:
            cur.close()

    projects = []
    my_projects = []
    cur = db.cursor()
    try:
        cur.execute(
            """
            SELECT
              p.id, p.title, p.description, p.created_at,
              u.username AS owner_name,
              (SELECT COUNT(*) FROM likes WHERE project_id = p.id) AS like_count,
              (SELECT COUNT(*) FROM comments WHERE project_id = p.id) AS comment_count,
              (SELECT COUNT(*) FROM project_members WHERE project_id = p.id) AS member_count
            FROM projects p
            JOIN users u ON p.owner_id = u.id
            ORDER BY p.created_at DESC
            """
        )
        projects = cur.fetchall()

        cur.execute(
            """
            SELECT
              p.id, p.title, p.description, p.created_at,
              u.username AS owner_name,
              (SELECT COUNT(*) FROM likes WHERE project_id = p.id) AS like_count,
              (SELECT COUNT(*) FROM comments WHERE project_id = p.id) AS comment_count,
              (SELECT COUNT(*) FROM project_members WHERE project_id = p.id) AS member_count
            FROM projects p
            JOIN users u ON p.owner_id = u.id
            WHERE p.owner_id = %s
            ORDER BY p.created_at DESC
            """,
            (uid,),
        )
        my_projects = cur.fetchall()
    except Exception as e:
        logger.error("Dashboard query error: %s", e)
        flash(f"Erreur lors du chargement des projets: {str(e)}", "danger")
    finally:
        cur.close()

    # keep tuples so templates using p[0], etc. work
    return render_template("dashboard.html", projects=projects, my_projects=my_projects)


# ---------------- PROJECT ----------------

@app.route("/project/<int:pid>", methods=["GET", "POST"])
@login_required
def project(pid):
    db = get_db()
    uid = session.get("user_id")
    cur = db.cursor()
    try:
        cur.execute(
            """
            SELECT p.id, p.title, p.description, p.owner_id, p.created_at, u.username AS owner_name
            FROM projects p
            JOIN users u ON p.owner_id = u.id
            WHERE p.id = %s
            """,
            (pid,),
        )
        project_data = cur.fetchone()
        if not project_data:
            flash("Projet introuvable.", "danger")
            return redirect(url_for("dashboard"))

        is_owner = project_data[3] == uid

        if request.method == "POST":
            if "comment" in request.form:
                msg = (request.form.get("comment") or "").strip()
                if msg:
                    try:
                        cur.execute("INSERT INTO comments (project_id, user_id, message) VALUES (%s, %s, %s)", (pid, uid, msg))
                        db.commit()
                        flash("Commentaire ajouté!", "success")
                    except Exception as e:
                        db.rollback()
                        logger.error("Add comment error: %s", e)
                        flash("Erreur lors de l'ajout du commentaire.", "danger")
            elif "file" in request.files:
                f = request.files["file"]
                if f and f.filename and allowed_file(f.filename):
                    filename = secure_filename(f.filename)
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    filename = f"{timestamp}_{filename}"
                    path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
                    abs_path = os.path.abspath(path)
                    if not abs_path.startswith(os.path.abspath(app.config["UPLOAD_FOLDER"]) + os.sep):
                        flash("Chemin de fichier invalide.", "danger")
                    else:
                        try:
                            f.save(abs_path)
                            cur.execute(
                                "INSERT INTO files (project_id, filename, filepath, uploaded_by) VALUES (%s, %s, %s, %s)",
                                (pid, filename, abs_path, uid),
                            )
                            db.commit()
                            flash("Fichier téléchargé avec succès!", "success")
                        except Exception as e:
                            db.rollback()
                            logger.error("File upload error: %s", e)
                            flash("Erreur lors du téléchargement du fichier.", "danger")
                else:
                    flash("Type de fichier non autorisé.", "danger")
            return redirect(url_for("project", pid=pid))

        # read comments and files
        cur.execute(
            """
            SELECT c.id, c.message, c.created_at, u.username
            FROM comments c
            JOIN users u ON c.user_id = u.id
            WHERE c.project_id = %s
            ORDER BY c.created_at DESC
            """,
            (pid,),
        )
        comments = cur.fetchall()

        cur.execute(
            """
            SELECT f.id, f.filename, f.uploaded_at, u.username, f.filepath
            FROM files f
            JOIN users u ON f.uploaded_by = u.id
            WHERE f.project_id = %s
            ORDER BY f.uploaded_at DESC
            """,
            (pid,),
        )
        files = cur.fetchall()
    except Exception as e:
        logger.error("Project page error: %s", e)
        flash("Une erreur est survenue.", "danger")
        cur.close()
        return redirect(url_for("dashboard"))
    finally:
        cur.close()

    # follow-up queries
    cur = db.cursor()
    try:
        cur.execute("SELECT COUNT(*) FROM likes WHERE project_id = %s", (pid,))
        lr = cur.fetchone()
        like_count = lr[0] if lr else 0

        cur.execute("SELECT 1 FROM likes WHERE user_id = %s AND project_id = %s", (uid, pid))
        user_liked = cur.fetchone() is not None

        cur.execute(
            """
            SELECT u.id, u.username, pm.role
            FROM project_members pm
            JOIN users u ON pm.user_id = u.id
            WHERE pm.project_id = %s
            """,
            (pid,),
        )
        members = cur.fetchall()
    except Exception as e:
        logger.error("Project follow-up error: %s", e)
        flash("Une erreur est survenue.", "danger")
        cur.close()
        return redirect(url_for("dashboard"))
    finally:
        cur.close()

    return render_template(
        "project.html",
        project=project_data,
        comments=comments,
        files=files,
        like_count=like_count,
        user_liked=user_liked,
        members=members,
        is_owner=is_owner,
    )


@app.route("/like/<int:pid>", methods=["POST"])
@login_required
def like(pid):
    db = get_db()
    uid = session.get("user_id")
    cur = db.cursor()
    try:
        cur.execute("SELECT 1 FROM likes WHERE user_id = %s AND project_id = %s", (uid, pid))
        if cur.fetchone():
            cur.execute("DELETE FROM likes WHERE user_id = %s AND project_id = %s", (uid, pid))
            db.commit()
            flash("Like retiré.", "info")
        else:
            cur.execute("INSERT INTO likes (user_id, project_id) VALUES (%s, %s)", (uid, pid))
            db.commit()
            flash("Projet liké!", "success")
    except Exception as e:
        db.rollback()
        logger.error("Like error: %s", e)
        flash("Erreur lors de l'action.", "danger")
    finally:
        cur.close()
    return redirect(url_for("project", pid=pid))


# ---------------- FILES ----------------

@app.route("/download/<int:file_id>")
@login_required
def download_file(file_id):
    db = get_db()
    cur = db.cursor()
    try:
        cur.execute("SELECT filename, filepath FROM files WHERE id = %s", (file_id,))
        row = cur.fetchone()
        if not row:
            flash("Fichier introuvable.", "danger")
            return redirect(url_for("dashboard"))
        filename, filepath = row[0], row[1]
        if not os.path.exists(filepath):
            flash("Le fichier n'existe plus sur le serveur.", "danger")
            return redirect(url_for("dashboard"))
        return send_file(filepath, as_attachment=True, download_name=filename)
    except Exception as e:
        logger.error("Download error: %s", e)
        flash("Erreur lors du téléchargement.", "danger")
        return redirect(url_for("dashboard"))
    finally:
        cur.close()


@app.route("/delete_file/<int:file_id>", methods=["POST"])
@login_required
def delete_file(file_id):
    db = get_db()
    cur = db.cursor()
    uid = session.get("user_id")
    try:
        cur.execute(
            """
            SELECT f.filepath, f.project_id, p.owner_id
            FROM files f
            JOIN projects p ON f.project_id = p.id
            WHERE f.id = %s
            """,
            (file_id,),
        )
        row = cur.fetchone()
        if not row:
            flash("Fichier introuvable.", "danger")
            return redirect(url_for("dashboard"))
        filepath, project_id, owner_id = row[0], row[1], row[2]
        if owner_id != uid:
            flash("Vous n'avez pas la permission de supprimer ce fichier.", "danger")
            return redirect(url_for("project", pid=project_id))
        if os.path.exists(filepath):
            os.remove(filepath)
        cur.execute("DELETE FROM files WHERE id = %s", (file_id,))
        db.commit()
        flash("Fichier supprimé avec succès.", "success")
        return redirect(url_for("project", pid=project_id))
    except Exception as e:
        db.rollback()
        logger.error("Delete file error: %s", e)
        flash("Erreur lors de la suppression.", "danger")
        return redirect(url_for("dashboard"))
    finally:
        cur.close()


# ---------------- MEMBERS ----------------

@app.route("/project/<int:pid>/add_member", methods=["POST"])
@login_required
def add_member(pid):
    db = get_db()
    cur = db.cursor()
    uid = session.get("user_id")
    try:
        cur.execute("SELECT owner_id FROM projects WHERE id = %s", (pid,))
        proj = cur.fetchone()
        if not proj or proj[0] != uid:
            flash("Vous n'avez pas la permission d'ajouter des membres.", "danger")
            return redirect(url_for("project", pid=pid))
        username = (request.form.get("username") or "").strip()
        role = request.form.get("role") or "member"
        cur.execute("SELECT id FROM users WHERE username = %s", (username,))
        user = cur.fetchone()
        if not user:
            flash("Utilisateur introuvable.", "danger")
        else:
            cur.execute("SELECT 1 FROM project_members WHERE project_id = %s AND user_id = %s", (pid, user[0]))
            if cur.fetchone():
                flash("Cet utilisateur est déjà membre du projet.", "warning")
            else:
                cur.execute("INSERT INTO project_members (project_id, user_id, role) VALUES (%s, %s, %s)", (pid, user[0], role))
                db.commit()
                flash(f"Membre {username} ajouté avec succès!", "success")
    except Exception as e:
        db.rollback()
        logger.error("Add member error: %s", e)
        flash("Une erreur est survenue lors de l'ajout du membre.", "danger")
    finally:
        cur.close()
    return redirect(url_for("project", pid=pid))


@app.route("/project/<int:pid>/remove_member/<int:member_id>", methods=["POST"])
@login_required
def remove_member(pid, member_id):
    db = get_db()
    cur = db.cursor()
    uid = session.get("user_id")
    try:
        cur.execute("SELECT owner_id FROM projects WHERE id = %s", (pid,))
        proj = cur.fetchone()
        if not proj or proj[0] != uid:
            flash("Vous n'avez pas la permission de retirer des membres.", "danger")
            return redirect(url_for("project", pid=pid))
        if member_id == uid:
            flash("Vous ne pouvez pas vous retirer vous-même du projet.", "danger")
        else:
            cur.execute("DELETE FROM project_members WHERE project_id = %s AND user_id = %s", (pid, member_id))
            db.commit()
            flash("Membre retiré du projet.", "success")
    except Exception as e:
        db.rollback()
        logger.error("Remove member error: %s", e)
        flash("Erreur lors du retrait du membre.", "danger")
    finally:
        cur.close()
    return redirect(url_for("project", pid=pid))


# ---------------- PROFILE ----------------

@app.route("/profile")
@login_required
def profile():
    """
    Templates expect `user` as a tuple where:
      user[0] = username (str)
      user[1] = email (str)
      user[2] = created_at (datetime)  <-- template uses .strftime on this element
      user[3] = id (int)
    """
    db = get_db()
    cur = db.cursor()
    uid = session.get("user_id")

    user_row = None
    project_count = comment_count = like_count = 0

    try:
        cur.execute("SELECT username, email, created_at, id FROM users WHERE id = %s", (uid,))
        user_row = cur.fetchone()
        if not user_row:
            flash("Utilisateur introuvable.", "danger")
            return redirect(url_for("dashboard"))

        cur.execute("SELECT COUNT(*) FROM projects WHERE owner_id = %s", (uid,))
        r = cur.fetchone()
        project_count = r[0] if r else 0

        cur.execute("SELECT COUNT(*) FROM comments WHERE user_id = %s", (uid,))
        r = cur.fetchone()
        comment_count = r[0] if r else 0

        cur.execute("SELECT COUNT(*) FROM likes WHERE user_id = %s", (uid,))
        r = cur.fetchone()
        like_count = r[0] if r else 0
    except Exception as e:
        logger.error("Profile error: %s", e)
        flash("Erreur lors du chargement du profil.", "danger")
        return redirect(url_for("dashboard"))
    finally:
        cur.close()

    return render_template("profile.html", user=user_row, project_count=project_count, comment_count=comment_count, like_count=like_count)


# ---------------- ERRORS & CONTEXT ----------------

@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404


@app.errorhandler(403)
def forbidden(e):
    return render_template("403.html"), 403


@app.errorhandler(500)
def server_error(e):
    logger.error("Server error: %s", e)
    return render_template("500.html"), 500


@app.errorhandler(413)
def too_large(e):
    flash("Le fichier est trop volumineux. Taille maximale: 10 MB", "danger")
    return redirect(request.referrer or url_for("dashboard"))


@app.context_processor
def inject_user():
    return {"current_user": get_current_user()}


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
# ...existing code...