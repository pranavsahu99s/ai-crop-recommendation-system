"""Administrator use cases: manage users, crop data, soil data; view system reports."""
import re
import sqlite3

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for

from .db import get_db, log_activity
from .domain import clean_place, parse_number
from .seed import SEASONS
from .security import admin_required
from .services.recommender import model, retrain

bp = Blueprint("admin", __name__)


def _actor():
    return f"admin:{session.get('name')}"


# -- system reports -----------------------------------------------------------

@bp.route("/")
@admin_required
def overview():
    db = get_db()
    one = lambda sql, *a: db.execute(sql, a).fetchone()[0]  # noqa: E731
    stats = {
        "farmers": one("SELECT COUNT(*) FROM farmers"),
        "active_farmers": one("SELECT COUNT(*) FROM farmers WHERE status = 'active'"),
        "plots": one("SELECT COUNT(*) FROM farm_details"),
        "recommendations": one("SELECT COUNT(*) FROM recommendations"),
        "low_confidence": one("SELECT COUNT(*) FROM recommendations WHERE status = 'low-confidence'"),
        "crops": one("SELECT COUNT(*) FROM crops WHERE is_active = 1"),
        "soils": one("SELECT COUNT(*) FROM soil_types"),
        "weather_live": one("SELECT COUNT(DISTINCT r.weather_id) FROM recommendations r JOIN weather_data w"
                            " ON w.weather_id = r.weather_id WHERE w.source = 'open-meteo'"),
        "weather_estimate": one("SELECT COUNT(*) FROM recommendations r JOIN weather_data w"
                                " ON w.weather_id = r.weather_id WHERE w.source != 'open-meteo'"),
    }
    top_crops = db.execute(
        """SELECT c.crop_name, COUNT(*) AS n FROM recommendation_crops rc JOIN crops c ON c.crop_id = rc.crop_id
            WHERE rc.rank_order = 1 GROUP BY c.crop_id ORDER BY n DESC, c.crop_name LIMIT 6""").fetchall()
    by_season = db.execute(
        """SELECT json_extract(input_snapshot, '$.season') AS season, COUNT(*) AS n
             FROM recommendations GROUP BY season ORDER BY n DESC""").fetchall()
    activity = db.execute("SELECT * FROM activity_log ORDER BY log_id DESC LIMIT 15").fetchall()
    return render_template("admin/overview.html", stats=stats, top_crops=top_crops, by_season=by_season,
                           activity=activity, model_info=model.describe())


@bp.route("/model/retrain", methods=["POST"])
@admin_required
def retrain_model():
    db = get_db()
    retrain(db)
    log_activity(_actor(), "retrain model", model.model_version)
    db.commit()
    flash(f"Model retrained ({model.model_version}).", "success")
    return redirect(url_for("admin.overview"))


# -- users ----------------------------------------------------------------------

@bp.route("/users")
@admin_required
def users():
    q = (request.args.get("q") or "").strip()
    sql = """SELECT f.*, (SELECT COUNT(*) FROM farm_details d WHERE d.farmer_id = f.farmer_id) AS plots,
                    (SELECT COUNT(*) FROM recommendations r WHERE r.farmer_id = f.farmer_id) AS recs
               FROM farmers f"""
    args = ()
    if q:
        sql += " WHERE f.name LIKE ? OR f.contact_no LIKE ? OR f.location LIKE ?"
        args = (f"%{q}%",) * 3
    rows = get_db().execute(sql + " ORDER BY f.created_at DESC, f.farmer_id DESC", args).fetchall()
    return render_template("admin/users.html", rows=rows, q=q)


@bp.route("/users/<int:farmer_id>", methods=["GET", "POST"])
@admin_required
def user_edit(farmer_id):
    db = get_db()
    farmer = db.execute("SELECT * FROM farmers WHERE farmer_id = ?", (farmer_id,)).fetchone()
    if farmer is None:
        abort(404)
    errors = {}
    form = dict(farmer)
    if request.method == "POST":
        form = request.form.to_dict()
        name = " ".join((form.get("name") or "").split())
        location, err = clean_place(form.get("location"), "Location")
        contact = re.sub(r"[\s-]", "", form.get("contact_no") or "")
        status = form.get("status")
        if not name:
            errors["name"] = "Name is required."
        if err:
            errors["location"] = err
        if not re.fullmatch(r"[6-9]\d{9}", contact):
            errors["contact_no"] = "Enter a 10-digit mobile number."
        if status not in ("active", "disabled"):
            errors["status"] = "Choose a status."
        if not errors:
            try:
                db.execute("UPDATE farmers SET name = ?, location = ?, contact_no = ?, status = ? WHERE farmer_id = ?",
                           (name, location, contact, status, farmer_id))
                log_activity(_actor(), "update user", f"farmer #{farmer_id} ({status})")
                db.commit()
            except sqlite3.IntegrityError:
                errors["contact_no"] = "Another farmer already uses this contact number."
            else:
                flash("User account updated.", "success")
                return redirect(url_for("admin.users"))
    plots = db.execute("SELECT COUNT(*) FROM farm_details WHERE farmer_id = ?", (farmer_id,)).fetchone()[0]
    recs = db.execute("SELECT COUNT(*) FROM recommendations WHERE farmer_id = ?", (farmer_id,)).fetchone()[0]
    return render_template("admin/user_form.html", farmer=farmer, form=form, errors=errors, plots=plots, recs=recs)


