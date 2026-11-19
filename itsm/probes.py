"""Phase 1 probes P0-P15 on the shared PDI (END_TO_END_ITSM.md §11, §13).

P0 runs first and only counts the change repository's Larkspur seed. If the seed is not there, every other
probe is skipped: the instance is not ready (or not the right one), and loading the seed is the owner's decision.

Two kinds:
- read: reads metadata or counts. Writes nothing.
- temp: creates temporary records tagged `SYN-PROBE-E2E-<hex>` and temporary users `syn.probe.e2e_<duty>`,
  then deletes every one of them (cleanup runs even after a failure), and checks that none is left.

Admin is used only to create and delete the temporary users and records and to read metadata; every other
call runs as the temporary identity under test. `--dry-run` prints each probe's plan and sends no request.

Results: PASS (the design's assumption holds), FALLBACK (it does not; the design's named fallback applies),
FAIL (it does not and the design has no fallback: stop and ask), INCONCLUSIVE (could not be decided; the
detail says why).
"""
from __future__ import annotations

import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from itsm.platform.audit import Audit
from itsm.platform.settings import Settings
from itsm.platform.sn import SNClient, SNError

TAG_PREFIX = "SYN-PROBE-E2E-"
USER_PREFIX = "syn.probe.e2e_"
ROLES = {  # END_TO_END_ITSM.md §5.2, one identity per duty
    "incident": ["itil"],
    "problem": ["itil", "problem_coordinator"],
    "change": ["sn_change_write", "audit_viewer", "sn_incident_write"],  # mirrors syn.svc.change_agents
    "approver": ["approver_user"],
}
APPROVER_GROUPS = ["Change Management", "CAB Approval"]  # DISCOVERY item 5
CHANGE_STATES = {"new": "-5", "assess": "-4", "authorize": "-3", "scheduled": "-2"}  # DISCOVERY item 3
PREFIXES = ["SYN-E2E-", TAG_PREFIX, "SYN-CHG-", "SYN-OPEN-", "SYN-REL-", "SYN-INC-", "PMSYNTH-"]
REFUSED = (401, 403)


@dataclass
class Result:
    id: str
    status: str
    detail: str
    facts: dict = field(default_factory=dict)


@dataclass
class Probe:
    id: str
    title: str
    kind: str  # read | temp
    needs: tuple[str, ...]  # temporary identities
    plan: tuple[str, ...]
    fn: Callable[[ProbeRun], Result]


def value(v) -> str:
    """A field from the Table API or the Change API ({'value': ..., 'display_value': ...})."""
    return str(v.get("value") if isinstance(v, dict) else (v or ""))


