"""`itsm run --dry-run --case <key>`: phase 3's thin slice (END_TO_END_ITSM.md §13).

Drives one case of a seeded run through the case graph with every write planned and none sent: reads come from
the instance, every identity's client is a dry-run client. The case is picked by key (planted-a..d or decoy) from
the run's ground truth; that choice is only which case to drive, never an input to a decision.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from itsm.adapters import pm
from itsm.case import Ctx, build
from itsm.data import load
from itsm.data.generate import plan as world_plan
from itsm.platform import policy, settings
from itsm.platform.audit import Audit
from itsm.platform.clock import Clock, parse_sn
from itsm.platform.settings import ROOT
from itsm.platform.sn import SNClient


def _llm_env(s: settings.Settings) -> None:
    """pm-agent's LLM settings from the orchestrator's (D9: xAI Grok), only when a real key is set."""
    key = s.values.get("XAI_API_KEY", "")
    if key and key != "replace-me":
        os.environ.setdefault("LLM_PROVIDER", "xai")
        os.environ.setdefault("LLM_MODEL", s.values.get("XAI_MODEL") or "")
        os.environ.setdefault("LLM_API_KEY", key)


def dry_run(run_id: str, case_key: str, var: Path = ROOT / "var") -> dict:
    s = settings.load(required=("SN_INSTANCE_URL", "SN_ADMIN_USER", "SN_ADMIN_PASSWORD", "SN_PROBLEM_USER",
                                "SN_PROBLEM_PASSWORD", "SN_INCIDENT_USER", "SN_INCIDENT_PASSWORD"))
    m = json.loads(load.manifest_path(run_id, var).read_text())
    tag = m["tag"]
    audit = Audit(var / f"audit_dryrun_{run_id}.jsonl", run_id=run_id)

    def client(user_key: str, identity: str) -> SNClient:
        return SNClient(s.instance, s.get(f"{user_key}_USER"), s.get(f"{user_key}_PASSWORD"), identity=identity,
                        audit=audit, secrets=s.secrets(), dry_run=True)

    clients = {"admin": client("SN_ADMIN", "admin"), "problem": client("SN_PROBLEM", s.get("SN_PROBLEM_USER")),
               "incident": client("SN_INCIDENT", s.get("SN_INCIDENT_USER"))}
    _llm_env(s)
    inst = pm.instance_file(clients["admin"], var / "pm_instance.json")
    with pm.use(inst, var / "pm-runs"):
        import detection_agent
        import llm

        view = pm.View(clients["problem"], "dry run")
        incidents = view.get_all("incident", f"correlation_id={tag}", fields=detection_agent.FIELDS)
        world = pm.world(view, tag)
        names = {k: v["name"] for k, v in world[1].items()}
        candidates = detection_agent.detect(incidents, names)
        gt = m["ground_truth"]
        target = gt["decoy"]["ci"] if case_key == "decoy" else gt["clusters"][case_key.removeprefix("planted-")]["ci"]
        cand = next((c for c in candidates if names.get(c["cmdb_ci"]) == target), None)
        if cand is None:
            return {"case": case_key, "error": f"detection found no candidate on {target}",
                    "candidates": [c["where"] for c in candidates]}
        ctx = Ctx(tag=tag, policy=policy.load(), clock=Clock(parse_sn(m["anchor"][:19].replace("T", " "))),
                  catalog=world_plan()["catalog"], clients=clients, view=view, world=world, llm=llm.available())
        case_id = f"{tag}-P01"
        final = build(ctx).invoke({"schema": "case/v1", "case_id": case_id, "run_id": run_id, "candidate": cand,
                                   "decisions": [], "terminal": None})
    sent = [r for r in audit.rows if not r["action"].startswith("GET") and r["result"] != "planned"]
    out = {"case": case_key, "case_id": case_id, "candidate": {k: cand[k] for k in ("id", "where", "incident_count",
                                                                                 "peak_14d", "confidence")},
           "llm": llm.describe() if ctx.llm else "unavailable", "terminal": final.get("terminal"),
           "decisions": final.get("decisions", []), "plan": ctx.plan,
           "reads": sum(1 for r in audit.rows if r["action"].startswith("GET")), "writes_sent": len(sent)}
    (var / f"dryrun_{run_id}_{case_key}.json").write_text(json.dumps(out, indent=1, default=str))
    return out


def print_report(out: dict) -> None:
    if out.get("error"):
        print(f"{out['case']}: {out['error']} (candidates: {out['candidates']})")
        return
    c = out["candidate"]
    print(f"dry run {out['case_id']} ({out['case']}): candidate {c['id']} on {c['where'].split(' / ')[0]}, "
          f"{c['incident_count']} incidents, confidence {c['confidence']}; LLM {out['llm']}")
    print("\ndecisions")
    for d in out["decisions"]:
        print(f"  {d['node']:13} {d['rule']:5} {d['result']}: {d['reason'][:110]}")
    print("\nplanned writes (none sent)")
    for p in out["plan"]:
        src = "" if p["source"] == "orchestrator" else f"  [{p['source']}]"
        print(f"  {p['stage']:18} {p['identity']:22} {p['action'][:58]}{src}")
    print(f"\nterminal: {out['terminal']}   reads: {out['reads']}   writes sent: {out['writes_sent']}")
    print("RESULT: " + ("DRY RUN OK (0 writes)" if out["writes_sent"] == 0 else "WRITES WERE SENT"))
