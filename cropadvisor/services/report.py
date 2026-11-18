"""Builds the downloadable recommendation report (use case: Download Recommendation)."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .pdf import PdfDocument


def _fmt_date(value):
    try:
        stamp = datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
        return stamp.astimezone(ZoneInfo("Asia/Kolkata")).strftime("%d %b %Y, %H:%M IST")
    except (TypeError, ValueError):
        return value or "-"


def build_pdf(data):
    rec, weather, inputs, farmer = data["rec"], data["weather"], data["inputs"], data["farmer"]
    doc = PdfDocument(title=f"Crop recommendation #{rec.rec_id}")
    m = doc.margin
    usable = doc.width - 2 * m

    doc.rect(0, doc.height - 6, doc.width, 6, fill="#2f5d3a")
    doc.y -= 4
    doc.text(m, doc.y, "CropAdvisor", 11, bold=True, color="#2f5d3a")
    doc.text(doc.width - m - 130, doc.y, f"Report #{rec.rec_id}", 9, color="#5d665a")
    doc.y -= 26
    doc.text(m, doc.y, "Crop recommendation report", 20, bold=True)
    doc.y -= 18
    doc.text(m, doc.y, f"Prepared for {farmer['name']} ({farmer['contact_no']})  |  {_fmt_date(rec.generated_date)}",
             9, color="#5d665a")
    doc.y -= 14

    top = rec.top
    if top:
        box_h = 62
        doc.y -= 6
        doc.rect(m, doc.y - box_h, usable, box_h, fill="#eef2ea")
        doc.text(m + 14, doc.y - 20, "Recommended crop", 9, color="#5d665a")
        doc.text(m + 14, doc.y - 44, top["crop"].crop_name, 20, bold=True, color="#2f5d3a")
        doc.text(m + usable - 150, doc.y - 20, "Confidence", 9, color="#5d665a")
        doc.text(m + usable - 150, doc.y - 44, f"{rec.confidence_score * 100:.0f}%", 20, bold=True)
        doc.y -= box_h + 8
    if rec.is_low_confidence:
        doc.paragraph("Low confidence: the inputs do not clearly match any crop in the knowledge base. "
                      "Treat this as a starting point and confirm with your local Krishi Vigyan Kendra.",
                      size=9, color="#8a4b0f")
    if weather.source != "open-meteo":
        doc.paragraph("Weather values are typical season estimates because the weather service could "
                      "not be reached when this report was generated.", size=9, color="#8a4b0f")

    doc.heading("Ranked crops")
    doc.table(["Rank", "Crop", "Category", "Water need", "Suitability"],
              [[c["rank_order"], c["crop"].crop_name, c["crop"].category, c["crop"].water_need,
                f"{c['suitability_score'] * 100:.0f}%"] for c in rec.crops],
              [44, 170, 110, 90, usable - 414])

    doc.heading("Farm and soil inputs")
    doc.table(["Field", "Value"], [
        ["Plot", inputs.get("plot_name") or "-"],
        ["Location", inputs["location"]],
        ["Land area", f"{inputs['land_area']:g} acres"],
        ["Season", inputs["season"]],
        ["Soil type", inputs["soil_type"]],
        ["N : P : K (kg/ha)", f"{inputs['n']:g} : {inputs['p']:g} : {inputs['k']:g}"],
        ["Soil pH", f"{inputs['ph']:g}"],
    ], [160, usable - 160])

    doc.heading("Weather used")
    source = "Open-Meteo historical archive" if weather.source == "open-meteo" else "Seasonal estimate (not measured)"
    doc.table(["Field", "Value"], [
        ["Place", weather.location],
        ["Period", weather.period or "-"],
        ["Mean temperature", f"{weather.temperature:.1f} °C"],
        ["Mean monthly rainfall", f"{weather.rainfall:.0f} mm"],
        ["Mean relative humidity", f"{weather.humidity:.0f}%"],
        ["Source", source],
    ], [160, usable - 160])

    if top:
        crop = top["crop"]
        doc.heading(f"Growing notes: {crop.crop_name}")
        if crop.guidance:
            doc.paragraph(crop.guidance)
        facts = [f"Seasons: {', '.join(crop.season_list)}", f"Suitable soils: {', '.join(crop.soil_list)}",
                 f"Water need: {crop.water_need}"]
        if crop.duration_days:
            facts.append(f"Duration: about {crop.duration_days} days")
        doc.paragraph("  |  ".join(facts), size=9, color="#5d665a")

    doc.y -= 8
    doc.paragraph(f"Model: {data.get('model_version') or '-'}. Suitability is the model's estimated probability "
                  "that the crop fits these conditions, compared with the other crops in the knowledge base.",
                  size=8, color="#7a8276")
    return doc.output(footer="CropAdvisor - BCS 522 Software Engineering Lab, Amity University Rajasthan")
