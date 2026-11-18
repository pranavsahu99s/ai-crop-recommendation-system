"""CropAdvisor: AI-based crop recommendation system for farmers (BCS 522)."""
import json
import logging
import sqlite3
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

from flask import Flask, render_template

from . import db as database
from .security import init_security
from .turso import TursoUnavailable
from .services.recommender import retrain


def create_app(config_object="config.Config", **overrides):
    app = Flask(__name__, instance_relative_config=False)
    app.config.from_object(config_object)
    app.config.update(overrides)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    database.init_app(app)
    init_security(app)

    from .auth import bp as auth_bp
    from .farmer import bp as farmer_bp
    from .admin import bp as admin_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(farmer_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")

    _register_template_helpers(app)
    _register_error_handlers(app)

    with app.app_context():
        database.init_db()
        retrain(database.get_db())
    return app


def _register_template_helpers(app):
    @app.template_filter("pct")
    def pct(value):
        return f"{value * 100:.0f}%" if value is not None else "—"

    @app.template_filter("datefmt")
    def datefmt(value, fmt="%d %b %Y, %H:%M"):
        if not value:
            return "—"
        try:
            # SQLite stores UTC; farmers read Indian Standard Time.
            return datetime.fromisoformat(value).replace(tzinfo=timezone.utc).astimezone(IST).strftime(fmt)
        except ValueError:
            return value

    @app.template_filter("fromjson")
    def fromjson(value):
        try:
            return json.loads(value or "{}")
        except ValueError:
            return {}

    @app.template_filter("num")
    def num(value):
        return "—" if value is None else f"{value:g}"


def _register_error_handlers(app):
    log = logging.getLogger("cropadvisor")

    @app.errorhandler(403)
    def forbidden(_e):
        return render_template("errors/error.html", code=403, title="Access denied",
                               message="Your account does not have permission to open this page."), 403

    @app.errorhandler(404)
    def not_found(_e):
        return render_template("errors/error.html", code=404, title="Page not found",
                               message="The page or record you asked for does not exist."), 404

    @app.errorhandler(413)
    def too_large(_e):
        return render_template("errors/error.html", code=413, title="File too large",
                               message="Soil reports must be smaller than 512 KB."), 413

    @app.errorhandler(database.DatabaseUnavailable)
    @app.errorhandler(TursoUnavailable)
    @app.errorhandler(sqlite3.OperationalError)
    def db_down(exc):
        log.error("Database error: %s", type(exc).__name__)
        return render_template("errors/error.html", code=503, title="Service temporarily unavailable",
                               message="The database could not be reached. Nothing was changed; "
                                       "please try again in a moment."), 503
