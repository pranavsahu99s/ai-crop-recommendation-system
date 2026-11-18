"""Register, login and logout (use cases: Register, Login)."""
import sqlite3

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from .db import get_db, log_activity
from .domain import Farmer
from .security import current_role, login_user

bp = Blueprint("auth", __name__)


def _safe_next(target):
    return target if target and target.startswith("/") and not target.startswith("//") else None


@bp.route("/")
def index():
    if current_role() == "farmer":
        return redirect(url_for("farmer.dashboard"))
    if current_role() == "admin":
        return redirect(url_for("admin.overview"))
    return render_template("index.html")


@bp.route("/register", methods=["GET", "POST"])
def register():
    form, errors = {}, {}
    if request.method == "POST":
        form, errors = Farmer.validate_registration(request.form)
        if not errors:
            db = get_db()
            try:
                db.execute(
                    "INSERT INTO farmers (name, location, contact_no, password_hash) VALUES (?, ?, ?, ?)",
                    (form["name"], form["location"], form["contact_no"], generate_password_hash(form["password"])))
                log_activity(form["contact_no"], "register", form["name"])
                db.commit()
            except sqlite3.IntegrityError:
                # Contact number is UNIQUE; no duplicate farmer is created (TC-04).
                errors["contact_no"] = "This contact number is already registered. Log in instead."
            else:
                flash("Account created. Log in with your contact number.", "success")
                return redirect(url_for("auth.login", contact_no=form["contact_no"]))
        form.pop("password", None)
    return render_template("auth/register.html", form=form, errors=errors)


@bp.route("/login", methods=["GET", "POST"])
def login():
    role = request.values.get("role", "farmer")
    if role not in ("farmer", "admin"):
        role = "farmer"
    error = None
    identifier = request.values.get("contact_no") or request.values.get("username") or ""

    if request.method == "POST":
        identifier = (request.form.get("identifier") or "").strip()
        password = request.form.get("password") or ""
        db = get_db()
        if role == "admin":
            row = db.execute("SELECT admin_id AS id, name, password_hash FROM admins WHERE username = ?",
                             (identifier,)).fetchone()
        else:
            row = db.execute("SELECT farmer_id AS id, name, password_hash, status FROM farmers"
                             " WHERE contact_no = ?", (identifier.replace(" ", ""),)).fetchone()
        if row and check_password_hash(row["password_hash"], password):
            if role == "farmer" and row["status"] != "active":
                error = "This account has been disabled. Contact the administrator."
            else:
                login_user(role, row["id"], row["name"])
                log_activity(identifier, "login", role)
                db.commit()
                dest = _safe_next(request.args.get("next"))
                if role == "admin":
                    return redirect(dest if dest and dest.startswith("/admin") else url_for("admin.overview"))
                return redirect(dest if dest and not dest.startswith("/admin") else url_for("farmer.dashboard"))
        else:
            error = "The contact number or password is incorrect." if role == "farmer" \
                else "The username or password is incorrect."
    return render_template("auth/login.html", role=role, identifier=identifier, error=error), (401 if error else 200)


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))