class ProbeRun:
    def __init__(self, settings: Settings, audit: Audit, *, session_factory=None, sleep=time.sleep) -> None:
        self.settings, self.audit, self.sleep = settings, audit, sleep
        self.session_factory = session_factory
        self.tag = TAG_PREFIX + secrets.token_hex(4)
        self.admin = self._client("admin", settings.get("SN_ADMIN_USER"), settings.get("SN_ADMIN_PASSWORD"))
        self.users: dict[str, dict] = {}       # duty -> {sys_id, client}
        self.created: list[tuple[str, str]] = []  # (table, sys_id), deleted in reverse order
        self.changes: list[str] = []

    def _client(self, identity: str, user: str, password: str) -> SNClient:
        return SNClient(self.settings.instance, user, password, identity=identity, audit=self.audit,
                        secrets=self.settings.secrets(), session=self.session_factory() if self.session_factory else None)

    # ---- temporary records -------------------------------------------------------------------
    def make(self, table: str, payload: dict, purpose: str, *, display_input: bool = False) -> str:
        status, row = self.admin.create(table, payload, purpose=f"setup: {purpose}", display_input=display_input)
        sys_id = value(row.get("sys_id"))
        if status not in (200, 201) or not sys_id:
            raise SNError(f"setup could not create {table} ({status})", status)
        self.created.append((table, sys_id))
        return sys_id

    def one(self, table: str, query: str, purpose: str) -> str:
        rows = self.admin.list(table, query, ["sys_id"], purpose=f"metadata: {purpose}", limit=2)
        if len(rows) != 1:
            raise SNError(f"expected one {table} row for {purpose}, found {len(rows)}")
        return rows[0]["sys_id"]

    def identity(self, duty: str) -> SNClient:
        if duty in self.users:
            return self.users[duty]["client"]
        user_name, password = USER_PREFIX + duty, secrets.token_urlsafe(24) + "aA1!"
        # Web service access only; the password set through the display value so the platform hashes it
        # (DISCOVERY item 13). The password lives only in memory for this run.
        sys_id = self.make("sys_user", {"user_name": user_name, "first_name": "SYN PROBE", "last_name": duty,
                                        "web_service_access_only": "true", "active": "true",
                                        "user_password": password}, f"user {user_name}", display_input=True)
        for role in ROLES[duty]:
            self.make("sys_user_has_role", {"user": sys_id, "role": self.one("sys_user_role", f"name={role}", role)},
                      f"role {role} for {user_name}")
        if duty == "approver":
            for g in APPROVER_GROUPS:
                self.make("sys_user_grmember", {"user": sys_id, "group": self.one("sys_user_group", f"name={g}", g)},
                          f"{user_name} in {g}")
        client = self._client(user_name, user_name, password)
        for _ in range(5):  # role grants can take a moment to apply to a new session
            status, _ = client.request("GET", "/api/now/table/sys_user", purpose=f"login check {user_name}",
                                       params={"sysparm_limit": 1, "sysparm_fields": "sys_id"})
            if status == 200:
                break
            self.sleep(2)
        else:
            raise SNError(f"temporary user {user_name} cannot log in (HTTP {status})", status)
        self.users[duty] = {"sys_id": sys_id, "client": client}
        return client

    def problem(self, purpose: str) -> str:
        return self.make("problem", {"short_description": f"{self.tag} {purpose}", "correlation_id": self.tag}, purpose)

    def incident(self, purpose: str, **fields) -> str:
        return self.make("incident", {"short_description": f"{self.tag} {purpose}", "correlation_id": self.tag,
                                      **fields}, purpose)

    def cleanup(self) -> list[str]:
        """Delete everything this run created, platform children of probe changes first. Returns problems."""
        errors = []
        for chg in self.changes:
            for table, ref in (("sysapproval_approver", "sysapproval"), ("sysapproval_group", "parent"),
                               ("change_task", "change_request"), ("task_ci", "task"), ("task_cmdb_ci_service", "task"),
                               ("conflict", "change"), ("chg_policy_applied", "change_request")):
                try:
                    for r in self.admin.list(table, f"{ref}={chg}", ["sys_id"], purpose=f"cleanup: {table}"):
                        self.admin.delete(table, r["sys_id"], purpose=f"cleanup: {table}")
                except SNError as e:
                    errors.append(f"{table}: {e}")
            self.created.append(("change_request", chg))
        for table, sys_id in reversed(self.created):
            try:
                status = self.admin.delete(table, sys_id, purpose=f"cleanup: {table}")
                if status not in (200, 204, 404):
                    errors.append(f"{table} {sys_id}: HTTP {status}")
            except SNError as e:
                errors.append(f"{table} {sys_id}: {e}")
        self.created, self.changes = [], []
        return errors

    def residue(self) -> dict[str, int]:
        q = f"correlation_idSTARTSWITH{TAG_PREFIX}"
        counts = {t: self.admin.count(t, q, purpose="cleanup: residue") for t in ("incident", "problem", "change_request")}
        counts["sys_user"] = self.admin.count("sys_user", f"user_nameSTARTSWITH{USER_PREFIX}", purpose="cleanup: residue")
        return counts


# ---- helpers used by several probes ------------------------------------------------------------
def dictionary(run: ProbeRun, table: str, element: str) -> dict | None:
    rows = run.admin.list("sys_dictionary", f"nameIN{table},task^element={element}",
                          ["name", "element", "internal_type", "reference", "read_only"], purpose=f"metadata: {table}.{element}")
    own = [r for r in rows if r["name"] == table]
    return (own or rows or [None])[0]


def choices(run: ProbeRun, table: str, element: str) -> list[dict]:
    return run.admin.list("sys_choice", f"name={table}^element={element}^inactive=false", ["value", "label"],
                          purpose=f"metadata: choices {table}.{element}")


def refused_or_unchanged(status: int, after: str, before: str) -> bool:
    return status in REFUSED or after == before


