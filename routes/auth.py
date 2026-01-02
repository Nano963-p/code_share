import re

import mysql.connector
from flask import render_template, request, redirect, url_for, flash, session

from db import fetchone, execute
from utils import hash_password, verify_password


_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]+$")
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


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

    # Basic validation BEFORE hitting DB constraints, so we show friendly messages
    if not (3 <= len(username) <= 30):
        flash("Username must be between 3 and 30 characters.", "error")
        return redirect(url_for("signup"))

    if not _USERNAME_RE.match(username):
        flash("Username can only contain letters, numbers, and underscore (_).", "error")
        return redirect(url_for("signup"))

    if not _EMAIL_RE.match(email):
        flash("Please enter a valid email address.", "error")
        return redirect(url_for("signup"))

    if len(password) < 6:
        flash("Password must be at least 6 characters.", "error")
        return redirect(url_for("signup"))

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

    try:
        uid = execute(
            "INSERT INTO users (username, email, password_hash) VALUES (%s, %s, %s)",
            (username, email, hash_password(password)),
        )
    except mysql.connector.Error as e:
        # 3819: CHECK constraint violated (MySQL 8)
        # 1062: duplicate key
        if getattr(e, "errno", None) == 3819:
            flash(
                "Invalid username or email format. Username: letters/numbers/underscore only; Email must be valid.",
                "error",
            )
        elif getattr(e, "errno", None) == 1062:
            flash("Username or email already exists.", "error")
        else:
            flash("Could not create account due to a database error.", "error")
        return redirect(url_for("signup"))

    session["user_id"] = uid
    return redirect(url_for("dashboard"))


def logout():
    session.clear()
    return redirect(url_for("login"))
