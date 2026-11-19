import re
from collections import defaultdict
from datetime import timedelta

import pytest

from itsm.agents.rca_confirm import CATEGORIES
from itsm.data.generate import plan


@pytest.fixture(scope="module")
def p():
    return plan()


def max_in_14_days(rows):
    """Most incidents on one CI inside any 14-day window (pm-agent's detection rule: 5 or more)."""
    by_ci = defaultdict(list)
    for r in rows:
        if r["cmdb_ci"]:
            by_ci[r["cmdb_ci"]].append(r["opened_at"])
    best = 0
    for times in by_ci.values():
        times.sort()
        for i, t in enumerate(times):
            best = max(best, sum(1 for u in times[i:] if u < t + timedelta(days=14)))
    return best


def test_same_seed_same_plan_and_keys_are_unique(p):
    assert plan()["incidents"] == p["incidents"]
    keys = [r["key"] for r in p["incidents"]]
    assert len(keys) == len(set(keys))


def test_every_planted_pattern_crosses_the_detection_rule_and_noise_never_does(p):
    hist = [r for r in p["incidents"] if r["phase"] == "history"]
    for k in "abcd":
        assert max_in_14_days([r for r in hist if r["cluster"] == k]) >= 5, k
    assert max_in_14_days([r for r in hist if r["cluster"] == "decoy"]) >= 5  # a decoy must look like a pattern
    assert max_in_14_days([r for r in p["incidents"] if r["cluster"] == "noise"]) < 5


def test_planted_patterns_also_recur_in_the_live_stream(p):
    for k in "abcd":
        assert p["ground_truth"]["clusters"][k]["stream"], k
    assert all(r["phase"] == "history" for r in p["incidents"] if r["cluster"] == "decoy")


def test_ground_truth_partitions_the_incidents(p):
    gt = p["ground_truth"]
    planted = [x for c in gt["clusters"].values() for x in c["history"] + c["stream"]]
    assert len(planted) + len(gt["decoy"]["incidents"]) + gt["noise"] == len(p["incidents"])
    assert len(set(planted)) == len(planted)


def test_catalog_matches_r1_categories_and_a1_plan_checklist(p):
    assert {c["mechanism"] for c in p["catalog"]} == set(CATEGORIES)
    for c in p["catalog"]:
        assert c["implementation_plan"].startswith("Deployment method:")
        assert re.search(r"Trigger:", c["backout_plan"]) and re.search(r"Duration: \d+ minutes", c["backout_plan"])
        assert c["test_plan"].startswith("Success criteria:")


def test_every_ci_is_a_larkspur_ci_and_no_ci_record_is_changed(p):
    from cm_agents.data.generate import generate

    from itsm.data.generate import DEFAULT_ANCHOR
    names = {c["name"] for c in generate(42, DEFAULT_ANCHOR)["cis"]}
    assert {r["cmdb_ci"] for r in p["incidents"] if r["cmdb_ci"]} <= names
    assert "firmware_version" not in str(p["catalog"])  # firmware evidence is in work notes, not CI fields
