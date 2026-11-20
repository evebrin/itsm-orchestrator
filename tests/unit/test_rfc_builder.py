import re

from itsm.agents.rfc_builder import KEYS, Confirmed, build, complete
from itsm.data.generate import plan

CATALOG = plan()["catalog"]
CASE = Confirmed("SYN-E2E-20261119-2106-P01", "PRB0040001", "log_growth", "syn-ful-db-prd-01", 16)


def test_request_comes_from_the_catalog_with_placeholders_filled():
    req, why = build(CASE, CATALOG, "2026-10-27 05:00:00")
    assert why == "catalog entry FIX-LOG-ROTATION" and req["fix_catalog_id"] == "FIX-LOG-ROTATION"
    assert all(req[k] for k in KEYS) and req["cis"] == ["syn-ful-db-prd-01"]
    assert "{" not in req["implementation_plan"] + req["backout_plan"] + req["test_plan"]
    assert req["implementation_plan"].startswith("Deployment method: AUTOMATED\n1. Owner: SYN Fulfillment DevOps.")
    assert re.search(r"Backout duration: \d+ minutes", req["backout_plan"])
    assert "risk" not in req and "impact" not in req           # the change repository computes them
    assert req["proposed_window"] == "next_maintenance"


def test_no_catalog_entry_means_no_request():
    req, why = build(Confirmed("c", "PRB1", "log_growth", "syn-store-web", 5), CATALOG, "x")
    assert req is None and "no fix catalog entry" in why


def test_completeness_needs_every_key_and_exactly_one_ci():
    req, _ = build(CASE, CATALOG, "2026-10-27 05:00:00")
    assert complete(req, lambda name: [{"name": name}]) == []
    assert complete(req, lambda name: []) == ["CI syn-ful-db-prd-01 does not resolve to exactly one cmdb_ci row"]
    assert "backout_plan is empty" in complete({**req, "backout_plan": ""}, lambda n: [{}])
