"""`itsm seed` and `itsm teardown` (END_TO_END_ITSM.md §12.1). Admin only, as the design allows.

seed
- refuses if the run tag already has incidents;
- records baseline counts of records this project did not create;
- creates the three runtime identities the orchestrator owns (`syn.svc.e2e_incident`, `_problem`, `_approver`;
  web service access only, passwords set through the display value so the platform hashes them, written to
  .env and never printed); the change identity `syn.svc.change_agents` belongs to the change repository;
- loads the 60-day history as resolved incidents tagged `SYN-E2E-<run_id>`; the live stream, the fix catalog and
  the ground truth are saved in the manifest for the run, not loaded;
- writes `var/seed_<run_id>.json` after every step, so a teardown after a failure finds everything.

teardown deletes children first (pm-agent's order): change children, changes, articles, problems, incidents,
then the identities' memberships, roles and users. Every row is checked against the run tag or the manifest
before it is deleted. It ends by recounting: nothing tagged left, baseline counts unchanged.
"""
from __future__ import annotations

import json
import re
import secrets
from datetime import datetime, timedelta
from pathlib import Path

from itsm.data.generate import plan as make_plan
from itsm.platform.settings import ROOT, write_env
from itsm.platform.sn import SNClient
from itsm.probes import APPROVER_GROUPS, ROLES

RUN_ID = re.compile(r"^\d{8}-\d{4}$")
USER_PREFIX = "syn.svc.e2e_"
DUTIES = ("incident", "problem", "approver")
ENV_KEYS = {d: (f"SN_{d.upper()}_USER", f"SN_{d.upper()}_PASSWORD") for d in DUTIES}
CLOSE_LABELS = {"planted": "Workaround provided", "other": "Solution provided"}  # P12 read these labels
CHANGE_CHILDREN = (("sysapproval_approver", "sysapproval"), ("sysapproval_group", "parent"),
                   ("change_task", "change_request"), ("task_ci", "task"), ("task_cmdb_ci_service", "task"),
                   ("conflict", "change"), ("chg_policy_applied", "change_request"))


class SeedError(RuntimeError):
    pass


def tag(run_id: str) -> str:
    if not RUN_ID.fullmatch(run_id):
        raise SeedError("run id must look like YYYYMMDD-HHMM")
    return f"SYN-E2E-{run_id}"


def run_queries(t: str) -> list[str]:
    """This run's records exactly: the run tag itself, or a case id under it (never a look-alike prefix)."""
    return [f"correlation_id={t}", f"correlation_idSTARTSWITH{t}-"]


def _count_run(admin: SNClient, table: str, t: str, purpose: str) -> int:
    return sum(admin.count(table, q, purpose=purpose) for q in run_queries(t))


def manifest_path(run_id: str, var: Path = ROOT / "var") -> Path:
    return var / f"seed_{run_id}.json"


def _save(m: dict, path: Path) -> None:
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(m, indent=1, default=str))


def _value(v) -> str:
    return str(v.get("value") if isinstance(v, dict) else (v or ""))


def _ids(admin: SNClient, table: str, field: str, names: set[str], purpose: str) -> dict[str, str]:
    out: dict[str, str] = {}
    names = sorted(n for n in names if n)
    for i in range(0, len(names), 50):
        chunk = names[i:i + 50]
        for r in admin.list(table, f"{field}IN{','.join(chunk)}", ["sys_id", field], purpose=purpose, limit=500):
            out[_value(r.get(field))] = _value(r.get("sys_id"))
    missing = [n for n in names if n not in out]
    if missing:
        raise SeedError(f"{len(missing)} {table} rows not found on the instance (first: {missing[0]}); is the Larkspur seed loaded?")
    return out


def _choice(admin: SNClient, table: str, element: str, label: str) -> str:
    rows = admin.list("sys_choice", f"name={table}^element={element}^label={label}^inactive=false", ["value"],
                      purpose=f"metadata: {table}.{element} {label}", limit=5)
    if not rows:
        raise SeedError(f"no {table}.{element} choice labelled {label!r} on the instance")
    return _value(rows[0]["value"])


def _baseline(admin: SNClient, t: str) -> dict[str, int]:
    """Per table: records this project did not create (all rows minus this run's and the project identities)."""
    out = {}
    for table in ("incident", "problem", "change_request"):
        total = admin.count(table, "", purpose=f"metadata: total {table}")
        out[table] = total - _count_run(admin, table, t, f"metadata: ours {table}")
    out["kb_knowledge"] = (admin.count("kb_knowledge", "", purpose="metadata: total kb_knowledge")
                           - admin.count("kb_knowledge", f"short_descriptionSTARTSWITH[{t}]", purpose="metadata: ours kb_knowledge")
                           - admin.count("kb_knowledge", f"short_descriptionSTARTSWITH[{t}-", purpose="metadata: ours kb_knowledge"))
    out["sys_user"] = (admin.count("sys_user", "", purpose="metadata: total sys_user")
                       - admin.count("sys_user", f"user_nameSTARTSWITH{USER_PREFIX}", purpose="metadata: ours sys_user"))
    return out