# ---- the probes ------------------------------------------------------------------------------------
# The change repository's seed markers (vendor/ChangeManagementAgent cm_agents/data/queries.py).
LARKSPUR = {
    "seeded changes": ("change_request", "correlation_idSTARTSWITHSYN-CHG-^ORcorrelation_idSTARTSWITHSYN-OPEN-"
                                         "^ORcorrelation_idSTARTSWITHSYN-REL-"),
    "seeded incidents": ("incident", "correlation_idSTARTSWITHSYN-INC-"),
    "Larkspur CIs": ("cmdb_ci", "nameSTARTSWITHsyn-"),
    "maintenance schedules": ("cmn_schedule", "nameSTARTSWITHSYN Tier-"),
}


def p0(run: ProbeRun) -> Result:
    counts = {k: run.admin.count(t, q, purpose=f"metadata: count {k}") for k, (t, q) in LARKSPUR.items()}
    present = [k for k, n in counts.items() if n]
    if len(present) == len(counts):
        return Result("P0", "PASS", "Larkspur seed present: " + ", ".join(f"{n} {k}" for k, n in counts.items()), counts)
    if not present:
        return Result("P0", "FAIL", "no Larkspur seed on this instance: load it (change repository RUNBOOK, "
                      "`cm-agents seed --seed 42 --anchor 2026-10-27`) only with the owner's agreement", counts)
    return Result("P0", "INCONCLUSIVE", "partial Larkspur seed (missing: " + ", ".join(k for k in counts if k not in present)
                  + "): ask the owner before going on", counts)


def p1(run: ProbeRun) -> Result:
    d = dictionary(run, "incident", "parent")
    prb, inc = run.problem("P1 problem"), run.incident("P1 incident")
    status, _ = run.identity("problem").update("incident", inc, {"parent": prb}, purpose="P1 link incident to problem")
    got = value(run.admin.get("incident", inc, ["parent"], purpose="P1 read back").get("parent"))
    facts = {"dictionary": d, "status": status, "linked": got == prb}
    if got == prb:
        return Result("P1", "PASS", "the problem identity can set incident.parent to a problem", facts)
    return Result("P1", "FAIL", f"incident.parent was not set (HTTP {status}); the design has no other link", facts)


def p2(run: ProbeRun) -> Result:
    fields = ["rfc", "cause_notes", "fix_notes", "workaround", "known_error", "primary_known_error_article",
              "resolution_code"]
    found = {f: dictionary(run, "problem", f) for f in fields}
    missing = [f for f, d in found.items() if not d]
    codes = [c["value"] for c in choices(run, "problem", "resolution_code")]
    facts = {"missing": missing, "resolution_codes": codes}
    if not missing and "fix_applied" in codes:
        return Result("P2", "PASS", "every problem field the design uses exists; resolution code fix_applied exists", facts)
    return Result("P2", "FAIL", f"missing fields {missing} or no fix_applied code", facts)


def p3(run: ProbeRun) -> Result:
    rows = run.admin.list("sys_dictionary_override", "name=problem^element=state",
                          ["read_only_override", "read_only"], purpose="metadata: problem.state override")
    ro = any(value(r.get("read_only_override")) == "true" and value(r.get("read_only")) == "true" for r in rows)
    d = dictionary(run, "problem", "state")
    ro = ro or bool(d and value(d.get("read_only")) == "true")
    if ro:
        return Result("P3", "FALLBACK", "problem.state is read-only to the Table API: pm-agent's state API is needed "
                      "(ADR 0009, owner PR P3)", {"overrides": rows})
    return Result("P3", "PASS", "problem.state is not read-only: no instance change needed", {"overrides": rows})


def p4(run: ProbeRun) -> Result:
    # Problem models are prb_model rows (extends sttrm_model); each has sttrm_state rows, and transitions link a
    # from_state to a to_state (dictionary read on dev181865, 2026-11-19).
    models = run.admin.list("prb_model", "", ["sys_id", "name"], purpose="metadata: problem state models")
    if not models:
        return Result("P4", "INCONCLUSIVE", "no prb_model row was readable; check the problem state model in the UI", {})
    ids = ",".join(m["sys_id"] for m in models)
    states = run.admin.count("sttrm_state", f"sttrm_modelIN{ids}", purpose="metadata: problem model states")
    n = run.admin.count("sttrm_state_transition", f"from_state.sttrm_modelIN{ids}", purpose="metadata: problem transitions")
    return Result("P4", "PASS" if n else "INCONCLUSIVE", f"{len(models)} problem state model(s), {states} states, {n} transitions",
                  {"models": [m.get("name") for m in models], "states": states, "transitions": n})


