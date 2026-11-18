"""Runs the main workflow through the Turso adapter.

FakeHrana answers /v2/pipeline requests the way Turso does, backed by an
in-memory SQLite database, so the hosted code path is tested offline.
"""
import sqlite3
import unittest
from unittest import mock

from cropadvisor import create_app
from cropadvisor.turso import TursoConnection, _decode, _encode
from tests.test_srs_cases import FARMER, PLOT, StubWeather


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload, self.status_code = payload, status

    def json(self):
        return self.payload


class FakeHrana:
    """Shared in-memory database standing in for the Turso server."""

    def __init__(self):
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        self.requests = 0
        self.headers = {}

    def __call__(self):            # used as requests.Session()
        return self

    def close(self):
        pass

    def post(self, url, json, timeout):
        assert url.endswith("/v2/pipeline")
        self.requests += 1
        results = []
        for req in json["requests"]:
            if req["type"] == "close":
                results.append({"type": "ok", "response": {"type": "close"}})
                continue
            try:
                if req["type"] == "sequence":
                    self.db.executescript(req["sql"])
                    results.append({"type": "ok", "response": {"type": "sequence"}})
                    continue
                stmt = req["stmt"]
                if "named_args" in stmt:
                    params = {a["name"].lstrip(":"): _decode(a["value"]) for a in stmt["named_args"]}
                else:
                    params = [_decode(a) for a in stmt.get("args", [])]
                cur = self.db.execute(stmt["sql"], params)
                rows = cur.fetchall()
                self.db.commit()
                results.append({"type": "ok", "response": {"type": "execute", "result": {
                    "cols": [{"name": d[0]} for d in (cur.description or [])],
                    "rows": [[_encode(v) for v in r] for r in rows],
                    "affected_row_count": max(cur.rowcount, 0),
                    "last_insert_rowid": str(cur.lastrowid) if cur.lastrowid else None,
                }}})
            except sqlite3.IntegrityError as exc:
                results.append({"type": "error", "error": {"message": str(exc), "code": "SQLITE_CONSTRAINT"}})
            except sqlite3.Error as exc:
                results.append({"type": "error", "error": {"message": str(exc), "code": "SQLITE_ERROR"}})
        return FakeResponse({"baton": None, "results": results})


class TursoAdapterTest(unittest.TestCase):
    def setUp(self):
        self.server = FakeHrana()
        patcher = mock.patch("cropadvisor.turso.requests.Session", self.server)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.app = create_app("config.TestConfig", TURSO_DATABASE_URL="libsql://demo-db.turso.io",
                              TURSO_AUTH_TOKEN="token", WEATHER_ENABLED=True, WTF_CSRF_DISABLED=True)
        self.app.extensions["weather_service"] = StubWeather()

    def test_full_workflow_over_turso(self):
        a, b = self.app.test_client(), self.app.test_client()
        a.post("/register", data=FARMER)
        a.post("/login", data={"role": "farmer", "identifier": FARMER["contact_no"], "password": FARMER["password"]})
        self.assertEqual(a.post("/farms/new", data=PLOT).status_code, 302)
        # The same data is visible on every request, whichever instance serves it.
        self.assertIn(b"North field", a.get("/farms").data)
        r = a.post("/farms/1/recommend")
        self.assertIn("/recommendations/", r.headers["Location"])
        self.assertIn(b'class="crop-name">Wheat', a.get(r.headers["Location"]).data)
        self.assertTrue(a.get("/recommendations/1/download").data.startswith(b"%PDF"))

        # Duplicate contact number is mapped to IntegrityError and handled (TC-04).
        self.assertIn(b"already registered", b.post("/register", data=FARMER).data)

        # Foreign keys are enforced over HTTP: deleting the farmer cascades (TC-52).
        b.post("/login", data={"role": "admin", "identifier": "admin", "password": "admin123"})
        b.post("/admin/users/2/delete")
        counts = self.server.db.execute(
            "SELECT (SELECT COUNT(*) FROM farm_details), (SELECT COUNT(*) FROM recommendations)").fetchone()
        self.assertEqual(counts, (0, 0))

    def test_network_failure_shows_503(self):
        def broken(*a, **k):
            import requests
            raise requests.ConnectionError("down")
        with mock.patch.object(self.server, "post", broken):
            r = self.app.test_client().post("/login", data={"role": "farmer", "identifier": "1", "password": "x"})
        self.assertEqual(r.status_code, 503)

    def test_value_round_trip(self):
        for value in (None, 0, 42, -3.5, "text", b"\x00\x01"):
            self.assertEqual(_decode(_encode(value)), value)
        self.assertEqual(TursoConnection("libsql://x.turso.io", "t").endpoint, "https://x.turso.io/v2/pipeline")


if __name__ == "__main__":
    unittest.main()
