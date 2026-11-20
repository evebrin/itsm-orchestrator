"""The case graph (END_TO_END_ITSM.md §7.1): one problem from detection to closure, stages 5-16 of §3.2.

`rca → rca_confirm → knowledge → rfc → change → approve → go_no_go → verify → close`, after `open_problem`, with a
conditional edge to a terminal state (§3.3) after every decision.

Phase 3 runs it as a **dry run** only: every ServiceNow read is real (dev181865, the seeded run), every write goes
through a dry-run client and is listed in the plan, never sent. The change repository's graph is not invoked in a
dry run, because its nodes write; its steps are listed as planned with what the orchestrator would pass to it.
Decisions are made by the rules (R1, A1, G1, C1) on the facts a dry run can know; a fact only the live run can read
(the change's risk tier, its conflicts) is shown as "decided at run time", never guessed.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from itsm.adapters import pm
from itsm.agents import rfc_builder
from itsm.agents.rca_confirm import confirm
from itsm.agents.rules import a1
from itsm.platform.clock import Clock
from itsm.platform.policy import Policy
from itsm.platform.sn import SNClient

CONFIDENCE_ORDER = ("Low", "Medium", "High")


class CaseState(TypedDict, total=False):
    schema: str
    case_id: str
    run_id: str
    candidate: dict
    problem_sys_id: str
    problem_number: str
    incident_sys_ids: list[str]
    mechanism: str | None
    request: dict | None
    decisions: list[dict]
    terminal: str | None


@dataclass
class Ctx:
    """Everything a node needs that is not case state (clients, policy, the planned-write log)."""
    tag: str
    policy: Policy
    clock: Clock
    catalog: list[dict]
    clients: dict[str, SNClient]          # incident, problem, admin (all dry-run in phase 3)
    view: pm.View
    world: tuple[list[dict], dict]
    llm: bool
    plan: list[dict] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)

    def note(self, stage: str, who: str, action: str, detail: str, source: str = "orchestrator") -> None:
        self.plan.append({"stage": stage, "identity": who, "action": action, "detail": detail, "source": source})

    def collect(self, stage: str) -> None:
        """Move the dry-run clients' planned writes into the plan under `stage`."""
        for c in self.clients.values():
            for w in c.planned:
                body = {k: v for k, v in (w["json"] or {}).items() if k != "user_password"}
                self.note(stage, w["identity"], f"{w['method']} {w['path']}", f"{w['purpose']}: {json.dumps(body)[:220]}")
            c.planned.clear()


def _decide(state: CaseState, node: str, rule: str, result: str, reason: str, criteria: dict | None = None) -> list[dict]:
    return [*state.get("decisions", []), {"node": node, "rule": rule, "result": result, "reason": reason,
                                          "criteria": criteria or {}}]


