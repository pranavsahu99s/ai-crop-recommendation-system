"""Minimal sqlite3-style connection to a Turso (libSQL) database over HTTP.

Used when TURSO_DATABASE_URL is set, so every serverless instance shares
one database. Turso speaks the SQLite dialect, so schema.sql and all
queries are unchanged. Only the sqlite3 calls this app uses are provided:
execute, executemany, executescript, commit, rollback, close, and rows that
support row["col"], row[0], keys() and dict(row).

Protocol: Hrana over HTTP, POST /v2/pipeline. Each call runs as its own
short stream with foreign keys switched on, and commits immediately.
"""
import base64
import sqlite3

import requests


class TursoUnavailable(Exception):
    pass


class Row(tuple):
    def __new__(cls, values, columns):
        row = super().__new__(cls, values)
        row._index = {name: i for i, name in enumerate(columns)}
        return row

    def __getitem__(self, key):
        if isinstance(key, str):
            return super().__getitem__(self._index[key])
        return super().__getitem__(key)

    def keys(self):
        return list(self._index)


class Cursor:
    def __init__(self, rows=(), lastrowid=None, rowcount=-1):
        self._rows = list(rows)
        self.lastrowid = lastrowid
        self.rowcount = rowcount

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def __iter__(self):
        return iter(self._rows)


def _encode(value):
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "integer", "value": str(int(value))}
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    if isinstance(value, float):
        return {"type": "float", "value": value}
    if isinstance(value, (bytes, bytearray)):
        return {"type": "blob", "base64": base64.b64encode(value).decode()}
    return {"type": "text", "value": str(value)}


def _decode(cell):
    kind = cell.get("type")
    if kind == "null":
        return None
    if kind == "integer":
        return int(cell["value"])
    if kind == "float":
        return float(cell["value"])
    if kind == "blob":
        return base64.b64decode(cell.get("base64", ""))
    return cell.get("value")


def _raise_sql_error(error):
    message = error.get("message", "database error")
    code = error.get("code") or ""
    if "CONSTRAINT" in code or "constraint failed" in message.lower():
        raise sqlite3.IntegrityError(message)
    raise sqlite3.OperationalError(message)


class TursoConnection:
    def __init__(self, url, auth_token, timeout=10.0, session=None):
        if url.startswith("libsql://"):
            url = "https://" + url[len("libsql://"):]
        self.endpoint = url.rstrip("/") + "/v2/pipeline"
        self.http = session or requests.Session()
        self.http.headers["Authorization"] = f"Bearer {auth_token}"
        self.timeout = timeout

    def _pipeline(self, requests_):
        body = {"baton": None, "requests": [
            {"type": "execute", "stmt": {"sql": "PRAGMA foreign_keys = ON"}},
            *requests_,
            {"type": "close"},
        ]}
        try:
            resp = self.http.post(self.endpoint, json=body, timeout=self.timeout)
        except requests.RequestException as exc:
            raise TursoUnavailable(type(exc).__name__) from None
        if resp.status_code >= 400:
            raise TursoUnavailable(f"HTTP {resp.status_code}")
        results = resp.json().get("results", [])[1:-1]
        for result in results:
            if result.get("type") == "error":
                _raise_sql_error(result.get("error", {}))
        return [r["response"] for r in results]

    @staticmethod
    def _stmt(sql, params):
        if isinstance(params, dict):
            named = [{"name": f":{k}", "value": _encode(v)} for k, v in params.items()]
            return {"type": "execute", "stmt": {"sql": sql, "named_args": named}}
        return {"type": "execute", "stmt": {"sql": sql, "args": [_encode(v) for v in params]}}

    @staticmethod
    def _cursor(response):
        result = response["result"]
        columns = [c.get("name") for c in result.get("cols", [])]
        rows = [Row([_decode(c) for c in r], columns) for r in result.get("rows", [])]
        last = result.get("last_insert_rowid")
        return Cursor(rows, int(last) if last is not None else None, result.get("affected_row_count", -1))

    def execute(self, sql, params=()):
        return self._cursor(self._pipeline([self._stmt(sql, params)])[0])

    def executemany(self, sql, seq):
        seq = list(seq)
        if not seq:
            return Cursor()
        responses = self._pipeline([self._stmt(sql, p) for p in seq])
        return Cursor(rowcount=sum(r["result"].get("affected_row_count", 0) for r in responses))

    def executescript(self, script):
        self._pipeline([{"type": "sequence", "sql": script}])

    # Every statement is committed as it runs.
    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        self.http.close()
