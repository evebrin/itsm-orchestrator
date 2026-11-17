"""Phase 1a check: replay rule R1 on pm-agent's reference run (read-only, on the PDI that run lives on).

Runs pm-agent's evidence gathering and both RCA engines for every problem in the run, applies R1, and only
then compares with the answer key. No ServiceNow write, no gate. The LLM is called once per problem.

pm-agent's own settings (.env, config/instance.json, runs/) are read from its working copy (`--pm-home`,
default ~/pm-agent); its code is imported from the pinned submodule. Values are never printed.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import dotenv_values

from itsm import vendor_paths
from itsm.agents.rca_confirm import confirm

ROOT = Path(__file__).resolve().parents[1]


def replay(run_id: str, pm_home: Path) -> dict:
    for k, v in dotenv_values(pm_home / ".env").items():  # pm-agent reads os.environ; nothing is printed
        if v and k not in os.environ:
            os.environ[k] = v
    vendor_paths.activate()
    import config as pm_config  # vendor/pm-agent
    import llm
    import rca_agent
    from sn_client import SNClient

    pm_config.INSTANCE_FILE = pm_home / "config" / "instance.json"
    pm_config.RUNS_DIR = pm_home / "runs"
    from cm_agents.enablement.guard import INJECTION_MARKERS

    ctx = pm_config.load_context(run_id)
    key = json.loads((pm_home / "runs" / f"{run_id}_answer_key.json").read_text())["patterns"]
    svc = SNClient()
    all_incidents, cis = rca_agent.load_world(svc, ctx["tag"])
    problems = svc.get_all("problem", f"correlation_id={ctx['tag']}", fields=["sys_id", "number", "short_description", "cmdb_ci"])
    rows = []
    for p in sorted(problems, key=lambda p: p["number"]):
        ev = rca_agent.gather(svc, p, ctx["tag"], all_incidents, cis)
        rule = rca_agent.analyse(ev, "fallback")
        hyp = rca_agent.analyse(ev, "llm")
        ok, criteria = confirm(rule, hyp, base_markers=INJECTION_MARKERS)
        # evaluation only, after the decision
        pid = rca_agent.match_pattern(key, {i["number"] for i in ev["incidents"]})
        rows.append({"problem": p["number"], "planted": pid or "unplanted", "confirmed": ok, **criteria,
                     "rule_root_cause": rule["root_cause"], "llm_root_cause": hyp["root_cause"],
                     "llm_engine": hyp.get("engine", "")})
    planted = [r for r in rows if r["planted"] != "unplanted"]
    out = {"run_id": run_id, "llm": llm.describe() if llm.available() else "unavailable", "rows": rows,
           "planted_confirmed": sum(r["confirmed"] for r in planted), "planted": len(planted),
           "unplanted_held": sum(not r["confirmed"] for r in rows if r["planted"] == "unplanted"),
           "unplanted": len(rows) - len(planted)}
    out["passed"] = out["planted_confirmed"] == out["planted"] and out["unplanted_held"] == out["unplanted"]
    (ROOT / "var").mkdir(exist_ok=True)
    (ROOT / "var" / f"r1_replay_{run_id}.json").write_text(json.dumps(out, indent=2))
    return out


def print_report(out: dict) -> None:
    print(f"R1 replay on run {out['run_id']} (LLM: {out['llm']})")
    print(f"{'problem':11} {'planted':10} {'rule engine':20} {'LLM':20} {'cited':6} {'markers':8} decision")
    for r in out["rows"]:
        print(f"{r['problem']:11} {r['planted']:10} {str(r['rule_engine_category']):20} {str(r['llm_category']):20} "
              f"{'yes' if r['cited_linked'] else 'no':6} {len(r['injection_markers']):<8} "
              f"{'CONFIRMED' if r['confirmed'] else 'HELD'}")
    print(f"\nplanted confirmed {out['planted_confirmed']} of {out['planted']}; "
          f"unplanted held {out['unplanted_held']} of {out['unplanted']}")
    print(f"RESULT: {'R1 REPLAY OK' if out['passed'] else 'R1 REPLAY DIFFERS FROM THE EXPECTATION'}")
