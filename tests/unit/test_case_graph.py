"""Phase 3 gate, offline: one planted case through every stage of the case graph, every write planned, none sent."""
import json
from datetime import UTC, datetime, timedelta
from unittest import mock

import pytest

from itsm.adapters import pm
from itsm.case import Ctx, build
from itsm.data.generate import plan
from itsm.platform import policy
from itsm.platform.audit import Audit
from itsm.platform.clock import Clock
from itsm.platform.sn import SNClient
from tests.unit.fake_instance import FakeInstance

PDI = "https://dev000001.service-now.com"
TAG = "SYN-E2E-20261120-0256"
NOTES = ["df -h on syn-ful-db-prd-01 shows /data at 96% used; /data/db_log is 41 GB.",
         "db_log keeps growing; no log rotation seems to run on syn-ful-db-prd-01.",
         "Same as last time: /data filled up by database logs, purged manually."]


def instance(n=8):
    t0 = datetime(2026, 10, 1, 14, tzinfo=UTC)
    incs = [{"sys_id": f"i{k}", "number": f"INC{k:04d}", "correlation_id": TAG, "short_description": "Fulfillment queries timing out",
             "opened_at": (t0 + timedelta(days=k)).strftime("%Y-%m-%d %H:%M:%S"), "cmdb_ci": "ci1", "business_service": "",
             "category": "database", "subcategory": "", "priority": "3", "caller_id": f"u{k % 3}", "close_code": "Workaround provided",
             "close_notes": NOTES[k % 3], "work_notes": NOTES[k % 3], "assignment_group": "g1", "state": "6"} for k in range(n)]
    return FakeInstance({"incident": incs, "cmdb_ci": [{"sys_id": "ci1", "name": "syn-ful-db-prd-01",
                                                        "sys_class_name": "cmdb_ci_db_instance"}]}), incs


def ctx_for(tmp_path, llm_on):
    inst, incs = instance()
    audit = Audit(tmp_path / "a.jsonl")
    clients = {k: SNClient(PDI, k, "pw", identity=f"syn.svc.e2e_{k}", audit=audit, session=inst, dry_run=True)
               for k in ("admin", "problem", "incident")}
    choices = tmp_path / "inst.json"
    code = {"value": "Workaround provided", "label": "Workaround provided"}
    choices.write_text(json.dumps({"choices": {"incident.close_code": [code]}}))
    view = pm.View(clients["problem"], "test")
    cand = {"id": "C1", "title": "Recurring database incidents on syn-ful-db-prd-01", "where": "syn-ful-db-prd-01",
            "incident_count": len(incs), "peak_14d": 8, "confidence": "High", "cmdb_ci": "ci1", "incidents": incs}
    def make(world):
        return Ctx(tag=TAG, policy=policy.load(), clock=Clock(datetime(2026, 10, 27, 5, tzinfo=UTC)),
                   catalog=plan()["catalog"], clients=clients, view=view, world=world, llm=llm_on)
    return inst, choices, cand, view, make


def run_case(tmp_path, llm_on):
    inst, choices, cand, view, make = ctx_for(tmp_path, llm_on)
    with pm.use(choices, tmp_path / "runs"):
        import rca_agent

        real = rca_agent.analyse

        def agreeing_llm(ev, engine):  # a stand-in LLM that names the rule engine's cause and cites linked incidents
            r = real(ev, "fallback")
            if engine == "llm":
                r = {**r, "engine": "llm test", "evidence": [i["number"] for i in ev["incidents"][:3]]}
            return r
        with mock.patch.object(rca_agent, "analyse", agreeing_llm):
            ctx = make(pm.world(view, TAG))
            final = build(ctx).invoke({"schema": "case/v1", "case_id": f"{TAG}-P01", "run_id": "x", "candidate": cand,
                                       "decisions": [], "terminal": None})
    return inst, ctx, final


def test_planted_case_reaches_closure_with_every_stage_planned_and_nothing_sent(tmp_path):
    inst, ctx, final = run_case(tmp_path, llm_on=True)
    assert final["terminal"] == "closed (dry run)"
    assert [d["node"] for d in final["decisions"]] == ["open_problem", "rca", "rca_confirm", "knowledge", "rfc", "change",
                                                       "approve", "go_no_go", "close"]
    assert {d["node"]: d["result"] for d in final["decisions"]}["rca_confirm"] == "confirmed"
    stages = {p["stage"] for p in ctx.plan}
    assert {"5 detect", "6 RCA", "7 confirm", "8 known error", "10 change", "11 approve", "12 go/no-go",
            "13 deploy, verify", "14 link back", "15 recurrence check", "16 close"} <= stages
    assert [c for c in inst.calls if c[0] != "GET"] == []                      # nothing but reads reached the instance
    approve = next(d for d in final["decisions"] if d["node"] == "approve")
    assert approve["criteria"]["c"] is True and approve["criteria"]["i"] is True  # catalog plans pass A1's checklist


def test_without_an_llm_r1_holds_and_later_stages_are_not_reached(tmp_path):
    inst, ctx, final = run_case(tmp_path, llm_on=False)
    assert final["terminal"] == "held_rca_unconfirmed"
    assert "8 known error" not in {p["stage"] for p in ctx.plan}
    assert [c for c in inst.calls if c[0] != "GET"] == []


@pytest.mark.parametrize("conf,terminal", [("Low", "rejected_not_a_problem")])
def test_low_confidence_cluster_is_not_opened(tmp_path, conf, terminal):
    inst, choices, cand, view, make = ctx_for(tmp_path, True)
    with pm.use(choices, tmp_path / "runs"):
        final = build(make(({}, {}))).invoke({"case_id": "c", "candidate": {**cand, "confidence": conf}, "decisions": []})
    assert final["terminal"] == terminal and not inst.calls
