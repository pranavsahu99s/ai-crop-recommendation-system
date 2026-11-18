"""Read N, P, K and pH from an uploaded soil report (.csv or .txt).

Accepted layouts, one value per line or as a two-row CSV:

    N,P,K,pH            Nitrogen: 82
    82,41,38,6.9        Phosphorus = 41
                        ...
"""
import csv
import io
import re

ALIASES = {
    "n": "n", "nitrogen": "n", "available nitrogen": "n",
    "p": "p", "phosphorus": "p", "phosphorous": "p", "available phosphorus": "p",
    "k": "k", "potassium": "k", "potash": "k", "available potassium": "k",
    "ph": "ph", "soil ph": "ph", "ph value": "ph",
}
ALLOWED_EXTENSIONS = {".csv", ".txt"}
_LINE_RE = re.compile(r"^\s*([A-Za-z ]+?)\s*(?:\(.*?\))?\s*[:=,\t]\s*([-+]?\d+(?:\.\d+)?)")


class SoilReportError(ValueError):
    pass


def _key(label):
    return ALIASES.get(re.sub(r"\s+", " ", label.strip().lower()))


def parse_soil_report(filename, raw):
    if not filename or "." not in filename or filename[filename.rfind("."):].lower() not in ALLOWED_EXTENSIONS:
        raise SoilReportError("Upload the soil report as a .csv or .txt file.")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise SoilReportError("The soil report must be a plain text or CSV file.") from None

    values = {}
    rows = [r for r in csv.reader(io.StringIO(text)) if any(c.strip() for c in r)]
    if len(rows) >= 2 and all(_key(c) for c in rows[0] if c.strip()):
        for label, cell in zip(rows[0], rows[1]):
            key = _key(label)
            try:
                values[key] = float(cell)
            except ValueError:
                pass
    else:
        for line in text.splitlines():
            m = _LINE_RE.match(line)
            if m and _key(m.group(1)):
                values[_key(m.group(1))] = float(m.group(2))

    if not values:
        raise SoilReportError("No N, P, K or pH values were found in the report.")
    return values