@bp.route("/users/<int:farmer_id>/delete", methods=["POST"])
@admin_required
def user_delete(farmer_id):
    db = get_db()
    farmer = db.execute("SELECT name FROM farmers WHERE farmer_id = ?", (farmer_id,)).fetchone()
    if farmer is None:
        abort(404)
    # Farm details and recommendations are removed by ON DELETE CASCADE (TC-52).
    db.execute("DELETE FROM farmers WHERE farmer_id = ?", (farmer_id,))
    log_activity(_actor(), "delete user", f"farmer #{farmer_id} {farmer['name']}")
    db.commit()
    flash(f"{farmer['name']} and their farm records were deleted.", "info")
    return redirect(url_for("admin.users"))


# -- crop data --------------------------------------------------------------------

CROP_NUMERIC = [
    # field, label, low, high, required, default
    ("optimal_temp", "Optimal temperature (°C)", -5, 50, True, None),
    ("min_rainfall", "Minimum rainfall (mm/month)", 0, 1000, True, None),
    ("temp_tolerance", "Temperature tolerance (± °C)", 1, 20, False, 6),
    ("max_rainfall", "Maximum rainfall (mm/month)", 0, 1500, False, None),
    ("humidity_min", "Humidity from (%)", 0, 100, False, 30),
    ("humidity_max", "Humidity to (%)", 0, 100, False, 85),
    ("n_min", "N from", 0, 300, False, 20), ("n_max", "N to", 0, 300, False, 120),
    ("p_min", "P from", 0, 300, False, 15), ("p_max", "P to", 0, 300, False, 80),
    ("k_min", "K from", 0, 300, False, 15), ("k_max", "K to", 0, 300, False, 80),
    ("ph_min", "pH from", 0, 14, False, 5.5), ("ph_max", "pH to", 0, 14, False, 7.8),
    ("duration_days", "Duration (days)", 20, 400, False, None),
]
CATEGORIES = ("Cereal", "Millet", "Pulse", "Oilseed", "Fibre", "Cash crop", "Vegetable", "Fruit", "Other")
WATER = ("Low", "Medium", "High")


def _validate_crop(form, soil_names):
    errors, data = {}, {}
    data["crop_name"] = " ".join((form.get("crop_name") or "").split())
    if not data["crop_name"]:
        errors["crop_name"] = "Crop name is required."
    elif not re.fullmatch(r"[\w .,'()\-]{2,60}", data["crop_name"]):
        errors["crop_name"] = "Use letters, numbers, spaces and brackets only."
    soils = [s for s in form.getlist("soil_category") if s in soil_names]
    if not soils:
        errors["soil_category"] = "Select at least one suitable soil type."
    data["soil_category"] = ",".join(soils)
    seasons = [s for s in form.getlist("seasons") if s in SEASONS]
    if not seasons:
        errors["seasons"] = "Select at least one season."
    data["seasons"] = ",".join(seasons)
    data["category"] = form.get("category") if form.get("category") in CATEGORIES else "Other"
    data["water_need"] = form.get("water_need") if form.get("water_need") in WATER else "Medium"
    data["guidance"] = (form.get("guidance") or "").strip()[:600] or None
    for field, label, low, high, required, default in CROP_NUMERIC:
        value, err = parse_number(form.get(field), label, low, high, required)
        if err:
            errors[field] = err
        data[field] = value if value is not None else default
    if data["max_rainfall"] is None and data["min_rainfall"] is not None:
        data["max_rainfall"] = data["min_rainfall"] + 150
    for lo, hi in (("humidity_min", "humidity_max"), ("n_min", "n_max"), ("p_min", "p_max"),
                   ("k_min", "k_max"), ("ph_min", "ph_max"), ("min_rainfall", "max_rainfall")):
        if data.get(lo) is not None and data.get(hi) is not None and data[lo] > data[hi] and hi not in errors:
            errors[hi] = "Must be greater than or equal to the lower value."
    if data["duration_days"] is not None:
        data["duration_days"] = int(data["duration_days"])
    return data, errors


