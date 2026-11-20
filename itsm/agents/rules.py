"""Decision rules A1 (approve one change step), G1 (go/no-go) and C1 (close the problem), END_TO_END_ITSM.md §5.4,
§5.9, §5.10. Pure functions over facts the nodes have read; they never call ServiceNow or an LLM.

A1 outcome. §5.4 says a false criterion rejects, while scenario E2E-3 (criterion c false) expects `held_change` and
§5.5 says the rule fails closed. Resolved here as: **reject** only when the change is the wrong change, that is no
confirmed problem behind it (f) or a fix that is not the catalog fix for the confirmed cause (i); every other
false criterion, and any criterion that cannot be evaluated, is a **hold** (the approval row stays `requested`).
A High tier is a hold "above delegated authority" (D6). Approve only when every criterion is true.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from itsm.platform.policy import Policy

REJECTS = ("f", "i")
PLAN_CHECKS = {
    "implementation_plan": re.compile(r"^Deployment method: (AUTOMATED|MANUAL)\b"),
    "backout_plan": re.compile(r"Trigger: .+ (Backout )?[Dd]uration: \d+ minutes"),
    "test_plan": re.compile(r"Success criteria: \S"),
}
BLOCKING = ("already_scheduled", "blackout")


@dataclass
class Decision:
    rule: str
    result: str                       # approve | hold | reject ; go | no-go | held ; close | keep_open | fix_failed
    criteria: dict = field(default_factory=dict)
    reason: str = ""


def _plans(change: dict) -> bool | None:
    texts = [change.get(k) for k in PLAN_CHECKS]
    if any(t is None for t in texts):
        return None
    return all(rx.search(t or "") for rx, t in zip(PLAN_CHECKS.values(), texts, strict=True))


def a1(policy: Policy, facts: dict) -> Decision:
    """facts: change {type, risk_tier, plans..., conflicts, in_freeze, in_window_and_lead, impacted_services,
    fix_catalog_id}; problem {state, cause_notes, confirmed_by_r1, mechanism}; catalog_mechanism (of the change's
    catalog id); approvals {service_today, run}; breaker_open; kill_switch. A missing fact is None (cannot tell)."""
    ch, pr, ap = facts.get("change") or {}, facts.get("problem") or {}, facts.get("approvals") or {}
    caps = policy.autonomy["caps"]

    def val(v, test):
        return None if v is None else bool(test(v))

    tier = ch.get("risk_tier")
    c = {
        "a": None if facts.get("kill_switch") is None else (policy.autonomy["enabled"] and not facts["kill_switch"]),
        "b": None if tier is None or ch.get("type") is None else (ch["type"] == "normal" and policy.auto_approves(tier)),
        "c": _plans(ch),
        "d": val(ch.get("conflicts"), lambda cs: not any(any(b in str(x).lower().replace(" ", "_") for b in BLOCKING)
                                                         for x in cs)),
        "e": None if ch.get("in_freeze") is None or ch.get("in_window_and_lead") is None
             else (not ch["in_freeze"] and ch["in_window_and_lead"]),
        "f": None if pr.get("state") is None else (pr["state"] == "Fix in Progress" and bool((pr.get("cause_notes") or "").strip())
                                                   and bool(pr.get("confirmed_by_r1"))),
        "g": val(ch.get("impacted_services"), lambda n: n <= policy.autonomy["max_impacted_services"]),
        "h": None if None in (ap.get("service_today"), ap.get("run"), facts.get("breaker_open"))
             else (ap["service_today"] < caps["per_service_per_day"] and ap["run"] < caps["per_run"] and not facts["breaker_open"]),
        "i": None if facts.get("catalog_mechanism") is None or pr.get("mechanism") is None
             else facts["catalog_mechanism"] == pr["mechanism"],
    }
    false = [k for k, v in c.items() if v is False]
    unknown = [k for k, v in c.items() if v is None]
    if any(k in REJECTS for k in false):
        return Decision("A1", "reject", c, "wrong change: criteria " + ", ".join(k for k in false if k in REJECTS))
    if tier == "high":
        return Decision("A1", "hold", c, "b: High risk is above delegated authority (D6)")
    if false or unknown:
        why = [f"{k}: false" for k in false] + [f"{k}: cannot be evaluated" for k in unknown]
        return Decision("A1", "hold", c, "; ".join(why))
    return Decision("A1", "approve", c, "every criterion a-i is true")


def g1(now: datetime, planned_start: datetime | None, planned_end: datetime | None, new_blocking_conflict: bool | None,
       breaker_open: bool | None, earlier_no_go: int) -> Decision:
    c = {"in_window": None if planned_start is None or planned_end is None else planned_start <= now <= planned_end,
         "no_new_blocking_conflict": None if new_blocking_conflict is None else not new_blocking_conflict,
         "breaker_closed": None if breaker_open is None else not breaker_open}
    if all(c.values()):
        return Decision("G1", "go", c, "inside the approved window, no new blocking conflict, breaker closed")
    failed = ", ".join(k for k, v in c.items() if not v)
    if earlier_no_go >= 1:
        return Decision("G1", "held", c, f"second no-go ({failed})")
    return Decision("G1", "no-go", c, f"not ready: {failed}")


def c1(change: dict, window_start: datetime, window_end: datetime, next_expected: datetime | None,
       similar: list) -> Decision:
    """change {state_label, close_code}; next_expected: the mechanism's next expected occurrence (pm-agent window_end)."""
    c = {"change_closed_successful": change.get("state_label") == "Closed" and change.get("close_code") == "successful",
         "window_at_least_14_days": window_end - window_start >= timedelta(days=14),
         "window_covers_next_occurrence": next_expected is not None and window_end >= next_expected,
         "no_similar_incidents": len(similar) == 0}
    if change.get("state_label") == "Closed" and change.get("close_code") not in (None, "", "successful"):
        return Decision("C1", "fix_failed", c, f"change closed {change.get('close_code')}")
    if all(c.values()):
        return Decision("C1", "close", c, "fix verified: no recurrence in the window")
    if not c["no_similar_incidents"]:
        return Decision("C1", "keep_open", c, f"{len(similar)} similar incidents recurred (held_recurrence)")
    return Decision("C1", "keep_open", c, "window not complete: " + ", ".join(k for k, v in c.items() if not v))
