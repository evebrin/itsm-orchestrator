"""Stage 9: the request for change, built from the confirmed problem and the fix catalog (END_TO_END_ITSM.md §4.3).

No agent writes plan content: the plans are the catalog's reviewed templates with {ci}, {service} and {group}
filled in, and the LLM is not called. Risk and impact are not sent; the change repository computes them.
A mechanism with no catalog entry, or a request that fails the completeness check, ends the case
`held_no_fix_plan`.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

REQUESTER = "SYN E2E Problem Management"
KEYS = ("requester", "summary", "description", "cis", "justification", "implementation_plan", "backout_plan",
        "test_plan", "deployment_method", "deployment_strategy", "proposed_window", "simulated_now")


@dataclass(frozen=True)
class Confirmed:
    """What stage 7 established about a case."""
    case_id: str
    problem_number: str
    mechanism: str      # an rca_confirm category
    ci: str             # Larkspur CI name of the problem
    incident_count: int


def build(case: Confirmed, catalog: list[dict], simulated_now: str) -> tuple[dict | None, str]:
    """(request, reason). request is None when there is no catalog entry for the mechanism on this CI."""
    entry = next((c for c in catalog if c["mechanism"] == case.mechanism and c["ci"] == case.ci), None)
    if entry is None:
        return None, f"no fix catalog entry for {case.mechanism} on {case.ci}"
    fill = {"ci": case.ci, "service": entry.get("service") or case.ci, "group": entry["group"]}
    request = {
        "requester": REQUESTER,
        "summary": f"SYN fix {case.mechanism} on {case.ci}",
        "description": (f"Permanent fix {entry['id']} ({entry['title']}) for problem {case.problem_number}, case "
                        f"{case.case_id}. Confirmed cause category: {case.mechanism}. Linked incidents: "
                        f"{case.incident_count}."),
        "cis": [case.ci],
        "justification": (f"{case.incident_count} incidents recurred on {case.ci}. The workaround "
                          f"({entry['workaround']}) is temporary; the fix removes the cause."),
        "implementation_plan": entry["implementation_plan"].format(**fill),
        "backout_plan": entry["backout_plan"].format(**fill),
        "test_plan": entry["test_plan"].format(**fill),
        "deployment_method": entry["deployment_method"],
        "deployment_strategy": entry["deployment_strategy"],
        "proposed_window": "next_maintenance",
        "simulated_now": simulated_now,
        "fix_catalog_id": entry["id"],   # A1 criterion i reads it back from the description and the case
    }
    return request, f"catalog entry {entry['id']}"


def complete(request: dict, exact_ci: Callable[[str], list]) -> list[str]:
    """The completeness check before start_change. Returns the gaps (empty: ready)."""
    gaps = [f"{k} is empty" for k in KEYS if not request.get(k)]
    cis = request.get("cis") or []
    if len(cis) != 1:
        gaps.append("cis must name exactly one CI")
    elif len(exact_ci(cis[0])) != 1:
        gaps.append(f"CI {cis[0]} does not resolve to exactly one cmdb_ci row")
    return gaps