def p5(run: ProbeRun) -> Result:
    kb = run.admin.list("kb_knowledge_base", "title=Known Error", ["sys_id", "title", "active", "workflow_publish"],
                        purpose="metadata: Known Error KB", display=True)
    template = run.admin.count("sys_db_object", "name=kb_template_known_error_article", purpose="metadata: KE template")
    facts = {"kb": kb, "template_table": bool(template)}
    if kb and template and value(kb[0].get("active")) == "true":
        return Result("P5", "PASS", "the Known Error KB and the known error article template exist; publishing is "
                      "exercised in phase 3/4", facts)
    return Result("P5", "FALLBACK", "Known Error KB or template missing: another KB the problem identity can "
                  "contribute to (END_TO_END_ITSM.md §11)", facts)


def p6(run: ProbeRun) -> Result:
    inc = run.incident("P6 incident")
    group = run.admin.list("sys_user_group", "nameSTARTSWITHSYN^active=true", ["sys_id", "name"],
                           purpose="metadata: a SYN group", limit=1)
    if not group:
        return Result("P6", "INCONCLUSIVE", "no active SYN group to assign to (is the Larkspur seed loaded?)", {})
    me = run.identity("incident")
    status, _ = me.update("incident", inc, {"assignment_group": group[0]["sys_id"]}, purpose="P6 assign incident")
    got = value(run.admin.get("incident", inc, ["assignment_group"], purpose="P6 read back").get("assignment_group"))
    c_status, created = me.request("POST", "/api/sn_chg_rest/change/normal", purpose="P6 change create must be refused",
                                   json={"short_description": f"{run.tag} P6 must not exist", "correlation_id": run.tag})
    chg = value((created or {}).get("sys_id")) if isinstance(created, dict) else ""
    if chg:
        run.changes.append(chg)
    facts = {"assign_status": status, "assigned": got == group[0]["sys_id"], "change_create_status": c_status}
    if got == group[0]["sys_id"] and c_status in REFUSED:
        return Result("P6", "PASS", "the incident identity assigns incidents and cannot create changes", facts)
    return Result("P6", "FALLBACK", "role set needs adjusting (smallest role that unblocks, never admin)", facts)


def p7(run: ProbeRun) -> Result:
    me = run.identity("problem")
    status, row = me.create("problem", {"short_description": f"{run.tag} P7 problem", "correlation_id": run.tag},
                            purpose="P7 create problem")
    prb = value(row.get("sys_id"))
    if prb:
        run.created.append(("problem", prb))
    n_status, _ = me.update("problem", prb, {"cause_notes": "P7 probe"}, purpose="P7 write cause notes") if prb else (0, {})
    c_status, created = me.request("POST", "/api/sn_chg_rest/change/normal", purpose="P7 change create must be refused",
                                   json={"short_description": f"{run.tag} P7 must not exist", "correlation_id": run.tag})
    chg = value((created or {}).get("sys_id")) if isinstance(created, dict) else ""
    if chg:
        run.changes.append(chg)
    facts = {"create_status": status, "cause_notes_status": n_status, "change_create_status": c_status}
    if prb and n_status == 200 and c_status in REFUSED:
        return Result("P7", "PASS", "the problem identity works problems and cannot create changes", facts)
    return Result("P7", "FALLBACK", "role set needs adjusting (separation of duties, §3.5)", facts)


def p8(run: ProbeRun) -> Result:
    prb = run.problem("P8 problem")
    before = value(run.admin.get("problem", prb, ["cause_notes"], purpose="P8 read before").get("cause_notes"))
    status, _ = run.identity("change").update("problem", prb, {"cause_notes": "P8 must not be written"},
                                              purpose="P8 diagnosis write must be refused")
    after = value(run.admin.get("problem", prb, ["cause_notes"], purpose="P8 read back").get("cause_notes"))
    facts = {"status": status, "unchanged": after == before}
    if refused_or_unchanged(status, after, before):
        return Result("P8", "PASS", "the change identity cannot change a problem's diagnosis", facts)
    return Result("P8", "FALLBACK", "the change roles can write problems: enforce in the adapter and record it", facts)


def _wait_state(run: ProbeRun, chg: str, target: str, tries: int = 15) -> str:
    state = ""
    for _ in range(tries):
        state = value(run.admin.get("change_request", chg, ["state"], purpose="P9 wait for state").get("state"))
        if state == target:
            break
        run.sleep(2)
    return state


