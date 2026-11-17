"""Rule R1: a root cause is confirmed only by code (END_TO_END_ITSM.md §5.8).

All four must hold, otherwise the case ends held_rca_unconfirmed:
1. the rule engine (pm-agent rca_agent.fallback) names a cause in a fix-catalog mechanism category;
2. the LLM hypothesis names the same category;
3. every cited incident is linked to the problem (pm-agent rca_agent.validate drops the others; at least one remains);
4. no injection marker appears in the analysis text.

The categories are the fix catalog's, one per planted mechanism. Each is a list of keyword groups; every group
must match (any keyword). They are generic (no CI names or versions) and fixed here, before the replay is run.
They differ from pm-agent's evaluation-only SCORE_KEYWORDS, which name the planted CIs.
"""
from __future__ import annotations

CATEGORIES: dict[str, list[list[str]]] = {
    "log_growth": [["log"], ["rotation", "rotate", "retention", "filled", "fills", "full", "growing", "grows"]],
    "cert_job_no_restart": [["cert", "certificate"], ["restart", "reload", "not reloaded", "not restarted"]],
    "firmware_defect": [["firmware"], ["bug", "defect", "version", "fixed in", "known issue"]],
    "monthend_batch_lock": [["month-end", "monthend", "month end"], ["lock"]],
}

# The change repository's markers (cm_agents/enablement/guard.py) plus two for analysis text.
EXTRA_MARKERS = ("ignore previous", "you are now")


def category(text: str) -> str | None:
    """The one category whose every group matches, or None (none, or more than one: ambiguous)."""
    t = (text or "").lower()
    hits = [c for c, groups in CATEGORIES.items() if all(any(k in t for k in g) for g in groups)]
    return hits[0] if len(hits) == 1 else None


def markers(texts: list[str], base: tuple[str, ...] = ()) -> list[str]:
    folded = "\n".join(t or "" for t in texts).casefold()
    return [m for m in (*base, *EXTRA_MARKERS) if m in folded]


def confirm(rule_result: dict, llm_result: dict | None, *, base_markers: tuple[str, ...] = ()) -> tuple[bool, dict]:
    """(confirmed, criteria). Both results are pm-agent analyse() outputs, already through validate()."""
    rule_cat = category(rule_result.get("root_cause", ""))
    llm_ok = bool(llm_result) and not str(llm_result.get("engine", "")).startswith("fallback")
    llm_cat = category(llm_result.get("root_cause", "")) if llm_ok else None
    cited = (llm_result or {}).get("evidence") or []
    found = markers([rule_result.get("root_cause", ""), *(([llm_result.get("root_cause", ""),
                                                            *llm_result.get("whys", [])]) if llm_result else [])],
                    base_markers)
    criteria = {
        "rule_engine_category": rule_cat,
        "llm_category": llm_cat if llm_ok else "LLM unavailable",
        "same_category": bool(rule_cat) and rule_cat == llm_cat,
        "cited_linked": len(cited) > 0,
        "dropped_citations": (llm_result or {}).get("evidence_dropped", []),
        "injection_markers": found,
    }
    ok = criteria["same_category"] and criteria["cited_linked"] and not found
    return ok, criteria
