from datetime import UTC, datetime, timedelta

import pytest

from itsm.agents.rfc_builder import Confirmed, build
from itsm.agents.rules import a1, c1, g1
from itsm.data.generate import plan
from itsm.platform import policy as pol

NOW = datetime(2026, 10, 27, 5, tzinfo=UTC)


@pytest.fixture(scope="module")
def P():
    return pol.load()


def good_facts():
    req, _ = build(Confirmed("c", "PRB1", "log_growth", "syn-ful-db-prd-01", 16), plan()["catalog"], "x")
    return {"kill_switch": False, "breaker_open": False, "catalog_mechanism": "log_growth",
            "change": {"type": "normal", "risk_tier": "low", "conflicts": [], "in_freeze": False, "in_window_and_lead": True,
                       "impacted_services": 1, **{k: req[k] for k in ("implementation_plan", "backout_plan", "test_plan")}},
            "problem": {"state": "Fix in Progress", "cause_notes": "logs fill /data", "confirmed_by_r1": True,
                        "mechanism": "log_growth"},
            "approvals": {"service_today": 0, "run": 0}}


def test_a_complete_catalog_change_is_approved(P):
    d = a1(P, good_facts())
    assert d.result == "approve" and all(d.criteria.values())


def test_missing_backout_trigger_is_a_hold_on_c_as_in_e2e_3(P):
    f = good_facts()
    f["change"]["backout_plan"] = "1. Restore the previous configuration."
    d = a1(P, f)
    assert d.result == "hold" and d.criteria["c"] is False and "c: false" in d.reason


@pytest.mark.parametrize("path,value,result,crit", [
    (("kill_switch",), True, "hold", "a"),
    (("change", "risk_tier"), "high", "hold", "b"),
    (("change", "conflicts"), ["Already Scheduled"], "hold", "d"),
    (("change", "in_freeze"), True, "hold", "e"),
    (("change", "impacted_services"), 3, "hold", "g"),
    (("approvals", "run"), 10, "hold", "h"),
    (("breaker_open",), True, "hold", "h"),
    (("problem", "confirmed_by_r1"), False, "reject", "f"),
    (("catalog_mechanism",), "firmware_defect", "reject", "i"),
])
def test_each_criterion(P, path, value, result, crit):
    f = good_facts()
    target = f
    for k in path[:-1]:
        target = target[k]
    target[path[-1]] = value
    d = a1(P, f)
    assert d.result == result and d.criteria[crit] is False


def test_a_fact_that_cannot_be_read_holds_never_approves(P):
    f = good_facts()
    del f["change"]["in_freeze"]
    d = a1(P, f)
    assert d.result == "hold" and d.criteria["e"] is None and "cannot be evaluated" in d.reason


def test_g1_go_no_go_then_held():
    start, end = NOW - timedelta(hours=1), NOW + timedelta(hours=1)
    assert g1(NOW, start, end, False, False, 0).result == "go"
    assert g1(NOW + timedelta(hours=2), start, end, False, False, 0).result == "no-go"
    assert g1(NOW + timedelta(hours=2), start, end, False, False, 1).result == "held"
    assert g1(NOW, None, end, False, False, 0).result == "no-go"


def test_c1_close_keep_open_and_fix_failed():
    ok = {"state_label": "Closed", "close_code": "successful"}
    w0, w1 = NOW, NOW + timedelta(days=14)
    assert c1(ok, w0, w1, NOW + timedelta(days=7), []).result == "close"
    assert c1(ok, w0, w1, NOW + timedelta(days=7), [{"number": "INC1"}]).result == "keep_open"
    assert c1(ok, w0, NOW + timedelta(days=10), NOW + timedelta(days=7), []).result == "keep_open"
    assert c1({"state_label": "Closed", "close_code": "unsuccessful"}, w0, w1, w1, []).result == "fix_failed"