def _own_row(run: ProbeRun, chg: str) -> dict | None:
    me = run.identity("approver")
    rows = me.list("sysapproval_approver", f"sysapproval={chg}^approver={run.users['approver']['sys_id']}^state=requested",
                   ["sys_id", "state", "approver"], purpose="P9 read own approval row")
    return rows[0] if rows else None


def p9(run: ProbeRun) -> Result:
    requester, approver = run.identity("change"), run.identity("approver")
    group = run.one("sys_user_group", "name=Change Management", "Change Management")
    status, created = requester.request("POST", "/api/sn_chg_rest/change/normal", purpose="P9 create normal change",
                                        json={"short_description": f"{run.tag} P9 approval probe", "correlation_id": run.tag,
                                              "assignment_group": group})
    chg = value((created or {}).get("sys_id")) if isinstance(created, dict) else ""
    if not chg:
        return Result("P9", "INCONCLUSIVE", f"the change identity could not create a probe change (HTTP {status})", {})
    run.changes.append(chg)
    requester.request("PATCH", f"/api/sn_chg_rest/change/normal/{chg}", purpose="P9 move to Assess",
                      json={"state": CHANGE_STATES["assess"]})
    facts: dict = {"assess": _wait_state(run, chg, CHANGE_STATES["assess"])}
    run.sleep(2)
    # negative checks first: another member's row, and the requester approving
    others = run.admin.list("sysapproval_approver", f"sysapproval={chg}^state=requested^approver!={run.users['approver']['sys_id']}",
                            ["sys_id"], purpose="P9 another approver's row", limit=1)
    if others:
        s1, _ = approver.update("sysapproval_approver", others[0]["sys_id"], {"state": "approved"},
                                purpose="P9 approve someone else's row: must be refused")
        s2, _ = requester.update("sysapproval_approver", others[0]["sys_id"], {"state": "approved"},
                                 purpose="P9 requester approving: must be refused")
        st = value(run.admin.get("sysapproval_approver", others[0]["sys_id"], ["state"], purpose="P9 read back").get("state"))
        facts.update(other_row_status=s1, requester_status=s2, other_row_state=st)
        if st != "requested":
            return Result("P9", "FAIL", "an identity approved a row that is not its own: separation of duties does not "
                          "hold with platform ACLs alone; stop and ask the owners", facts)
    for step, nxt in (("assess", "authorize"), ("authorize", "scheduled")):
        row = None
        for _ in range(10):
            row = _own_row(run, chg)
            if row:
                break
            run.sleep(2)
        if not row:
            facts[f"{step}_row"] = "none"
            return Result("P9", "FALLBACK", f"no approval row addressed to the approver at {step}: membership did not "
                          "produce a row (§5.2 fallback)", facts)
        s, _ = approver.update("sysapproval_approver", row["sys_id"],
                               {"state": "approved", "comments": f"{run.tag} probe approval at {step}"},
                               purpose=f"P9 approve own row at {step}")
        facts[f"{step}_status"] = s
        facts[nxt] = _wait_state(run, chg, CHANGE_STATES[nxt])
        if facts[nxt] != CHANGE_STATES[nxt]:
            return Result("P9", "FALLBACK", f"approving its own row at {step} did not move the change (HTTP {s}); "
                          "smallest role that unblocks, never admin (§5.2)", facts)
    return Result("P9", "PASS", "the approver identity approved its own rows at Assess and Authorize and the change "
                  "reached Scheduled; other rows were refused", facts)


def p10(run: ProbeRun) -> Result:
    admin_rows = [r for r in run.audit.rows if r.get("identity") == "admin"]
    stray = [r for r in admin_rows if not str(r.get("record", "")).startswith(("setup:", "cleanup:", "metadata:", "P"))]
    # "P.." purposes as admin are read-backs; they only read.
    writes = [r for r in admin_rows if str(r.get("record", "")).startswith("P") and not r["action"].startswith("GET")]
    if stray or writes:
        return Result("P10", "FAIL", "admin made a request outside setup, cleanup and read-backs",
                      {"stray": len(stray), "writes": len(writes)})
    return Result("P10", "PASS", f"admin made {len(admin_rows)} requests, all setup, cleanup, metadata or read-backs", {})


