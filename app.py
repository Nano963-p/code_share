from flask import Flask, render_template, request, redirect, session, url_for, abort, flash, send_file
import os
from db import get_db, init_app
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "REDACTED")
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Initialiser la base de données
init_app(app)

# Configuration
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "pdf", "txt", "py", "js", "html", "css", "md"}
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10 MB

def allowed_file(filename):
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
    """Récupère les informations de l'utilisateur connecté"""
    if session.get("user_id"):
        db = get_db()
        cur = db.cursor()
        cur.execute("SELECT id, username, email FROM users WHERE id=%s", (session["user_id"],))
        return cur.fetchone()
    return None

# ==================== AUTHENTIFICATION ====================

@app.route("/", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    
    if request.method == "POST":
        db = get_db()
        cur = db.cursor()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        
        if not username or not password:
            flash("Veuillez remplir tous les champs.", "danger")
            return render_template("login.html")
        
        try:
            cur.execute("SELECT id, password FROM users WHERE username=%s", (username,))
            row = cur.fetchone()
            
            if row and check_password_hash(row[1], password):
                session.clear()
                session["user_id"] = row[0]
                flash(f"Bienvenue {username}!", "success")
                return redirect(url_for("dashboard"))
            else:
                flash("Nom d'utilisateur ou mot de passe incorrect.", "danger")
        except Exception as e:
            print(f"Erreur lors de la connexion: {e}")
            flash("Une erreur est survenue. Veuillez réessayer.", "danger")
        finally:
            cur.close()
    
    return render_template("login.html")

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    
    if request.method == "POST":
        db = get_db()
        cur = db.cursor()
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        
        # Validation
        if not username or not email or not password:
            flash("Tous les champs sont obligatoires.", "danger")
            return render_template("signup.html")
        
        if password != confirm_password:
            flash("Les mots de passe ne correspondent pas.", "danger")
            return render_template("signup.html")
        
        if len(password) < 6:
            flash("Le mot de passe doit contenir au moins 6 caractères.", "danger")
            return render_template("signup.html")
        
        try:
            # Vérifier si l'utilisateur existe déjà
            cur.execute("SELECT id FROM users WHERE username=%s OR email=%s", (username, email))
            if cur.fetchone():
                flash("Ce nom d'utilisateur ou email est déjà utilisé.", "danger")
                return render_template("signup.html")
            
            # Créer l'utilisateur
            hashed_pw = generate_password_hash(password)
            cur.execute("INSERT INTO users (username, email, password) VALUES (%s, %s, %s)",
                       (username, email, hashed_pw))
            db.commit()
            flash("Compte créé avec succès! Vous pouvez maintenant vous connecter.", "success")
            return redirect(url_for("login"))
        except Exception as e:
            db.rollback()
            print(f"Erreur lors de la création du compte: {e}")
            flash("Une erreur est survenue lors de la création du compte.", "danger")
        finally:
            cur.close()
    
    return render_template("signup.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("Vous avez été déconnecté.", "info")
    return redirect(url_for("login"))

# ==================== DASHBOARD ====================

@app.route("/dashboard", methods=["GET", "POST"])
@login_required
def dashboard():
    db = get_db()
    cur = db.cursor()
    uid = session.get("user_id")
    
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        
        if not title:
            flash("Le titre du projet est obligatoire.", "danger")
        else:
            try:
                cur.execute("INSERT INTO projects (title, description, owner_id) VALUES (%s, %s, %s)",
                           (title, description, uid))
                project_id = cur.lastrowid
                
                # Ajouter le créateur comme membre avec le rôle "owner"
                cur.execute("INSERT INTO project_members (project_id, user_id, role) VALUES (%s, %s, %s)",
                           (project_id, uid, "owner"))
                db.commit()
                flash("Projet créé avec succès!", "success")
                return redirect(url_for("project", pid=project_id))
            except Exception as e:
                db.rollback()
                print(f"Erreur lors de la création du projet: {e}")
                flash("Erreur lors de la création du projet.", "danger")
            finally:
                cur.close()
    
    # Récupérer tous les projets avec informations supplémentaires
    try:
        cur.execute("""
            SELECT p.id, p.title, p.description, p.created_at, 
                   u.username as owner_name,
                   (SELECT COUNT(*) FROM likes WHERE project_id = p.id) as like_count,
                   (SELECT COUNT(*) FROM comments WHERE project_id = p.id) as comment_count
            FROM projects p
            JOIN users u ON p.owner_id = u.id
            ORDER BY p.created_at DESC
        """)
        projects = cur.fetchall()
        
        # Récupérer les projets de l'utilisateur
        cur.execute("""
            SELECT p.id, p.title, p.description, p.created_at,
                   (SELECT COUNT(*) FROM project_members WHERE project_id = p.id) as member_count
            FROM projects p
            WHERE p.owner_id = %s
            ORDER BY p.created_at DESC
        """, (uid,))
        my_projects = cur.fetchall()
    except Exception as e:
        print(f"Erreur lors de la récupération des projets: {e}")
        projects = []
        my_projects = []
        flash("Erreur lors du chargement des projets.", "danger")
    finally:
        cur.close()
    
    return render_template("dashboard.html", projects=projects, my_projects=my_projects)

# ==================== PROJET ====================

@app.route("/project/<int:pid>", methods=["GET", "POST"])
@login_required
def project(pid):
    db = get_db()
    cur = db.cursor()
    uid = session.get("user_id")
    
    try:
        # Vérifier que le projet existe
        cur.execute("""
            SELECT p.*, u.username as owner_name 
            FROM projects p 
            JOIN users u ON p.owner_id = u.id 
            WHERE p.id = %s
        """, (pid,))
        project_data = cur.fetchone()
        
        if not project_data:
            flash("Projet introuvable.", "danger")
            return redirect(url_for("dashboard"))
        
        if request.method == "POST":
            # Ajouter un commentaire
            if "comment" in request.form:
                msg = request.form.get("comment", "").strip()
                if msg:
                    cur.execute("INSERT INTO comments (project_id, user_id, message) VALUES (%s, %s, %s)",
                               (pid, uid, msg))
                    db.commit()
                    flash("Commentaire ajouté!", "success")
            
            # Upload de fichier
            if "file" in request.files:
                f = request.files["file"]
                if f and f.filename and allowed_file(f.filename):
                    filename = secure_filename(f.filename)
                    # Ajouter timestamp pour éviter les collisions
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    filename = f"{timestamp}_{filename}"
                    path = os.path.join(UPLOAD_FOLDER, filename)
                    abs_path = os.path.abspath(path)
                    
                    # Sécurité: vérifier que le chemin est dans le dossier uploads
                    if not abs_path.startswith(os.path.abspath(UPLOAD_FOLDER) + os.sep):
                        flash("Chemin de fichier invalide.", "danger")
                    else:
                        try:
                            f.save(abs_path)
                            cur.execute("""INSERT INTO files (project_id, filename, filepath, uploaded_by) 
                                          VALUES (%s, %s, %s, %s)""",
                                       (pid, filename, abs_path, uid))
                            db.commit()
                            flash("Fichier téléchargé avec succès!", "success")
                        except Exception as e:
                            print(f"Erreur upload: {e}")
                            flash("Erreur lors du téléchargement du fichier.", "danger")
                else:
                    flash("Type de fichier non autorisé.", "danger")
            
            return redirect(url_for("project", pid=pid))
        
        # Récupérer les commentaires avec les noms d'utilisateur
        cur.execute("""
            SELECT c.id, c.message, c.created_at, u.username 
            FROM comments c 
            JOIN users u ON c.user_id = u.id 
            WHERE c.project_id = %s 
            ORDER BY c.created_at DESC
        """, (pid,))
        comments = cur.fetchall()
        
        # Récupérer les fichiers
        cur.execute("""
            SELECT f.id, f.filename, f.uploaded_at, u.username 
            FROM files f 
            JOIN users u ON f.uploaded_by = u.id 
            WHERE f.project_id = %s 
            ORDER BY f.uploaded_at DESC
        """, (pid,))
        files = cur.fetchall()
        
        # Nombre de likes
        cur.execute("SELECT COUNT(*) FROM likes WHERE project_id = %s", (pid,))
        like_count = cur.fetchone()[0]
        
        # Vérifier si l'utilisateur a liké
        cur.execute("SELECT 1 FROM likes WHERE user_id = %s AND project_id = %s", (uid, pid))
        user_liked = cur.fetchone() is not None
        
        # Récupérer les membres du projet
        cur.execute("""
            SELECT u.id, u.username, pm.role 
            FROM project_members pm 
            JOIN users u ON pm.user_id = u.id 
            WHERE pm.project_id = %s
        """, (pid,))
        members = cur.fetchall()
        
        # Vérifier si l'utilisateur est le propriétaire
        is_owner = project_data[3] == uid  # owner_id
        
    except Exception as e:
        print(f"Erreur dans la page projet: {e}")
        flash("Une erreur est survenue.", "danger")
        return redirect(url_for("dashboard"))
    finally:
        cur.close()
    
    return render_template("project.html", 
                          project=project_data, 
                          comments=comments, 
                          files=files,
                          like_count=like_count,
                          user_liked=user_liked,
                          members=members,
                          is_owner=is_owner)

@app.route("/like/<int:pid>", methods=["POST"])
@login_required
def like(pid):
    db = get_db()
    cur = db.cursor()
    uid = session.get("user_id")
    
    try:
        # Vérifier si déjà liké
        cur.execute("SELECT 1 FROM likes WHERE user_id = %s AND project_id = %s", (uid, pid))
        if cur.fetchone():
            # Unlike
            cur.execute("DELETE FROM likes WHERE user_id = %s AND project_id = %s", (uid, pid))
            db.commit()
            flash("Like retiré.", "info")
        else:
            # Like
            cur.execute("INSERT INTO likes (user_id, project_id) VALUES (%s, %s)", (uid, pid))
            db.commit()
            flash("Projet liké!", "success")
    except Exception as e:
        print(f"Erreur lors du like: {e}")
        db.rollback()
    finally:
        cur.close()
    
    return redirect(url_for("project", pid=pid))

# ==================== TÉLÉCHARGEMENT DE FICHIERS ====================

@app.route("/download/<int:file_id>")
@login_required
def download_file(file_id):
    db = get_db()
    cur = db.cursor()
    
    try:
        # Récupérer les informations du fichier
        cur.execute("SELECT filename, filepath FROM files WHERE id = %s", (file_id,))
        file_data = cur.fetchone()
        
        if not file_data:
            flash("Fichier introuvable.", "danger")
            return redirect(url_for("dashboard"))
        
        filename = file_data[0]
        filepath = file_data[1]
        
        # Vérifier que le fichier existe
        if not os.path.exists(filepath):
            flash("Le fichier n'existe plus sur le serveur.", "danger")
            return redirect(url_for("dashboard"))
        
        # Envoyer le fichier
        return send_file(filepath, as_attachment=True, download_name=filename)
    
    except Exception as e:
        print(f"Erreur téléchargement: {e}")
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
        # Récupérer les infos du fichier et vérifier les permissions
        cur.execute("""
            SELECT f.filepath, f.project_id, p.owner_id 
            FROM files f 
            JOIN projects p ON f.project_id = p.id 
            WHERE f.id = %s
        """, (file_id,))
        file_data = cur.fetchone()
        
        if not file_data:
            flash("Fichier introuvable.", "danger")
            return redirect(url_for("dashboard"))
        
        filepath, project_id, owner_id = file_data
        
        # Vérifier si l'utilisateur est le propriétaire du projet
        if owner_id != uid:
            flash("Vous n'avez pas la permission de supprimer ce fichier.", "danger")
            return redirect(url_for("project", pid=project_id))
        
        # Supprimer le fichier physique
        if os.path.exists(filepath):
            os.remove(filepath)
        
        # Supprimer l'entrée de la base de données
        cur.execute("DELETE FROM files WHERE id = %s", (file_id,))
        db.commit()
        flash("Fichier supprimé avec succès.", "success")
        return redirect(url_for("project", pid=project_id))
    
    except Exception as e:
        print(f"Erreur suppression fichier: {e}")
        db.rollback()
        flash("Erreur lors de la suppression.", "danger")
        return redirect(url_for("dashboard"))
    finally:
        cur.close()

# ==================== GESTION DES MEMBRES ====================

@app.route("/project/<int:pid>/add_member", methods=["POST"])
@login_required
def add_member(pid):
    db = get_db()
    cur = db.cursor()
    uid = session.get("user_id")
    
    try:
        # Vérifier que l'utilisateur est le propriétaire
        cur.execute("SELECT owner_id FROM projects WHERE id = %s", (pid,))
        project = cur.fetchone()
        
        if not project or project[0] != uid:
            flash("Vous n'avez pas la permission d'ajouter des membres.", "danger")
            return redirect(url_for("project", pid=pid))
        
        username = request.form.get("username", "").strip()
        role = request.form.get("role", "member")
        
        # Trouver l'utilisateur
        cur.execute("SELECT id FROM users WHERE username = %s", (username,))
        user = cur.fetchone()
        
        if not user:
            flash("Utilisateur introuvable.", "danger")
        else:
            cur.execute("INSERT INTO project_members (project_id, user_id, role) VALUES (%s, %s, %s)",
                       (pid, user[0], role))
            db.commit()
            flash(f"Membre {username} ajouté avec succès!", "success")
    except Exception as e:
        print(f"Erreur ajout membre: {e}")
        flash("Cet utilisateur est déjà membre du projet.", "warning")
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
        # Vérifier que l'utilisateur est le propriétaire
        cur.execute("SELECT owner_id FROM projects WHERE id = %s", (pid,))
        project = cur.fetchone()
        
        if not project or project[0] != uid:
            flash("Vous n'avez pas la permission de retirer des membres.", "danger")
            return redirect(url_for("project", pid=pid))
        
        # Ne pas permettre de retirer le propriétaire
        if member_id == uid:
            flash("Vous ne pouvez pas vous retirer vous-même du projet.", "danger")
        else:
            cur.execute("DELETE FROM project_members WHERE project_id = %s AND user_id = %s",
                       (pid, member_id))
            db.commit()
            flash("Membre retiré du projet.", "success")
    except Exception as e:
        print(f"Erreur retrait membre: {e}")
        db.rollback()
        flash("Erreur lors du retrait du membre.", "danger")
    finally:
        cur.close()
    
    return redirect(url_for("project", pid=pid))

# ==================== PROFIL ====================

@app.route("/profile")
@login_required
def profile():
    db = get_db()
    cur = db.cursor()
    uid = session.get("user_id")
    
    try:
        # Informations utilisateur
        cur.execute("SELECT username, email, created_at FROM users WHERE id = %s", (uid,))
        user = cur.fetchone()
        
        # Statistiques
        cur.execute("SELECT COUNT(*) FROM projects WHERE owner_id = %s", (uid,))
        project_count = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM comments WHERE user_id = %s", (uid,))
        comment_count = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM likes WHERE user_id = %s", (uid,))
        like_count = cur.fetchone()[0]
    except Exception as e:
        print(f"Erreur profil: {e}")
        user = None
        project_count = 0
        comment_count = 0
        like_count = 0
    finally:
        cur.close()
    
    return render_template("profile.html", 
                          user=user, 
                          project_count=project_count,
                          comment_count=comment_count,
                          like_count=like_count)

# ==================== ERREURS ====================

@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404

@app.errorhandler(413)
def too_large(e):
    flash("Le fichier est trop volumineux. Taille maximale: 10 MB", "danger")
    return redirect(request.referrer or url_for("dashboard"))

if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=5000)