from flask import render_template, request, redirect, url_for, flash, session
from db import fetchone, execute
from utils import hash_password, verify_password


def login():
    if request.method == "GET":
        return render_template("auth/login.html")

    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""

    u = fetchone(
        "SELECT id, username, password_hash FROM users WHERE username_norm = LOWER(TRIM(%s))",
        (username,),
    )
    if not u or not verify_password(password, u["password_hash"]):
        flash("Invalid username or password.", "error")
        return redirect(url_for("login"))

    session["user_id"] = u["id"]
    return redirect(url_for("dashboard"))


def signup():
    if request.method == "GET":
        return render_template("auth/signup.html")

    username = (request.form.get("username") or "").strip()
    email = (request.form.get("email") or "").strip()
    password = request.form.get("password") or ""
    confirm = request.form.get("confirm_password") or ""

    if password != confirm:
        flash("Passwords do not match.", "error")
        return redirect(url_for("signup"))

    existing = fetchone(
        "SELECT id FROM users WHERE username_norm=LOWER(TRIM(%s)) OR email_norm=LOWER(TRIM(%s))",
        (username, email),
    )
    if existing:
        flash("Username or email already exists.", "error")
        return redirect(url_for("signup"))

    uid = execute(
        "INSERT INTO users (username, email, password_hash) VALUES (%s, %s, %s)",
        (username, email, hash_password(password)),
    )
    session["user_id"] = uid
    return redirect(url_for("dashboard"))


def logout():
    session.clear()
    return redirect(url_for("login"))