def p11(run: ProbeRun) -> Result:
    rows = run.admin.list("cmdb_ci", "nameSTARTSWITHsyn-", ["sys_class_name"], purpose="metadata: Larkspur CI classes",
                          limit=1000)
    classes = sorted({value(r.get("sys_class_name")) for r in rows})
    attrs = {}
    for cls in classes:
        attrs[cls] = [a for a in ("firmware_version", "os_version", "os", "model_id")
                      if run.admin.count("sys_dictionary", f"name={cls}^element={a}", purpose=f"metadata: {cls}.{a}")]
    facts = {"cis": len(rows), "classes": attrs}
    if not rows:
        return Result("P11", "INCONCLUSIVE", "no syn- CIs found (is the Larkspur seed loaded?)", facts)
    has = any(attrs.values())
    return Result("P11", "PASS" if has else "FALLBACK",
                  "some Larkspur CI classes carry attributes RCA can use" if has else
                  "no class carries firmware/OS attributes: plant evidence in work notes only (§11)", facts)


def p12(run: ProbeRun) -> Result:
    codes = choices(run, "incident", "close_code")
    hit = [c for c in codes if any(w in (c["label"] + c["value"]).lower() for w in ("problem", "workaround", "known error"))]
    facts = {"close_codes": codes, "problem_or_workaround": hit}
    if not codes:
        return Result("P12", "FAIL", "no incident close codes readable", facts)
    return Result("P12", "PASS" if hit else "FALLBACK",
                  f"close code for a known-error workaround: {hit[0]['label']}" if hit else
                  "no problem/workaround close code: use an existing code plus close notes (§11)", facts)


def p13(run: ProbeRun) -> Result:
    codes = choices(run, "incident", "close_code")
    if not codes:
        return Result("P13", "INCONCLUSIVE", "no close code to resolve the probe incident with", {})
    prb = run.problem("P13 problem")
    inc = run.incident("P13 resolved incident", state="6", close_code=codes[0]["value"], close_notes="probe")
    status, _ = run.identity("problem").update("incident", inc, {"parent": prb}, purpose="P13 link a resolved incident")
    got = value(run.admin.get("incident", inc, ["parent", "state"], purpose="P13 read back").get("parent"))
    facts = {"status": status, "linked": got == prb}
    if got == prb:
        return Result("P13", "PASS", "a resolved incident can be linked by the problem identity (no admin exception)", facts)
    return Result("P13", "FALLBACK", "resolved incidents cannot be linked by the problem identity: link them before "
                  "they resolve, or keep pm-agent's admin exception (recorded)", facts)


def p14(run: ProbeRun) -> Result:
    states = [c["value"] for c in choices(run, "kb_knowledge", "workflow_state")]
    script = run.admin.list("sys_script_include", "name=KnowledgeUIAction", ["sys_id", "script"],
                            purpose="metadata: KnowledgeUIAction", limit=1)
    has_retire = bool(script and "retire" in value(script[0].get("script")).lower())
    facts = {"workflow_states": states, "retire_in_KnowledgeUIAction": has_retire}
    if "retired" in states and has_retire:
        return Result("P14", "PASS", "articles can be retired through KnowledgeUIAction; exercised in phase 4", facts)
    return Result("P14", "FALLBACK", "no retire path found: leave the article published with a 'retired by "
                  "closure' note (§11)", facts)


def p15(run: ProbeRun) -> Result:
    counts = {p: {t: run.admin.count(t, f"correlation_idSTARTSWITH{p}", purpose=f"metadata: count {p}")
                  for t in ("incident", "problem", "change_request")} for p in PREFIXES}
    counts["[SYN] description"] = {"incident": run.admin.count("incident", "descriptionSTARTSWITH[SYN]",
                                                               purpose="metadata: count [SYN]")}
    e2e = sum(counts["SYN-E2E-"].values())
    if e2e:
        return Result("P15", "FAIL", f"{e2e} SYN-E2E- records already exist on the instance before any run", counts)
    return Result("P15", "PASS", "no SYN-E2E- records yet; the run tag is free and outside every other prefix", counts)


