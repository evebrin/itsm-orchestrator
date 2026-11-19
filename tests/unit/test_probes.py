import requests

from itsm import __main__ as cli
from itsm.platform.audit import Audit
from itsm.platform.settings import Settings
from itsm.probes import BY_ID, ORDER, PROBES, ProbeRun, p0, p3, p10, run_probes
from tests.unit.fakes import FakeResp, FakeSession

PDI = "https://dev000001.service-now.com"


def run_with(tmp_path, routes):
    s = Settings(PDI, {"SN_INSTANCE_URL": PDI, "SN_ADMIN_USER": "admin", "SN_ADMIN_PASSWORD": "pw"})
    session = FakeSession(routes)
    return ProbeRun(s, Audit(tmp_path / "a.jsonl"), session_factory=lambda: session, sleep=lambda s: None), session


def test_catalog_has_p0_to_p15_once_with_plans():
    assert [p.id for p in PROBES] == [f"P{i}" for i in range(0, 16)]
    assert sorted(ORDER, key=lambda i: int(i[1:])) == [p.id for p in PROBES]
    assert ORDER[0] == "P0" and ORDER[-1] == "P10"
    assert all(p.plan and p.kind in ("read", "temp") and callable(p.fn) for p in PROBES)


def test_dry_run_sends_no_request(monkeypatch, capsys):
    def boom(*a, **k):
        raise AssertionError("a request was sent")
    monkeypatch.setattr(requests.Session, "request", boom)
    assert cli.main(["probe", "--all", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "no request was sent" in out and all(p.id in out for p in PROBES)


def test_p3_reports_the_state_api_fallback_when_read_only(tmp_path):
    run, _ = run_with(tmp_path, {("GET", "/api/now/table/sys_dictionary_override"):
                                 FakeResp(200, [{"read_only_override": "true", "read_only": "true"}])})
    assert p3(run).status == "FALLBACK"


def test_temp_probe_cleans_up_in_reverse_and_checks_residue(tmp_path):
    run, session = run_with(tmp_path, {("GET", "/api/now/table/incident"): FakeResp(200, [{"parent": "nope"}]),
                                       ("GET", "/api/now/table/sys_user_role"): FakeResp(200, [{"sys_id": "role1"}])})
    results, errors, residue = run_probes(["P1"], run)
    deletes = [c[1] for c in session.calls if c[0] == "DELETE"]
    creates = [c[1] for c in session.calls if c[0] == "POST"]
    assert results[0].status == "FAIL"            # the fake never stores the link
    assert [d.rsplit("/", 1)[0] for d in deletes] == list(reversed(creates))  # children first, problem last
    assert not errors and set(residue) == {"incident", "problem", "change_request", "sys_user"}
    # the problem identity, not admin, made the link attempt
    patch = [c for c in session.calls if c[0] == "PATCH"][0]
    assert patch[4] == "syn.probe.e2e_problem"


def test_p10_flags_admin_writes_outside_setup(tmp_path):
    run, _ = run_with(tmp_path, {})
    run.audit.write(identity="admin", action="PATCH /api/now/table/incident/x", record="P1 sneaky write")
    assert p10(run).status == "FAIL"
    assert BY_ID["P10"].kind == "read"


def test_a_stopped_probe_is_inconclusive_and_still_cleans_up(tmp_path):
    run, session = run_with(tmp_path, {})  # no role rows: the temporary user cannot be given its role
    results, errors, _ = run_probes(["P1"], run)
    assert results[0].status == "INCONCLUSIVE" and "sys_user_role" in results[0].detail
    assert len([c for c in session.calls if c[0] == "DELETE"]) == len([c for c in session.calls if c[0] == "POST"])


def stats(n):
    return {("GET", f"/api/now/stats/{t}"): FakeResp(200, {"stats": {"count": str(n)}})
            for t in ("change_request", "incident", "cmdb_ci", "cmn_schedule")}


def test_p0_passes_when_the_larkspur_seed_is_present(tmp_path):
    run, session = run_with(tmp_path, stats(1500))
    r = p0(run)
    assert r.status == "PASS" and r.facts["seeded changes"] == 1500
    assert all(c[0] == "GET" for c in session.calls)  # counts only


def test_without_the_seed_p0_fails_and_every_other_probe_is_skipped(tmp_path):
    run, session = run_with(tmp_path, stats(0))
    results, errors, _ = run_probes(["P0", "P2", "P1"], run)
    assert [r.status for r in results] == ["FAIL", "INCONCLUSIVE", "INCONCLUSIVE"]
    assert "seed 42" in results[0].detail and all("skipped" in r.detail for r in results[1:])
    assert not errors and all(c[0] == "GET" for c in session.calls)  # nothing created, nothing to clean up