@bp.route("/crops")
@admin_required
def crops():
    rows = get_db().execute(
        """SELECT c.*, (SELECT COUNT(*) FROM recommendation_crops rc WHERE rc.crop_id = c.crop_id) AS used
             FROM crops c ORDER BY c.is_active DESC, c.crop_name""").fetchall()
    return render_template("admin/crops.html", rows=rows)


def _crop_form(crop=None):
    db = get_db()
    soil_names = [r["name"] for r in db.execute("SELECT name FROM soil_types ORDER BY name")]
    errors = {}
    if request.method == "POST":
        data, errors = _validate_crop(request.form, set(soil_names))
        # Re-show what was typed, so a rejected value can be corrected in place.
        form = request.form.to_dict() | {"soil_list": data["soil_category"].split(","),
                                         "season_list": data["seasons"].split(",")}
        if not errors:
            cols = ["crop_name", "soil_category", "seasons", "category", "water_need", "guidance"] + \
                   [f[0] for f in CROP_NUMERIC]
            try:
                if crop is None:
                    db.execute(f"INSERT INTO crops ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                               [data[c] for c in cols])
                    action = "add crop"
                else:
                    db.execute(f"UPDATE crops SET {', '.join(c + ' = ?' for c in cols)} WHERE crop_id = ?",
                               [data[c] for c in cols] + [crop["crop_id"]])
                    action = "update crop"
                log_activity(_actor(), action, data["crop_name"])
                db.commit()
            except sqlite3.IntegrityError:
                errors["crop_name"] = "A crop with this name already exists."
            else:
                retrain(db)
                flash(f"{data['crop_name']} saved. The model was retrained with the updated crop data.", "success")
                return redirect(url_for("admin.crops"))
    elif crop is not None:
        form = dict(crop) | {"soil_list": crop["soil_category"].split(","), "season_list": crop["seasons"].split(",")}
    else:
        form = {"soil_list": [], "season_list": [], "temp_tolerance": 6, "humidity_min": 30, "humidity_max": 85,
                "n_min": 20, "n_max": 120, "p_min": 15, "p_max": 80, "k_min": 15, "k_max": 80,
                "ph_min": 5.5, "ph_max": 7.8, "water_need": "Medium", "category": "Other"}
    return render_template("admin/crop_form.html", crop=crop, form=form, errors=errors, soil_names=soil_names,
                           seasons=SEASONS, categories=CATEGORIES, water=WATER, numeric=CROP_NUMERIC)


@bp.route("/crops/new", methods=["GET", "POST"])
@admin_required
def crop_new():
    return _crop_form()


@bp.route("/crops/<int:crop_id>", methods=["GET", "POST"])
@admin_required
def crop_edit(crop_id):
    crop = get_db().execute("SELECT * FROM crops WHERE crop_id = ?", (crop_id,)).fetchone()
    if crop is None:
        abort(404)
    return _crop_form(crop)


@bp.route("/crops/<int:crop_id>/delete", methods=["POST"])
@admin_required
def crop_delete(crop_id):
    db = get_db()
    crop = db.execute("SELECT crop_name FROM crops WHERE crop_id = ?", (crop_id,)).fetchone()
    if crop is None:
        abort(404)
    try:
        db.execute("DELETE FROM crops WHERE crop_id = ?", (crop_id,))
        log_activity(_actor(), "delete crop", crop["crop_name"])
        db.commit()
    except sqlite3.IntegrityError:
        # Referenced by saved recommendations (ON DELETE RESTRICT), keep history consistent (TC-35).
        db.rollback()
        flash(f"{crop['crop_name']} appears in saved recommendations, so it cannot be deleted. "
              "Deactivate it instead to stop recommending it.", "warning")
        return redirect(url_for("admin.crops"))
    retrain(db)
    flash(f"{crop['crop_name']} deleted.", "info")
    return redirect(url_for("admin.crops"))


@bp.route("/crops/<int:crop_id>/toggle", methods=["POST"])
@admin_required
def crop_toggle(crop_id):
    db = get_db()
    crop = db.execute("SELECT crop_name, is_active FROM crops WHERE crop_id = ?", (crop_id,)).fetchone()
    if crop is None:
        abort(404)
    db.execute("UPDATE crops SET is_active = ? WHERE crop_id = ?", (0 if crop["is_active"] else 1, crop_id))
    log_activity(_actor(), "deactivate crop" if crop["is_active"] else "activate crop", crop["crop_name"])
    db.commit()
    retrain(db)
    flash(f"{crop['crop_name']} {'deactivated' if crop['is_active'] else 'activated'}.", "info")
    return redirect(url_for("admin.crops"))


# -- soil data --------------------------------------------------------------------

SOIL_FIELDS = [("typical_n", "Typical N", 0, 300), ("typical_p", "Typical P", 0, 300),
               ("typical_k", "Typical K", 0, 300), ("typical_ph", "Typical pH", 0, 14)]
DRAINAGE = ("Poor", "Moderate", "Good", "Very good")


@bp.route("/soils")
@admin_required
def soils():
    rows = get_db().execute(
        """SELECT s.*, (SELECT COUNT(*) FROM farm_details d WHERE d.soil_type = s.name) AS plots
             FROM soil_types s ORDER BY s.name""").fetchall()
    return render_template("admin/soils.html", rows=rows)


def _soil_form(soil=None):
    db = get_db()
    errors = {}
    form = dict(soil) if soil else {"drainage": "Moderate"}
    if request.method == "POST":
        form = request.form.to_dict()
        name = " ".join((form.get("name") or "").split())
        if not re.fullmatch(r"[A-Za-z][A-Za-z \-]{1,39}", name):
            errors["name"] = "Use letters, spaces and hyphens only."
        values = {}
        for field, label, low, high in SOIL_FIELDS:
            values[field], err = parse_number(form.get(field), label, low, high)
            if err:
                errors[field] = err
        drainage = form.get("drainage") if form.get("drainage") in DRAINAGE else "Moderate"
        description = (form.get("description") or "").strip()[:300] or None
        if not errors:
            try:
                if soil is None:
                    db.execute("INSERT INTO soil_types (name, description, typical_n, typical_p, typical_k,"
                               " typical_ph, drainage) VALUES (?, ?, ?, ?, ?, ?, ?)",
                               (name, description, *values.values(), drainage))
                else:
                    db.execute("UPDATE soil_types SET name = ?, description = ?, typical_n = ?, typical_p = ?,"
                               " typical_k = ?, typical_ph = ?, drainage = ? WHERE soil_id = ?",
                               (name, description, *values.values(), drainage, soil["soil_id"]))
                    if name != soil["name"]:
                        db.execute("UPDATE farm_details SET soil_type = ? WHERE soil_type = ?", (name, soil["name"]))
                        for c in db.execute("SELECT crop_id, soil_category FROM crops").fetchall():
                            parts = [name if s == soil["name"] else s for s in c["soil_category"].split(",")]
                            db.execute("UPDATE crops SET soil_category = ? WHERE crop_id = ?",
                                       (",".join(parts), c["crop_id"]))
                log_activity(_actor(), "save soil type", name)
                db.commit()
            except sqlite3.IntegrityError:
                errors["name"] = "A soil type with this name already exists."
            else:
                retrain(db)
                flash(f"Soil type {name} saved.", "success")
                return redirect(url_for("admin.soils"))
    return render_template("admin/soil_form.html", soil=soil, form=form, errors=errors,
                           fields=SOIL_FIELDS, drainage=DRAINAGE)


@bp.route("/soils/new", methods=["GET", "POST"])
@admin_required
def soil_new():
    return _soil_form()


@bp.route("/soils/<int:soil_id>", methods=["GET", "POST"])
@admin_required
def soil_edit(soil_id):
    soil = get_db().execute("SELECT * FROM soil_types WHERE soil_id = ?", (soil_id,)).fetchone()
    if soil is None:
        abort(404)
    return _soil_form(soil)


@bp.route("/soils/<int:soil_id>/delete", methods=["POST"])
@admin_required
def soil_delete(soil_id):
    db = get_db()
    soil = db.execute("SELECT name FROM soil_types WHERE soil_id = ?", (soil_id,)).fetchone()
    if soil is None:
        abort(404)
    in_use = db.execute("SELECT COUNT(*) FROM farm_details WHERE soil_type = ?", (soil["name"],)).fetchone()[0]
    if in_use:
        flash(f"{soil['name']} is used by {in_use} farm plot(s) and cannot be deleted.", "warning")
        return redirect(url_for("admin.soils"))
    db.execute("DELETE FROM soil_types WHERE soil_id = ?", (soil_id,))
    log_activity(_actor(), "delete soil type", soil["name"])
    db.commit()
    retrain(db)
    flash(f"Soil type {soil['name']} deleted.", "info")
    return redirect(url_for("admin.soils"))