R, T = "read", "temp"
PROBES = [
    Probe("P0", "the change repository's Larkspur seed is on this instance", R, (),
          ("count SYN-CHG-/SYN-OPEN-/SYN-REL- changes, SYN-INC- incidents, syn- CIs and 'SYN Tier-' schedules",
           "if none: skip every other probe"), p0),
    Probe("P1", "incident.parent links an incident to a problem", T, ("problem",),
          ("read sys_dictionary for incident.parent", "create a probe problem and incident (admin)",
           "as the problem identity set incident.parent", "read back as admin"), p1),
    Probe("P2", "problem fields and the fix_applied resolution code exist", R, (),
          ("read sys_dictionary for rfc, cause_notes, fix_notes, workaround, known_error, primary_known_error_article, "
           "resolution_code", "read sys_choice problem.resolution_code"), p2),
    Probe("P3", "problem.state read-only to the Table API?", R, (),
          ("read sys_dictionary_override for problem.state", "read sys_dictionary problem.state read_only"), p3),
    Probe("P4", "problem state model and transitions", R, (),
          ("read prb_model (the problem state models)", "count their sttrm_state rows and sttrm_state_transition rows"), p4),
    Probe("P5", "Known Error KB and article template", R, (),
          ("read kb_knowledge_base 'Known Error'", "check sys_db_object kb_template_known_error_article"), p5),
    Probe("P6", "incident identity: assigns incidents, cannot create changes", T, ("incident",),
          ("create a probe incident (admin)", "as the incident identity set assignment_group to a SYN group",
           "as the incident identity POST /api/sn_chg_rest/change/normal (expect 401/403)"), p6),
    Probe("P7", "problem identity: works problems, cannot create changes", T, ("problem",),
          ("as the problem identity create a probe problem and write cause_notes",
           "as the problem identity POST /api/sn_chg_rest/change/normal (expect 401/403)"), p7),
    Probe("P8", "change identity cannot change a diagnosis", T, ("change",),
          ("create a probe problem (admin)", "as the change identity PATCH problem.cause_notes (expect refused)",
           "read back as admin"), p8),
    Probe("P9", "approver identity approves its own rows; nobody else can", T, ("change", "approver"),
          ("create the approver user in Change Management and CAB Approval (membership rows only)",
           "as the change identity create a normal change for Change Management and move it to Assess",
           "approver PATCHes another member's row, requester PATCHes a row (both expect refused)",
           "approver approves its own row at Assess, change reaches Authorize",
           "approver approves its own row at Authorize, change reaches Scheduled",
           "delete the change, its approvals, groups, tasks and links (admin)"), p9),
    Probe("P10", "admin is used only for setup, cleanup and metadata", R, (),
          ("check this run's own audit rows: every admin request is setup, cleanup, metadata or a read-back",), p10),
    Probe("P11", "Larkspur CI classes and their RCA attributes", R, (),
          ("read the classes of syn- CIs", "check firmware_version, os_version, os, model_id in sys_dictionary"), p11),
    Probe("P12", "incident close code for a known-error workaround", R, (),
          ("read sys_choice incident.close_code",), p12),
    Probe("P13", "a resolved incident can be linked by the problem identity", T, ("problem",),
          ("create a probe problem and a Resolved probe incident (admin)",
           "as the problem identity set incident.parent", "read back as admin"), p13),
    Probe("P14", "known error articles can be retired", R, (),
          ("read sys_choice kb_knowledge.workflow_state", "read KnowledgeUIAction for a retire function"), p14),
    Probe("P15", "run-tag prefixes do not collide", R, (),
          (f"count incident, problem, change_request for each prefix {', '.join(PREFIXES)} and '[SYN]' descriptions",),
          p15),
]
BY_ID = {p.id: p for p in PROBES}
ORDER = [p.id for p in PROBES if p.kind == R and p.id != "P10"] + [p.id for p in PROBES if p.kind == T] + ["P10"]


def run_probes(ids: list[str], run: ProbeRun) -> tuple[list[Result], list[str], dict[str, int]]:
    results = []
    try:
        for pid in [i for i in ORDER if i in ids]:
            if results and results[0].id == "P0" and results[0].status != "PASS":
                results.append(Result(pid, "INCONCLUSIVE", "skipped: P0 found no complete Larkspur seed"))
                continue
            try:
                results.append(BY_ID[pid].fn(run))
            except SNError as e:
                results.append(Result(pid, "INCONCLUSIVE", f"stopped: {e}"))
    finally:
        errors = run.cleanup() if (run.created or run.changes) else []
    residue = run.residue() if any(BY_ID[i].kind == T for i in ids) else {}
    return results, errors, residue
