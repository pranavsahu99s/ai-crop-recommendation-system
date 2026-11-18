"""SQLite access: one connection per request, schema creation and seeding."""
import os
import sqlite3

import click
from flask import current_app, g
from werkzeug.security import generate_password_hash

from .seed import CROPS, SOIL_TYPES, DEMO_ADMIN, DEMO_FARMER


class DatabaseUnavailable(Exception):
    """Raised when the database cannot be opened (TC-47)."""


def get_db():
    if "db" not in g:
        path = current_app.config["DATABASE"]
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            conn = sqlite3.connect(path, timeout=5)
            conn.execute("PRAGMA foreign_keys = ON")
        except (sqlite3.Error, OSError) as exc:
            raise DatabaseUnavailable(str(exc)) from exc
        conn.row_factory = sqlite3.Row
        g.db = conn
    return g.db


def close_db(_exc=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def log_activity(actor, action, detail=None):
    db = get_db()
    db.execute("INSERT INTO activity_log (actor, action, detail) VALUES (?, ?, ?)", (actor, action, detail))


def init_db(seed=True):
    db = get_db()
    with current_app.open_resource("schema.sql") as fh:
        db.executescript(fh.read().decode("utf-8"))
    if seed:
        seed_db(db)
    db.commit()


def seed_db(db):
    if db.execute("SELECT COUNT(*) FROM soil_types").fetchone()[0] == 0:
        db.executemany(
            "INSERT INTO soil_types (name, description, typical_n, typical_p, typical_k, typical_ph, drainage)"
            " VALUES (:name, :description, :n, :p, :k, :ph, :drainage)",
            SOIL_TYPES,
        )
    if db.execute("SELECT COUNT(*) FROM crops").fetchone()[0] == 0:
        db.executemany(
            """INSERT INTO crops (crop_name, category, seasons, soil_category, optimal_temp, temp_tolerance,
                   min_rainfall, max_rainfall, humidity_min, humidity_max, n_min, n_max, p_min, p_max,
                   k_min, k_max, ph_min, ph_max, water_need, duration_days, guidance)
               VALUES (:name, :category, :seasons, :soils, :temp, :tol, :rain_min, :rain_max, :hum_min,
                   :hum_max, :n_min, :n_max, :p_min, :p_max, :k_min, :k_max, :ph_min, :ph_max,
                   :water, :days, :guidance)""",
            CROPS,
        )
    if db.execute("SELECT COUNT(*) FROM admins").fetchone()[0] == 0:
        db.execute(
            "INSERT INTO admins (username, name, password_hash) VALUES (?, ?, ?)",
            (DEMO_ADMIN["username"], DEMO_ADMIN["name"], generate_password_hash(DEMO_ADMIN["password"])),
        )
    if db.execute("SELECT COUNT(*) FROM farmers").fetchone()[0] == 0:
        db.execute(
            "INSERT INTO farmers (name, location, contact_no, password_hash) VALUES (?, ?, ?, ?)",
            (DEMO_FARMER["name"], DEMO_FARMER["location"], DEMO_FARMER["contact_no"],
             generate_password_hash(DEMO_FARMER["password"])),
        )


@click.command("init-db")
@click.option("--reset", is_flag=True, help="Delete the existing database first.")
def init_db_command(reset):
    """Create tables and load reference data."""
    path = current_app.config["DATABASE"]
    if reset and os.path.exists(path):
        close_db()
        os.remove(path)
    init_db()
    click.echo(f"Database ready at {path}")


def init_app(app):
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