def build(ctx: Ctx):
    prob, view = ctx.clients["problem"], ctx.view

    def open_problem(s: CaseState) -> CaseState:
        c = s["candidate"]
        need = ctx.policy.problem["min_confidence"]
        if CONFIDENCE_ORDER.index(c["confidence"]) < CONFIDENCE_ORDER.index(need):
            return {"decisions": _decide(s, "open_problem", "§4.1", "reject", f"confidence {c['confidence']} < {need}"),
                    "terminal": "rejected_not_a_problem"}
        _, row = prob.create("problem", {
            "short_description": f"[{s['case_id']}] {c['title']}", "correlation_id": s["case_id"], "cmdb_ci": c["cmdb_ci"],
            "description": f"Detected by trend analysis on {c['where']}: {c['incident_count']} incidents, peak "
                           f"{c['peak_14d']} in 14 days, confidence {c['confidence']}.",
            "work_notes": f"[agent:detect] opened by rule §4.1 (5+ in 14 days, confidence {c['confidence']} >= {need})."},
            purpose="stage 5: open problem")
        pid = row["sys_id"]
        ids = [i["sys_id"] for i in c["incidents"]]
        for i in ids:
            prob.update("incident", i, {"parent": pid}, purpose="stage 5: link incident to the problem")
        view.links[pid] = ids
        ctx.collect("5 detect")
        return {"problem_sys_id": pid, "problem_number": "DRYRUN", "incident_sys_ids": ids,
                "decisions": _decide(s, "open_problem", "§4.1", "open", f"confidence {c['confidence']} >= {need}")}

    def rca(s: CaseState) -> CaseState:
        import rca_agent

        all_incidents, cis = ctx.world
        p = {"sys_id": s["problem_sys_id"], "number": s["problem_number"], "cmdb_ci": s["candidate"]["cmdb_ci"],
             "short_description": s["candidate"]["title"]}
        ev = rca_agent.gather(view, p, s["case_id"], all_incidents, cis)
        rule = rca_agent.analyse(ev, "fallback")
        llm_r = rca_agent.analyse(ev, "llm") if ctx.llm else None
        ctx.evidence[s["case_id"]] = {"ev": ev, "rule": rule, "llm": llm_r}
        prob.update("problem", s["problem_sys_id"], {"work_notes": f"[agent:rca] rule engine: {rule['root_cause'][:300]}"
                    + (f"\nLLM: {llm_r['root_cause'][:300]}" if llm_r else "\nLLM: not called (unavailable)")},
                    purpose="stage 6: analysis note")
        ctx.collect("6 RCA")
        return {"decisions": _decide(s, "rca", "—", "analysed", f"{len(ev['incidents'])} linked incidents read")}

    def rca_confirm(s: CaseState) -> CaseState:
        from cm_agents.enablement.guard import INJECTION_MARKERS

        e = ctx.evidence[s["case_id"]]
        ok, crit = confirm(e["rule"], e["llm"], base_markers=INJECTION_MARKERS)
        if not ok:
            prob.update("problem", s["problem_sys_id"], {"work_notes": f"[agent:rca_confirm] R1 held: {json.dumps(crit)}"},
                        purpose="stage 7: R1 hold note")
            ctx.collect("7 confirm")
            return {"decisions": _decide(s, "rca_confirm", "R1", "hold", "root cause not confirmed", crit),
                    "terminal": "held_rca_unconfirmed"}
        mech = crit["rule_engine_category"]
        prob.update("problem", s["problem_sys_id"], {"cause_notes": e["rule"]["root_cause"], "workaround": e["rule"]["workaround"]},
                    purpose="stage 7: confirmed cause and workaround")
        prob.request("POST", "/api/<pm-agent state API>/move", purpose="stage 7: problem state -> Root Cause Analysis",
                     json={"sys_id": s["problem_sys_id"], "state": "Root Cause Analysis"})
        ctx.collect("7 confirm")
        return {"mechanism": mech, "decisions": _decide(s, "rca_confirm", "R1", "confirmed", mech, crit)}

    def knowledge(s: CaseState) -> CaseState:
        import knowledge_agent

        e = ctx.evidence[s["case_id"]]
        p = {"number": s["problem_number"], "short_description": s["candidate"]["title"],
             "cause_notes": e["rule"]["root_cause"], "workaround": e["rule"]["workaround"]}
        a = knowledge_agent.fallback(knowledge_agent.facts(p, e["ev"]))
        prob.create("kb_knowledge", {"short_description": f"[{s['case_id']}] Known error: {a['title']}",
                                     "kb_cause": a["cause"], "kb_workaround": " ".join(a["workaround_steps"]),
                                     "source": s["problem_sys_id"], "workflow_state": "draft"},
                    purpose="stage 8: known error article")
        prob.request("POST", "/api/<pm-agent state API>/publish_article", purpose="stage 8: publish the article",
                     json={"sys_id": "<article>"})
        prob.update("problem", s["problem_sys_id"], {"known_error": "true", "primary_known_error_article": "<article>"},
                    purpose="stage 8: mark known error")
        ctx.collect("8 known error")
        return {"decisions": _decide(s, "knowledge", "—", "published", "article text from the confirmed fields only")}

    def rfc(s: CaseState) -> CaseState:
        _, cis = ctx.world
        ci = cis.get(s["candidate"]["cmdb_ci"], {}).get("name", "")
        case = rfc_builder.Confirmed(s["case_id"], s["problem_number"], s["mechanism"] or "", ci, len(s["incident_sys_ids"]))
        req, why = rfc_builder.build(case, ctx.catalog, ctx.clock.sn())
        gaps = rfc_builder.complete(req, lambda n: prob.list("cmdb_ci", f"name={n}", ["sys_id"], purpose="stage 9: exact CI",
                                                             limit=5)) if req else [why]
        if gaps:
            return {"decisions": _decide(s, "rfc", "§4.3", "hold", "; ".join(gaps)), "terminal": "held_no_fix_plan"}
        return {"request": req, "decisions": _decide(s, "rfc", "§4.3", "ready", why)}

    def change(s: CaseState) -> CaseState:
        req = s["request"] or {}
        ctx.note("10 change", "syn.svc.change_agents", "start_change(request, thread_id=case id)",
                 f"summary {req.get('summary')!r}, CI {req.get('cis')}, {req.get('deployment_method')}, window "
                 f"{req.get('proposed_window')}", source="change repository (not invoked in a dry run)")
        ctx.note("10 change", "syn.svc.change_agents", "intake, scheduling, risk",
                 "creates the normal change (correlation_id = case id), affected CI, next maintenance window, risk score",
                 source="change repository (not invoked in a dry run)")
        prob.update("problem", s["problem_sys_id"], {"rfc": "<change>", "fix_notes": f"Fix {req.get('fix_catalog_id')}"},
                    purpose="stage 14: link the change to the problem")
        prob.request("POST", "/api/<pm-agent state API>/move", purpose="stage 14: problem state -> Fix in Progress",
                     json={"sys_id": s["problem_sys_id"], "state": "Fix in Progress"})
        ctx.collect("14 link back")
        return {"decisions": _decide(s, "change", "§4.3", "requested", "the change repository would create the change")}

    def approve(s: CaseState) -> CaseState:
        req = s["request"] or {}
        facts = {"kill_switch": ctx.policy.kill_switch(), "breaker_open": False,
                 "catalog_mechanism": next((c["mechanism"] for c in ctx.catalog if c["id"] == req.get("fix_catalog_id")), None),
                 "change": {"type": "normal", **{k: req.get(k) for k in ("implementation_plan", "backout_plan", "test_plan")}},
                 "problem": {"state": "Fix in Progress", "cause_notes": "confirmed", "confirmed_by_r1": True,
                             "mechanism": s["mechanism"]},
                 "approvals": {"service_today": 0, "run": 0}}
        d = a1(ctx.policy, facts)
        runtime = sorted(k for k, v in d.criteria.items() if v is None)
        result = d.result if d.result == "reject" or [k for k, v in d.criteria.items() if v is False] else \
            f"approve if run-time criteria {', '.join(runtime)} hold"
        for step in ("Assess (assignment group)", "Authorize (CAB Approval)"):
            ctx.note("11 approve", "syn.svc.e2e_approver", "PATCH sysapproval_approver state=approved + comment",
                     f"{step}: rule A1; {result}")
        return {"decisions": _decide(s, "approve", "A1", result, d.reason, d.criteria)}

    def go_no_go(s: CaseState) -> CaseState:
        ctx.note("12 go/no-go", "syn.svc.change_agents", "record_go_no_go (resume the change graph)",
                 "rule G1 at the planned start: inside the window, no new blocking conflict, breaker closed",
                 source="change repository (not invoked in a dry run)")
        ctx.note("13 deploy, verify", "syn.svc.change_agents", "deploy, verify, close the change",
                 "simulator thresholds from the change policy; on failure a u_caused_by incident",
                 source="change repository (not invoked in a dry run)")
        return {"decisions": _decide(s, "go_no_go", "G1", "decided at run time", "needs the approved planned window")}

    def close(s: CaseState) -> CaseState:
        ctx.note("15 recurrence check", "syn.svc.e2e_problem", "read the verification window",
                 "pm-agent window_end and recurrence: 14+ days, same CI or service and subcategory, similarity >= 0.10")
        prob.request("POST", "/api/<pm-agent state API>/move", purpose="stage 16: problem -> Resolved, then Closed fix_applied",
                     json={"sys_id": s["problem_sys_id"], "state": "Closed", "fields": {"resolution_code": "fix_applied"}})
        for i in s["incident_sys_ids"][:1]:
            prob.update("incident", i, {"work_notes": "[agent:closure_policy] problem closed, fix verified"},
                        purpose="stage 16: note on open linked incidents (each one still open at the time)")
        ctx.collect("16 close")
        return {"decisions": _decide(s, "close", "C1", "decided at run time", "needs the change outcome and the window"),
                "terminal": "closed (dry run)"}

    g = StateGraph(CaseState)
    order = [("open_problem", open_problem), ("rca", rca), ("rca_confirm", rca_confirm), ("knowledge", knowledge),
             ("rfc", rfc), ("change", change), ("approve", approve), ("go_no_go", go_no_go), ("close", close)]
    for name, fn in order:
        g.add_node(name, fn)
    g.set_entry_point("open_problem")
    for (name, _), (nxt, _) in zip(order, order[1:], strict=False):
        g.add_conditional_edges(name, lambda s, n=nxt: END if s.get("terminal") else n, {nxt: nxt, END: END})
    g.add_edge("close", END)
    return g.compile()
