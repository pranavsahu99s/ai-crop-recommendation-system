"""Farmer use cases: profile, farm details, recommendations, history and download."""
from flask import (Blueprint, Response, abort, flash, redirect, render_template, request, session,
                   url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from .db import get_db, log_activity
from .domain import FarmDetails, clean_place
from .seed import SEASON_INFO, SEASONS
from .security import farmer_required
from .services.advisory import IncompleteInput, generate_recommendation, load_recommendation
from .services.recommender import ModelUnavailable
from .services.report import build_pdf
from .services.soil_report import SoilReportError, parse_soil_report
from .services.weather import WeatherError

bp = Blueprint("farmer", __name__)


def _uid():
    return session["uid"]


def _soil_types():
    return get_db().execute("SELECT * FROM soil_types ORDER BY name").fetchall()


def _get_plot(plot_no):
    """Load a plot owned by the current farmer; other farmers' plots are 404 (TC-45)."""
    row = get_db().execute("SELECT * FROM farm_details WHERE farmer_id = ? AND plot_no = ?",
                           (_uid(), plot_no)).fetchone()
    if row is None:
        abort(404)
    return FarmDetails.from_row(row)


@bp.route("/dashboard")
@farmer_required
def dashboard():
    db = get_db()
    farmer = db.execute("SELECT * FROM farmers WHERE farmer_id = ?", (_uid(),)).fetchone()
    plots = [FarmDetails.from_row(r) for r in db.execute(
        "SELECT * FROM farm_details WHERE farmer_id = ? ORDER BY plot_no", (_uid(),))]
    recent = db.execute(
        """SELECT r.rec_id, r.generated_date, r.confidence_score, r.status, r.input_snapshot,
                  c.crop_name, rc.suitability_score
             FROM recommendations r
             JOIN recommendation_crops rc ON rc.rec_id = r.rec_id AND rc.rank_order = 1
             JOIN crops c ON c.crop_id = rc.crop_id
            WHERE r.farmer_id = ? ORDER BY r.generated_date DESC, r.rec_id DESC LIMIT 5""", (_uid(),)).fetchall()
    total = db.execute("SELECT COUNT(*) FROM recommendations WHERE farmer_id = ?", (_uid(),)).fetchone()[0]
    return render_template("farmer/dashboard.html", farmer=farmer, plots=plots, recent=recent, total=total)


# -- profile ---------------------------------------------------------------

@bp.route("/profile", methods=["GET", "POST"])
@farmer_required
def profile():
    db = get_db()
    farmer = db.execute("SELECT * FROM farmers WHERE farmer_id = ?", (_uid(),)).fetchone()
    errors = {}
    if request.method == "POST":
        name = " ".join((request.form.get("name") or "").split())
        location, loc_err = clean_place(request.form.get("location"), "Village / district")
        if not name:
            errors["name"] = "Name is required."
        if loc_err:
            errors["location"] = loc_err
        new_pw = request.form.get("new_password") or ""
        if new_pw:
            if not check_password_hash(farmer["password_hash"], request.form.get("current_password") or ""):
                errors["current_password"] = "Current password is incorrect."
            elif len(new_pw) < 6:
                errors["new_password"] = "New password must be at least 6 characters."
        if not errors:
            db.execute("UPDATE farmers SET name = ?, location = ? WHERE farmer_id = ?", (name, location, _uid()))
            if new_pw:
                db.execute("UPDATE farmers SET password_hash = ? WHERE farmer_id = ?",
                           (generate_password_hash(new_pw), _uid()))
            db.commit()
            session["name"] = name
            flash("Profile updated.", "success")
            return redirect(url_for("farmer.profile"))
    return render_template("farmer/profile.html", farmer=farmer, errors=errors, form=request.form)


# -- farm details ------------------------------------------------------------

@bp.route("/farms")
@farmer_required
def farms():
    plots = [FarmDetails.from_row(r) for r in get_db().execute(
        "SELECT * FROM farm_details WHERE farmer_id = ? ORDER BY plot_no", (_uid(),))]
    return render_template("farmer/farms.html", plots=plots)


def _farm_form(plot=None):
    soils = _soil_types()
    soil_names = {s["name"] for s in soils}
    errors = {}
    if request.method == "POST":
        form = request.form.to_dict()
        upload = request.files.get("soil_report")
        report_values = None
        if upload and upload.filename:
            try:
                report_values = parse_soil_report(upload.filename, upload.read())
                for key, value in report_values.items():
                    form[key] = f"{value:g}"
            except SoilReportError as exc:
                errors["soil_report"] = str(exc)
        data, field_errors = FarmDetails.validate_inputs(form, soil_names)
        errors.update(field_errors)
        if not errors:
            db = get_db()
            if plot is None:
                plot_no = db.execute("SELECT COALESCE(MAX(plot_no), 0) + 1 FROM farm_details WHERE farmer_id = ?",
                                     (_uid(),)).fetchone()[0]
                db.execute(
                    "INSERT INTO farm_details (farmer_id, plot_no, plot_name, location, land_area, season,"
                    " soil_type, n, p, k, ph) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (_uid(), plot_no, data["plot_name"], data["location"], data["land_area"], data["season"],
                     data["soil_type"], data["n"], data["p"], data["k"], data["ph"]))
            else:
                plot_no = plot.plot_no
                db.execute(
                    "UPDATE farm_details SET plot_name = ?, location = ?, land_area = ?, season = ?, soil_type = ?,"
                    " n = ?, p = ?, k = ?, ph = ?, updated_at = datetime('now')"
                    " WHERE farmer_id = ? AND plot_no = ?",
                    (data["plot_name"], data["location"], data["land_area"], data["season"], data["soil_type"],
                     data["n"], data["p"], data["k"], data["ph"], _uid(), plot_no))
            db.commit()
            msg = "Farm details saved."
            if report_values:
                msg += " Values from the soil report were applied."
            flash(msg, "success")
            return redirect(url_for("farmer.farm_detail", plot_no=plot_no))
    else:
        if plot:
            form = {k: ("" if v is None else (f"{v:g}" if isinstance(v, float) else v))
                    for k, v in plot.__dict__.items()}
        else:
            home = get_db().execute("SELECT location FROM farmers WHERE farmer_id = ?", (_uid(),)).fetchone()
            form = {"location": home["location"]}
    soil_map = {s["name"]: {"n": s["typical_n"], "p": s["typical_p"], "k": s["typical_k"], "ph": s["typical_ph"]}
                for s in soils}
    return render_template("farmer/farm_form.html", form=form, errors=errors, plot=plot, soils=soils,
                           soil_map=soil_map, seasons=SEASONS, season_info=SEASON_INFO)