def seed(admin: SNClient, run_id: str, *, env_path: Path | None = None, var: Path = ROOT / "var",
         seed_number: int = 42) -> dict:
    t = tag(run_id)
    path = manifest_path(run_id, var)
    if path.exists():
        raise SeedError(f"{path.name} exists: this run was seeded before; tear it down first")
    if _count_run(admin, "incident", t, "metadata: run tag free"):
        raise SeedError(f"incidents tagged {t} already exist")
    p = make_plan(seed_number)
    history = [r for r in p["incidents"] if r["phase"] == "history"]
    m = {"run_id": run_id, "tag": t, "seed": seed_number, "anchor": p["anchor"], "started": datetime.now().isoformat(),
         "baseline": _baseline(admin, t), "identities": {}, "incidents": {}, "complete": False,
         "history_count": len(history), "stream": [r for r in p["incidents"] if r["phase"] == "stream"],
         "catalog": p["catalog"],
         "ground_truth": p["ground_truth"]}
    _save(m, path)

    cis = _ids(admin, "cmdb_ci", "name", {r["cmdb_ci"] for r in p["incidents"]}, "metadata: Larkspur CIs")
    services = _ids(admin, "cmdb_ci_service", "name", {r["service"] for r in p["incidents"]}, "metadata: services")
    groups = _ids(admin, "sys_user_group", "name", {r["assignment_group"] for r in history} | set(APPROVER_GROUPS),
                  "metadata: groups")
    callers = _ids(admin, "sys_user", "user_name", {r["caller"] for r in history}, "metadata: callers")
    resolved = _choice(admin, "incident", "state", "Resolved")
    codes = {k: _choice(admin, "incident", "close_code", v) for k, v in CLOSE_LABELS.items()}

    # identities first: a failure later still leaves a manifest teardown can use
    approver_groups = sorted(set(APPROVER_GROUPS) | {r["assignment_group"] for r in history if r["cluster"] in "abcd"})
    groups.update(_ids(admin, "sys_user_group", "name", set(approver_groups) - set(groups), "metadata: groups"))
    env = {}
    for duty in DUTIES:
        user, password = USER_PREFIX + duty, secrets.token_urlsafe(24) + "aA1!"
        if admin.count("sys_user", f"user_name={user}", purpose="metadata: identity free"):
            raise SeedError(f"user {user} already exists; tear down the earlier run first")
        status, row = admin.create("sys_user", {"user_name": user, "first_name": "SYN E2E", "last_name": duty,
                                                "web_service_access_only": "true", "active": "true",
                                                "user_password": password}, purpose=f"setup: identity {user}",
                                   display_input=True)
        if status not in (200, 201):
            raise SeedError(f"could not create {user} (HTTP {status})")
        ident = {"user": user, "sys_id": _value(row["sys_id"]), "roles": [], "memberships": []}
        m["identities"][duty] = ident
        _save(m, path)
        for role in ROLES[duty]:
            rid = _ids(admin, "sys_user_role", "name", {role}, f"metadata: role {role}")[role]
            _, r = admin.create("sys_user_has_role", {"user": ident["sys_id"], "role": rid}, purpose=f"setup: role {role} for {user}")
            ident["roles"].append(_value(r.get("sys_id")))
        for g in approver_groups if duty == "approver" else ():
            _, r = admin.create("sys_user_grmember", {"user": ident["sys_id"], "group": groups[g]},
                                purpose=f"setup: {user} in {g}")
            ident["memberships"].append(_value(r.get("sys_id")))
        _save(m, path)
        env.update({ENV_KEYS[duty][0]: user, ENV_KEYS[duty][1]: password})
    write_env(env, env_path)

    for r in history:
        opened = r["opened_at"]
        planted = r["cluster"] in "abcd"
        payload = {"correlation_id": t, "short_description": r["short_description"],
                   "description": f"{r['short_description']}. Reported by user. (synthetic, {t})",
                   "category": r["category"], "impact": r["impact"], "urgency": r["urgency"],
                   "cmdb_ci": cis.get(r["cmdb_ci"], ""), "business_service": services.get(r["service"], ""),
                   "assignment_group": groups[r["assignment_group"]], "caller_id": callers[r["caller"]],
                   "opened_at": opened.strftime("%Y-%m-%d %H:%M:%S"),
                   "resolved_at": (opened + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S"),
                   "state": resolved, "close_code": codes["planted" if planted else "other"],
                   "close_notes": r["work_notes"], "work_notes": r["work_notes"]}
        status, row = admin.create("incident", payload, purpose=f"setup: incident {r['key']}")
        if status not in (200, 201):
            raise SeedError(f"could not create incident {r['key']} (HTTP {status})")
        m["incidents"][r["key"]] = _value(row["sys_id"])
        if len(m["incidents"]) % 25 == 0:
            _save(m, path)
    m["complete"] = True
    _save(m, path)
    return m


def check(admin: SNClient, run_id: str, var: Path = ROOT / "var") -> list[tuple[str, bool, str]]:
    """`itsm seed --check`: the instance holds exactly what the manifest says was loaded."""
    m = json.loads(manifest_path(run_id, var).read_text())
    n = admin.count("incident", f"correlation_id={m['tag']}", purpose="metadata: seed check")
    loaded, planned = len(m["incidents"]), m["history_count"]
    out = [("seed completed", m["complete"], "complete" if m["complete"] else "stopped part way: tear down, seed again"),
           ("history incidents loaded = planned", loaded == planned, f"{loaded} loaded, {planned} planned"),
           ("incidents on the instance = loaded", n == loaded, f"{n} on the instance")]
    for ident in m["identities"].values():
        ok = admin.count("sys_user", f"user_name={ident['user']}^web_service_access_only=true",
                         purpose="metadata: seed check") == 1
        out.append((f"identity {ident['user']}", ok, "web service access only" if ok else "missing"))
    return out


def teardown(admin: SNClient, run_id: str, var: Path = ROOT / "var") -> dict:
    t = tag(run_id)
    path = manifest_path(run_id, var)
    m = json.loads(path.read_text()) if path.exists() else {"identities": {}, "baseline": None}
    deleted: dict[str, int] = {}

    def drop(table: str, rows: list[dict], ok) -> None:
        for r in rows:
            if not ok(r):
                raise SeedError(f"refusing to delete a {table} row that is not this run's")
            status = admin.delete(table, _value(r["sys_id"]), purpose=f"cleanup: {table}")
            if status not in (200, 204, 404):
                raise SeedError(f"could not delete {table} (HTTP {status})")
            deleted[table] = deleted.get(table, 0) + 1

    def tagged(r: dict) -> bool:
        c = _value(r.get("correlation_id"))
        return c == t or c.startswith(t + "-")

    for q in run_queries(t):
        for chg in admin.list("change_request", q, ["sys_id", "correlation_id"], purpose="cleanup: changes", limit=1000):
            for table, ref in CHANGE_CHILDREN:
                drop(table, admin.list(table, f"{ref}={_value(chg['sys_id'])}", ["sys_id"], purpose=f"cleanup: {table}",
                                       limit=1000), lambda r: True)
            drop("change_request", [chg], tagged)
    for prefix in (f"[{t}]", f"[{t}-"):  # title prefix of the run or of one of its cases
        arts = admin.list("kb_knowledge", f"short_descriptionSTARTSWITH{prefix}", ["sys_id", "short_description"],
                          purpose="cleanup: articles", limit=1000)
        drop("kb_knowledge", arts, lambda r, x=prefix: _value(r.get("short_description")).startswith(x))
    for table in ("problem", "incident"):
        for q in run_queries(t):
            drop(table, admin.list(table, q, ["sys_id", "correlation_id"], purpose=f"cleanup: {table}", limit=10000), tagged)
    for ident in m["identities"].values():
        if not ident["user"].startswith(USER_PREFIX):
            raise SeedError("manifest names an identity outside the project prefix")
        for table, key in (("sys_user_grmember", "memberships"), ("sys_user_has_role", "roles")):
            drop(table, [{"sys_id": s} for s in ident[key] if s], lambda r: True)
        rows = admin.list("sys_user", f"user_name={ident['user']}", ["sys_id", "user_name"], purpose="cleanup: identity", limit=2)
        drop("sys_user", rows, lambda r, u=ident["user"]: _value(r.get("user_name")) == u)

    left = {table: _count_run(admin, table, t, "cleanup: residue") for table in ("incident", "problem", "change_request")}
    left["sys_user"] = sum(admin.count("sys_user", f"user_name={i['user']}", purpose="cleanup: residue")
                           for i in m["identities"].values())
    unchanged = None
    if m.get("baseline"):
        now = _baseline(admin, t)
        unchanged = {k: now[k] == v for k, v in m["baseline"].items()}
    if not any(left.values()) and path.exists():
        path.rename(path.with_name(path.stem + ".torn-down.json"))
    return {"deleted": deleted, "left": left, "untagged_unchanged": unchanged}
