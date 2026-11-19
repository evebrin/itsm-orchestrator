"""A small in-memory ServiceNow for seed/teardown tests: Table API (GET/POST/PATCH/DELETE) and the stats API.

Queries support `^`-joined terms of `field=value`, `field!=value`, `fieldSTARTSWITHvalue` and `fieldINa,b`;
dotted reference fields are not supported (the loader does not use them).
"""
import itertools
import json as _json
from urllib.parse import urlparse

from tests.unit.fakes import FakeResp


def _match(row, query):
    for term in filter(None, (query or "").split("^")):
        for op in ("STARTSWITH", "!=", "IN", "="):
            if op in term:
                field, val = term.split(op, 1)
                have = str(row.get(field, ""))
                ok = {"STARTSWITH": have.startswith(val), "!=": have != val, "IN": have in val.split(","),
                      "=": have == val}[op]
                if not ok:
                    return False
                break
    return True


class FakeInstance:
    def __init__(self, tables=None):
        self.tables = {t: [dict(r) for r in rows] for t, rows in (tables or {}).items()}
        self.ids = itertools.count(1)
        self.calls = []
        self.headers, self.auth = {}, None

    def rows(self, table, query=""):
        return [r for r in self.tables.get(table, []) if _match(r, query)]

    def request(self, method, url, params=None, json=None, timeout=None):
        path = urlparse(url).path
        params = params or {}
        self.calls.append((method, path, params, json, self.auth[0] if self.auth else None))
        parts = path.strip("/").split("/")
        if parts[:3] == ["api", "now", "stats"]:
            return FakeResp(200, {"stats": {"count": str(len(self.rows(parts[3], params.get("sysparm_query"))))}})
        if parts[:3] != ["api", "now", "table"]:
            return FakeResp(404, {"error": "no such api"})
        table, sys_id = parts[3], (parts[4] if len(parts) > 4 else None)
        store = self.tables.setdefault(table, [])
        if method == "GET":
            got = self.rows(table, params.get("sysparm_query"))[: int(params.get("sysparm_limit", 10000))]
            fields = [f for f in (params.get("sysparm_fields") or "").split(",") if f]
            return FakeResp(200, [{f: r.get(f, "") for f in fields} if fields else dict(r) for r in got])
        if method == "POST":
            row = {**_json.loads(_json.dumps(json or {})), "sys_id": f"sid{next(self.ids):05d}"}
            store.append(row)
            return FakeResp(201, dict(row))
        row = next((r for r in store if r["sys_id"] == sys_id), None)
        if row is None:
            return FakeResp(404, {"error": "not found"})
        if method == "PATCH":
            row.update(json or {})
            return FakeResp(200, dict(row))
        store.remove(row)
        return FakeResp(204)
