"""Authentication helpers, role checks, CSRF protection and session expiry."""
import hmac
import secrets
import time
from functools import wraps

from flask import abort, flash, redirect, request, session, url_for


def current_role():
    return session.get("role")


def login_user(role, user_id, name):
    session.clear()
    session.permanent = True
    session.update(role=role, uid=user_id, name=name, last_seen=int(time.time()),
                   csrf=secrets.token_urlsafe(32))


def farmer_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_role() != "farmer":
            if current_role() == "admin":
                abort(403)
            flash("Please log in to continue.", "info")
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    """Farmers get 403, anonymous users go to the login page (TC-30, TC-41)."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_role() != "admin":
            if current_role() == "farmer":
                abort(403)
            flash("Please log in as an administrator.", "info")
            return redirect(url_for("auth.login", role="admin"))
        return view(*args, **kwargs)
    return wrapped


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


def init_security(app):
    app.jinja_env.globals["csrf_token"] = csrf_token
    lifetime = app.config["PERMANENT_SESSION_LIFETIME"].total_seconds()

    @app.before_request
    def enforce_session_and_csrf():
        # Inactivity timeout (TC-43). The cookie itself is signed, so a tampered
        # value is discarded by Flask before this runs (TC-44).
        if "role" in session:
            if time.time() - session.get("last_seen", 0) > lifetime:
                session.clear()
                flash("Your session expired. Please log in again.", "info")
                if request.endpoint not in ("auth.login", "static"):
                    return redirect(url_for("auth.login", next=request.path))
            else:
                session["last_seen"] = int(time.time())

        if request.method == "POST" and not app.config.get("WTF_CSRF_DISABLED"):
            sent = request.form.get("csrf_token", "")
            if not sent or not hmac.compare_digest(sent, session.get("csrf", "")):
                flash("The form expired. Please try again.", "error")
                back = request.referrer or ""
                return redirect(back if back.startswith(request.host_url) else url_for("auth.login"))

    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        return resp

    @app.context_processor
    def inject_user():
        return {"user_role": current_role(), "user_name": session.get("name")}