@bp.route("/farms/new", methods=["GET", "POST"])
@farmer_required
def farm_new():
    return _farm_form()


@bp.route("/farms/<int:plot_no>/edit", methods=["GET", "POST"])
@farmer_required
def farm_edit(plot_no):
    return _farm_form(_get_plot(plot_no))


@bp.route("/farms/<int:plot_no>")
@farmer_required
def farm_detail(plot_no):
    plot = _get_plot(plot_no)
    soil = get_db().execute("SELECT * FROM soil_types WHERE name = ?", (plot.soil_type,)).fetchone()
    history = get_db().execute(
        """SELECT r.rec_id, r.generated_date, r.status, c.crop_name, rc.suitability_score
             FROM recommendations r
             JOIN recommendation_crops rc ON rc.rec_id = r.rec_id AND rc.rank_order = 1
             JOIN crops c ON c.crop_id = rc.crop_id
            WHERE r.farmer_id = ? AND r.plot_no = ? ORDER BY r.rec_id DESC LIMIT 5""",
        (_uid(), plot_no)).fetchall()
    return render_template("farmer/farm_detail.html", plot=plot, soil=soil, history=history,
                           missing=plot.missing_for_recommendation(), season_info=SEASON_INFO)


@bp.route("/farms/<int:plot_no>/delete", methods=["POST"])
@farmer_required
def farm_delete(plot_no):
    _get_plot(plot_no)
    db = get_db()
    db.execute("DELETE FROM farm_details WHERE farmer_id = ? AND plot_no = ?", (_uid(), plot_no))
    db.commit()
    flash("Plot removed. Earlier recommendations for it are kept in your history.", "info")
    return redirect(url_for("farmer.farms"))


# -- recommendations ----------------------------------------------------------

@bp.route("/farms/<int:plot_no>/recommend", methods=["POST"])
@farmer_required
def request_recommendation(plot_no):
    plot = _get_plot(plot_no)
    db = get_db()
    try:
        rec_id, notice = generate_recommendation(db, _uid(), plot)
    except IncompleteInput as exc:
        flash("Some details are still needed before a recommendation can be made: "
              + ", ".join(exc.missing) + ".", "warning")
        return redirect(url_for("farmer.farm_edit", plot_no=plot_no))
    except WeatherError as exc:
        db.rollback()
        flash(exc.message, "error")
        return redirect(url_for("farmer.farm_edit", plot_no=plot_no))
    except ModelUnavailable:
        db.rollback()
        flash("The recommendation service is unavailable at the moment. No result was produced; "
              "please try again later.", "error")
        return redirect(url_for("farmer.farm_detail", plot_no=plot_no))
    log_activity(session["name"], "recommendation", f"rec #{rec_id}")
    db.commit()
    if notice:
        flash(notice, "warning")
    return redirect(url_for("farmer.recommendation", rec_id=rec_id))


def _owned_recommendation(rec_id):
    data = load_recommendation(get_db(), rec_id)
    if data is None or data["rec"].farmer_id != _uid():
        abort(404)
    return data


@bp.route("/recommendations")
@farmer_required
def history():
    rows = get_db().execute(
        """SELECT r.rec_id, r.generated_date, r.confidence_score, r.status, r.input_snapshot,
                  GROUP_CONCAT(c.crop_name, ', ') AS crops
             FROM recommendations r
             JOIN (SELECT rc.rec_id, c.crop_name FROM recommendation_crops rc
                     JOIN crops c ON c.crop_id = rc.crop_id ORDER BY rc.rank_order) c ON c.rec_id = r.rec_id
            WHERE r.farmer_id = ?
            GROUP BY r.rec_id ORDER BY r.generated_date DESC, r.rec_id DESC""", (_uid(),)).fetchall()
    return render_template("farmer/history.html", rows=rows)


@bp.route("/recommendations/<int:rec_id>")
@farmer_required
def recommendation(rec_id):
    data = _owned_recommendation(rec_id)
    top = data["rec"].top
    checks = top["crop"].check_suitability(data["inputs"], data["weather"].__dict__) if top else []
    return render_template("farmer/recommendation.html", checks=checks, **data)


@bp.route("/recommendations/<int:rec_id>/download")
@farmer_required
def download(rec_id):
    data = _owned_recommendation(rec_id)
    pdf = build_pdf(data)
    return Response(pdf, mimetype="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="crop-recommendation-{rec_id}.pdf"'})
