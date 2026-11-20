"""ServiceNow REST client for the orchestrator's own nodes (END_TO_END_ITSM.md §8).

One client per identity. Every request is audited with the identity and a purpose. Rules carried over:
- PDI hosts only (settings.PDI_URL); secrets are redacted from every error message;
- a hibernating PDI answers with an HTML page: raised as Hibernating, never parsed as data;
- a request that failed before any response is retried only for GET (a dropped write may have committed),
  the change repository's rule (cm_agents/servicenow/client.py);
- 429/502/503/504 are retried with backoff, at most 3 attempts; other 4xx/5xx raise SNError with the status;
- dry run: reads go to the instance, every write is recorded in `planned` and the audit (result "planned") and
  never sent; it answers with a placeholder sys_id so the caller can go on.
"""
from __future__ import annotations

import time
from typing import Any

import requests

from itsm.platform.audit import Audit
from itsm.platform.settings import PDI_URL, redact

MAX_ATTEMPTS = 3
RETRY_STATUS = {429, 502, 503, 504}


class SNError(RuntimeError):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class Hibernating(SNError):
    pass


class SNClient:
    def __init__(self, instance: str, user: str, password: str, *, identity: str, audit: Audit,
                 secrets: list[str] | None = None, session: requests.Session | None = None,
                 timeout: float = 60, sleep=time.sleep, dry_run: bool = False) -> None:
        if not PDI_URL.fullmatch(instance):
            raise SNError("refusing a host that is not a Personal Developer Instance")
        self.instance, self.identity, self.audit = instance, identity, audit
        self.secrets = [s for s in (secrets or []) + [password] if s]
        self.session = session or requests.Session()
        self.session.auth = (user, password)
        self.session.headers.update({"Accept": "application/json", "Content-Type": "application/json"})
        self.timeout, self._sleep = timeout, sleep
        self.dry_run, self.planned = dry_run, []

    # ---- low level ---------------------------------------------------------------------------
    def request(self, method: str, path: str, *, purpose: str, params: dict | None = None,
                json: dict | None = None) -> tuple[int, Any]:
        """(status, parsed result). Raises SNError for errors other than 401/403/404, which are returned
        so a probe can assert a refusal."""
        if self.dry_run and method != "GET":
            self.planned.append({"identity": self.identity, "method": method, "path": path, "purpose": purpose,
                                 "params": params, "json": json})
            self._log(method, path, purpose, "planned")
            return (201 if method == "POST" else 200), {"sys_id": f"dryrun-{len(self.planned):04d}", "number": "DRYRUN"}
        url = f"{self.instance}{path}"
        last = ""
        for attempt in range(MAX_ATTEMPTS):
            try:
                r = self.session.request(method, url, params=params, json=json, timeout=self.timeout)
            except requests.RequestException as e:
                last = f"{type(e).__name__}"
                if method == "GET" and attempt < MAX_ATTEMPTS - 1:
                    self._sleep(2 ** attempt)
                    continue
                self._log(method, path, purpose, "no response")
                raise SNError(f"{method} {path}: no response ({last})") from None
            if "text/html" in r.headers.get("Content-Type", ""):
                self._log(method, path, purpose, "hibernating")
                raise Hibernating("the PDI answered with an HTML page: it is probably hibernating; wake it in a browser")
            if r.status_code in RETRY_STATUS and attempt < MAX_ATTEMPTS - 1:
                self._sleep(2 ** attempt)
                continue
            self._log(method, path, purpose, str(r.status_code))
            if r.status_code in (401, 403, 404):
                return r.status_code, self._json(r)
            if r.status_code >= 400:
                raise SNError(redact(f"{method} {path} -> {r.status_code}: {r.text[:300]}", self.secrets),
                              r.status_code)
            return r.status_code, self._json(r).get("result") if r.content else None
        raise SNError(f"{method} {path}: giving up after {MAX_ATTEMPTS} attempts ({last})")

    @staticmethod
    def _json(r: requests.Response) -> dict:
        try:
            return r.json() if r.content else {}
        except ValueError:
            return {}

    def _log(self, method: str, path: str, purpose: str, outcome: str) -> None:
        self.audit.write(practice="platform", node="sn", identity=self.identity, action=f"{method} {path}",
                         record=purpose, result=outcome)

    # ---- table API -----------------------------------------------------------------------------
    def list(self, table: str, query: str = "", fields: list[str] | None = None, *, purpose: str,
             limit: int = 200, display: bool = False, offset: int = 0) -> list[dict]:
        """Reference fields come back as plain sys_ids (sysparm_exclude_reference_link), as pm-agent reads them."""
        params: dict[str, Any] = {"sysparm_limit": limit, "sysparm_query": query, "sysparm_offset": offset,
                                  "sysparm_display_value": "true" if display else "false",
                                  "sysparm_exclude_reference_link": "true"}
        if fields:
            params["sysparm_fields"] = ",".join(fields)
        status, result = self.request("GET", f"/api/now/table/{table}", purpose=purpose, params=params)
        if status != 200:
            raise SNError(f"GET {table} as {self.identity} -> {status}", status)
        return result or []

    def get(self, table: str, sys_id: str, fields: list[str] | None = None, *, purpose: str) -> dict:
        rows = self.list(table, f"sys_id={sys_id}", fields, purpose=purpose, limit=1)
        return rows[0] if rows else {}

    def count(self, table: str, query: str, *, purpose: str) -> int:
        status, result = self.request("GET", f"/api/now/stats/{table}", purpose=purpose,
                                      params={"sysparm_count": "true", "sysparm_query": query})
        if status != 200:
            raise SNError(f"stats {table} as {self.identity} -> {status}", status)
        return int(((result or {}).get("stats") or {}).get("count") or 0)

    def create(self, table: str, payload: dict, *, purpose: str, display_input: bool = False) -> tuple[int, dict]:
        params = {"sysparm_input_display_value": "true"} if display_input else None
        status, result = self.request("POST", f"/api/now/table/{table}", purpose=purpose, params=params, json=payload)
        return status, (result if isinstance(result, dict) else {})

    def update(self, table: str, sys_id: str, payload: dict, *, purpose: str) -> tuple[int, dict]:
        status, result = self.request("PATCH", f"/api/now/table/{table}/{sys_id}", purpose=purpose, json=payload)
        return status, (result if isinstance(result, dict) else {})

    def delete(self, table: str, sys_id: str, *, purpose: str) -> int:
        status, _ = self.request("DELETE", f"/api/now/table/{table}/{sys_id}", purpose=purpose)
        return status
