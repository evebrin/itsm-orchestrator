import json

import pytest
from dotenv import dotenv_values

from itsm.data import load
from itsm.data.generate import plan
from itsm.platform.audit import Audit
from itsm.platform.sn import SNClient
from itsm.probes import APPROVER_GROUPS, ROLES
from tests.unit.fake_instance import FakeInstance

PDI = "https://dev000001.service-now.com"
RUN = "20261119-1530"


def larkspur_instance(drop_ci=None):
    p = plan()
    cis = sorted({r["cmdb_ci"] for r in p["incidents"] if r["cmdb_ci"]} - {drop_ci})
    groups = sorted({r["assignment_group"] for r in p["incidents"]} | set(APPROVER_GROUPS))
    return FakeInstance({
        "cmdb_ci": [{"sys_id": f"ci{i}", "name": n} for i, n in enumerate(cis)],
        "cmdb_ci_service": [{"sys_id": f"svc{i}", "name": n}
                            for i, n in enumerate(sorted({r["service"] for r in p["incidents"] if r["service"]}))],
        "sys_user_group": [{"sys_id": f"g{i}", "name": n} for i, n in enumerate(groups)],
        "sys_user": [{"sys_id": f"u{i}", "user_name": n} for i, n in enumerate(sorted({r["caller"] for r in p["incidents"]}))]
                    + [{"sys_id": "admin", "user_name": "admin"}],
        "sys_user_role": [{"sys_id": f"r-{n}", "name": n} for n in sorted({x for v in ROLES.values() for x in v})],
        "sys_choice": [{"name": "incident", "element": "state", "label": "Resolved", "value": "6", "inactive": "false"},
                       {"name": "incident", "element": "close_code", "label": "Workaround provided", "value": "Workaround provided",
                        "inactive": "false"},
                       {"name": "incident", "element": "close_code", "label": "Solution provided", "value": "Solution provided",
                        "inactive": "false"}],
        # records this project did not create, one of them with a look-alike tag
        "incident": [{"sys_id": "other1", "correlation_id": "SYN-INC-0001"},
                     {"sys_id": "other2", "correlation_id": f"SYN-E2E-{RUN}0"}],
        "kb_knowledge": [{"sys_id": "kb1", "short_description": "Someone else's article"}],
    })


def admin_for(instance, tmp_path):
    return SNClient(PDI, "admin", "pw", identity="admin", audit=Audit(tmp_path / "a.jsonl"), session=instance)


def test_seed_check_and_teardown_leave_nothing_and_touch_nothing_else(tmp_path, capsys):
    inst, env = larkspur_instance(), tmp_path / ".env"
    env.write_text("SN_INSTANCE_URL=https://dev000001.service-now.com\nSN_ADMIN_PASSWORD=pw\n")
    admin = admin_for(inst, tmp_path)
    m = load.seed(admin, RUN, env_path=env, var=tmp_path / "var")

    history = [r for r in plan()["incidents"] if r["phase"] == "history"]
    ours = inst.rows("incident", f"correlation_id=SYN-E2E-{RUN}")
    assert len(ours) == len(history) == len(m["incidents"]) and m["complete"]
    assert all(r["state"] == "6" and r["close_notes"] and r["opened_at"] for r in ours)
    assert all(ok for _, ok, _ in load.check(admin, RUN, var=tmp_path / "var"))

    users = inst.rows("sys_user", "user_nameSTARTSWITHsyn.svc.e2e_")
    assert sorted(u["user_name"] for u in users) == [f"syn.svc.e2e_{d}" for d in ("approver", "incident", "problem")]
    assert all(u["web_service_access_only"] == "true" for u in users)
    approver = next(u for u in users if u["user_name"].endswith("approver"))
    assert len(inst.rows("sys_user_grmember", f"user={approver['sys_id']}")) >= len(APPROVER_GROUPS)

    saved = dotenv_values(env)
    assert saved["SN_ADMIN_PASSWORD"] == "pw" and saved["SN_APPROVER_USER"] == "syn.svc.e2e_approver"
    assert saved["SN_APPROVER_PASSWORD"] and saved["SN_APPROVER_PASSWORD"] not in capsys.readouterr().out
    assert saved["SN_APPROVER_PASSWORD"] not in (tmp_path / "a.jsonl").read_text()
    assert saved["SN_APPROVER_PASSWORD"] not in (tmp_path / "var" / f"seed_{RUN}.json").read_text()

    out = load.teardown(admin, RUN, var=tmp_path / "var")
    assert not any(out["left"].values()) and all(out["untagged_unchanged"].values())
    assert out["deleted"]["incident"] == len(history) and out["deleted"]["sys_user"] == 3
    assert [r["sys_id"] for r in inst.tables["incident"]] == ["other1", "other2"]   # look-alike tag untouched
    assert not inst.rows("sys_user_has_role") and not inst.rows("sys_user_grmember")
    assert (tmp_path / "var" / f"seed_{RUN}.torn-down.json").exists()


def test_a_run_is_seeded_once(tmp_path):
    inst = larkspur_instance()
    admin = admin_for(inst, tmp_path)
    load.seed(admin, RUN, env_path=tmp_path / ".env", var=tmp_path / "var")
    with pytest.raises(load.SeedError, match="seeded before"):
        load.seed(admin, RUN, env_path=tmp_path / ".env", var=tmp_path / "var")


def test_a_missing_larkspur_ci_stops_before_any_write_and_teardown_still_works(tmp_path):
    inst = larkspur_instance(drop_ci="syn-ful-db-prd-01")
    admin = admin_for(inst, tmp_path)
    with pytest.raises(load.SeedError, match="cmdb_ci rows not found"):
        load.seed(admin, RUN, env_path=tmp_path / ".env", var=tmp_path / "var")
    assert not [c for c in inst.calls if c[0] in ("POST", "PATCH", "DELETE")]
    m = json.loads((tmp_path / "var" / f"seed_{RUN}.json").read_text())
    assert not m["complete"] and not m["identities"]
    assert not any(load.teardown(admin, RUN, var=tmp_path / "var")["left"].values())


def test_run_ids_are_checked():
    with pytest.raises(load.SeedError):
        load.tag("../x")
    assert load.tag(RUN) == "SYN-E2E-20261119-1530"


def test_seed_dry_run_sends_no_request(monkeypatch, capsys):
    import requests

    from itsm import __main__ as cli

    def boom(*a, **k):
        raise AssertionError("a request was sent")
    monkeypatch.setattr(requests.Session, "request", boom)
    assert cli.main(["seed", "--run-id", RUN, "--dry-run"]) == 0
    assert "no request was sent" in capsys.readouterr().out
