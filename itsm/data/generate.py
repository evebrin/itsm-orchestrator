"""The combined world's own synthetic data (END_TO_END_ITSM.md §12.1). Offline and deterministic; writes nothing.

Built on the change repository's Larkspur seed, unchanged: its CIs, groups and users come from
`cm_agents.data.generate.generate(42, anchor)`, the same call that loaded dev181865. On top this module plans:

- a 60-day incident history on Larkspur prod CIs with pm-agent's four planted mechanisms, re-targeted
  (log growth fills a database disk; a weekly certificate job does not reload a proxy; a firmware defect on one
  switch; a month-end batch locks a database);
- one decoy burst on one CI whose incidents have unrelated causes;
- noise whose types are **not** pinned to one CI (pm-agent's known limitation: its noise always hit the same CI,
  which made one noise type look like a pattern);
- a live stream for the run period (planted incidents keep recurring until a fix; noise continues);
- the fix catalog (one entry per mechanism, plans written so decision rule A1 criterion c can check them);
- the ground truth (clusters, mechanism categories, catalog ids, expected outcomes), for evaluation only.

Evidence such as firmware versions lives in incident work notes only: the CI records belong to the change
repository's seed and are not modified (probe P11's fallback). Category values are the platform's out-of-box
incident categories; subcategory is left empty until a probe reads the instance's choices.
"""
from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

from cm_agents.data.generate import generate as larkspur
from cm_agents.data.generate import parse_anchor

# The anchor dev181865 was loaded with (change repository RUNBOOK: `cm-agents seed --seed 42 --anchor 2026-10-27`).
DEFAULT_ANCHOR = parse_anchor("2026-10-27")
HISTORY_DAYS = 60
STREAM_DAYS = 21
NOISE_COUNT = 120
STREAM_NOISE_PER_DAY = 2

PATTERNS = {
    "a": {"mechanism": "log_growth", "ci": "syn-ful-db-prd-01", "service": "SYN Order Fulfillment",
          "group": "SYN Fulfillment DevOps", "category": "database", "impact": "2", "urgency": "2",
          "short": ["Order fulfillment queries timing out", "syn-ful-db-prd-01 disk almost full alert",
                    "Warehouse screens slow, database wait times high", "Fulfillment orders database unresponsive",
                    "Low disk space warning on syn-ful-db-prd-01 /data", "Shipping label lookups taking 30 seconds"],
          "notes": ["df -h on syn-ful-db-prd-01 shows /data at {pct}% used; /data/db_log is {gb} GB.",
                    "Cleared old files from /data/db_log; free space back to normal and queries recovered.",
                    "db_log keeps growing; no log rotation seems to run on syn-ful-db-prd-01.",
                    "Same as last time: /data filled up by database logs, purged manually."],
          "workaround": "Purge old files from /data/db_log on syn-ful-db-prd-01."},
    "b": {"mechanism": "cert_job_no_restart", "ci": "syn-pay-lb-01", "service": "SYN Payments",
          "group": "SYN Payments DevOps", "category": "network", "impact": "2", "urgency": "1",
          "short": ["Payment API calls failing TLS handshake", "Card payments rejected: certificate not trusted",
                    "Payments gateway returning SSL errors", "Checkout payment step fails after weekend"],
          "notes": ["syn-pay-lb-01 still presents the old certificate after the Sunday 23:00 CERT-RENEW-WEEKLY job; "
                    "the proxy was not reloaded.",
                    "Reloaded the TLS proxy on syn-pay-lb-01; handshakes succeed again.",
                    "Seen again this Monday; the certificate renewal log shows success but the proxy was not reloaded.",
                    "Workaround: reload the TLS proxy on syn-pay-lb-01."],
          "workaround": "Reload the TLS proxy on syn-pay-lb-01 after the Sunday renewal job."},
    "c": {"mechanism": "firmware_defect", "ci": "syn-net-sw-03", "service": "",
          "group": "SYN Platform Ops", "category": "network", "impact": "3", "urgency": "2",
          "short": ["Store back office loses network every hour", "Network drops on servers behind syn-net-sw-03",
                    "Uplink flaps, connections reset", "Intermittent packet loss to the warehouse VLAN"],
          "notes": ["syn-net-sw-03 runs firmware 9.3.2; uplink port reset after about 60 minutes.",
                    "Moved the uplink to syn-net-sw-04 temporarily; no resets since.",
                    "syn-net-sw-04 and syn-net-sw-05 run firmware 9.4.1, where the keepalive defect is fixed, and are not affected.",
                    "Vendor advisory: a link keepalive bug in firmware 9.3.x, fixed in firmware 9.4.1."],
          "workaround": "Move affected uplinks to syn-net-sw-04 until the firmware is upgraded."},
    "d": {"mechanism": "monthend_batch_lock", "ci": "syn-hr-payroll", "service": "SYN HR Portal",
          "group": "SYN Platform Ops", "category": "software", "impact": "1", "urgency": "2",
          "short": ["Payroll screens timing out", "Cannot submit timesheets in payroll", "Payroll approvals fail with 504",
                    "HR portal payroll page freezing"],
          "notes": ["HR-PAYROLL-MONTHEND batch started at 17:00 and holds locks on the payroll database.",
                    "Application recovered once the month-end batch finished.",
                    "Same lock timeouts as last month-end, during the batch window.",
                    "Users can retry after the month-end batch completes."],
          "workaround": "Wait for the month-end batch to finish, then retry."},
}
# Written in the change repository's own plan format (cm_agents/data/generate.py `_plans`), so its plan checklist
# (risk agent `judge_plans`: ordered backout, trigger and duration, test criteria, ordered steps with an owner) passes.
# {ci} and {service} are filled by itsm.agents.rfc_builder.
CATALOG = {
    "a": {"id": "FIX-LOG-ROTATION", "title": "Configure database log rotation and a disk alert",
          "deployment_method": "automated", "deployment_strategy": "big bang",
          "implementation_plan": "Deployment method: AUTOMATED\n1. Owner: {group}. Enable log rotation with 7-day "
                                 "retention for /data/db_log on {ci}.\n2. Add a disk usage alert at 80% for /data on {ci}.",
          "backout_plan": "1. Disable the log rotation job on {ci}.\n2. Restore the previous logging configuration.\n"
                          "Trigger: query latency or error rate above the verification thresholds. Backout duration: 15 minutes.",
          "test_plan": "1. Check /data usage on {ci}.\n2. Run the slow-query report for {service}.\n"
                       "Success criteria: /data below 70 percent for the verification window and no slow-query alerts."},
    "b": {"id": "FIX-CERT-RELOAD", "title": "Reload the TLS proxy after certificate renewal",
          "deployment_method": "automated", "deployment_strategy": "big bang",
          "implementation_plan": "Deployment method: AUTOMATED\n1. Owner: {group}. Add a proxy reload step to "
                                 "CERT-RENEW-WEEKLY for {ci}.\n2. Add a check that the served certificate is the renewed one.",
          "backout_plan": "1. Remove the reload step from CERT-RENEW-WEEKLY.\n2. Reload the proxy on {ci} manually.\n"
                          "Trigger: TLS handshake failures above the verification thresholds. Backout duration: 10 minutes.",
          "test_plan": "1. Run CERT-RENEW-WEEKLY in the test window.\n2. Call the {service} API over TLS.\n"
                       "Success criteria: the served certificate matches the renewed one and handshake errors are 0."},
    "c": {"id": "FIX-SWITCH-FIRMWARE", "title": "Upgrade switch firmware to 9.4.1",
          "deployment_method": "manual", "deployment_strategy": "big bang",
          "implementation_plan": "Deployment method: MANUAL\n1. Owner: {group}. Upgrade {ci} from firmware 9.3.2 to "
                                 "9.4.1 in the maintenance window.\n2. Move the uplinks back from syn-net-sw-04 to {ci}.",
          "backout_plan": "1. Boot {ci} from the previous firmware image.\n2. Move the uplinks to syn-net-sw-04 again.\n"
                          "Trigger: uplink resets or packet loss after the upgrade. Backout duration: 30 minutes.",
          "test_plan": "1. Watch uplink resets on {ci}.\n2. Measure packet loss to the warehouse VLAN.\n"
                       "Success criteria: no uplink resets for the verification window and packet loss below 0.1 percent."},
    "d": {"id": "FIX-BATCH-RESCHEDULE", "title": "Move the month-end payroll batch after hours",
          "deployment_method": "automated", "deployment_strategy": "big bang",
          "implementation_plan": "Deployment method: AUTOMATED\n1. Owner: {group}. Reschedule HR-PAYROLL-MONTHEND to "
                                 "22:00 local.\n2. Split the batch into commits of at most 5,000 rows.",
          "backout_plan": "1. Restore the previous HR-PAYROLL-MONTHEND schedule.\n2. Run the batch as one job.\n"
                          "Trigger: the batch does not finish before 06:00 local. Backout duration: 20 minutes.",
          "test_plan": "1. Run the batch on test data after hours.\n2. Watch payroll response times on {ci}.\n"
                       "Success criteria: no payroll timeouts during business hours on the next month-end."},
}
DECOY = {"ci": "syn-store-web", "service": "SYN Online Store", "group": "SYN Store DevOps", "items": [
    ("software", "Store page shows an old banner", "CDN cache; purged the cached object."),
    ("software", "Cannot log in to the store admin page", "User's account was not in the admin group; added."),
    ("software", "Store search returns no results for one product", "Product was unpublished by merchandising."),
    ("software", "Store page error in an old browser", "Unsupported browser; user switched to a current one."),
    ("inquiry", "How do I change the store opening hours", "Explained the content editor steps."),
    ("software", "Store image upload fails", "File was larger than the 10 MB limit."),
    ("software", "Store coupon code rejected", "Coupon had expired; marketing issued a new one."),
]}
# (category, descriptions, resolution, CI classes to draw from): the CI is drawn per incident, never fixed.
NOISE = [
    ("inquiry", ["Forgot my password", "Password expired, need a reset"], "Password reset; user signed in.", ()),
    ("inquiry", ["How do I export a report", "Where is the expense form"], "Explained the steps.", ()),
    ("hardware", ["Laptop will not boot", "Docking station not detected"], "Hardware swapped.", ()),
    ("software", ["Application error on save", "Report shows an error"], "Cleared the user's cache.", ("cmdb_ci_appl",)),
    ("software", ["Page not loading", "Session expired repeatedly"], "Session reset.", ("cmdb_ci_appl",)),
    ("database", ["Report query slow once", "Connection refused briefly"], "Connection pool recycled.",
     ("cmdb_ci_db_instance",)),
    ("network", ["Cannot reach an internal site by name", "Slow file transfer"], "Flushed DNS cache on the client.",
     ("cmdb_ci_linux_server", "cmdb_ci_win_server")),
    ("hardware", ["Server fan alert", "Disk SMART warning"], "Replaced the part under warranty.",
     ("cmdb_ci_linux_server", "cmdb_ci_win_server")),
]


def _last_business_days(start: datetime, end: datetime) -> list[datetime]:
    out, d = [], start.replace(day=1)
    while d < end:
        nxt = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
        last = nxt - timedelta(days=1)
        while last.weekday() >= 5:
            last -= timedelta(days=1)
        if start <= last < end:
            out.append(last)
        d = nxt
    return out


def _times(rng: random.Random, key: str, start: datetime, end: datetime) -> list[datetime]:
    def at(day, lo=14, hi=22):
        return day.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(hours=rng.randint(lo, hi - 1),
                                                                                  minutes=rng.randint(0, 59))
    days = (end - start).days
    if key == "a":  # bursts that come closer together as the disk refills after each purge
        offs = [o for o in (50, 49, 38, 37, 36, 27, 26, 25, 18, 17, 16, 11, 10, 6, 5, 2) if o < days] if days > 30 else \
            [o for o in range(days) if o % 4 in (0, 1)]
        return [at(end - timedelta(days=o)) for o in offs] if days > 30 else [at(start + timedelta(days=o)) for o in offs]
    if key == "b":  # every Monday morning, 2-3 incidents
        return [at(start + timedelta(days=i), 13, 17) for i in range(days) if (start + timedelta(days=i)).weekday() == 0
                for _ in range(rng.randint(2, 3))]
    if key == "c":  # roughly every few days, denser recently
        picks = sorted(rng.sample(range(days), min(days, max(4, days // 4))))
        return [at(start + timedelta(days=i)) for i in picks]
    # d: month-end batch window, late afternoon local (22:00-24:00 UTC)
    return [day.replace(hour=22, minute=0, second=0, microsecond=0) + timedelta(minutes=rng.randint(0, 110))
            for day in _last_business_days(start, end) for _ in range(6)]


def plan(seed: int = 42, anchor: datetime | None = None) -> dict:
    """Everything `itsm seed` would load, without writing. Same seed and anchor, same plan."""
    world = larkspur(seed, anchor or DEFAULT_ANCHOR)
    anchor = datetime.fromisoformat(world["anchor"]) if isinstance(world["anchor"], str) else world["anchor"]
    anchor = anchor.astimezone(UTC)
    rng = random.Random(f"itsm-e2e:{seed}")
    cis = {c["name"]: c for c in world["cis"]}
    for p in (*PATTERNS.values(), DECOY):
        if p["ci"] not in cis:
            raise ValueError(f"Larkspur seed has no CI {p['ci']}")
    groups = {g["name"] for g in world["groups"]}
    for p in (*PATTERNS.values(), DECOY):
        if p["group"] not in groups:
            raise ValueError(f"Larkspur seed has no group {p['group']}")
    pool = {cls: sorted(n for n, c in cis.items() if c["ci_class"] == cls and c["environment"] == "prod")
            for cls in {cl for *_, cls_list in NOISE for cl in cls_list}}
    callers = sorted(u["user_name"] for u in world["users"])
    start, stream_end = anchor - timedelta(days=HISTORY_DAYS), anchor + timedelta(days=STREAM_DAYS)

    rows = []

    def add(when, phase, cluster, short, category, ci, service, group, note, impact="3", urgency="3"):
        rows.append({"opened_at": when, "phase": phase, "cluster": cluster, "short_description": short,
                     "category": category, "cmdb_ci": ci, "service": service, "assignment_group": group,
                     "caller": rng.choice(callers), "impact": impact, "urgency": urgency, "work_notes": note})

    for phase, (lo, hi) in (("history", (start, anchor)), ("stream", (anchor, stream_end))):
        for key, p in PATTERNS.items():
            for when in _times(rng, key, lo, hi):
                note = rng.choice(p["notes"]).format(pct=rng.randint(91, 99), gb=rng.randint(28, 60))
                add(when, phase, key, rng.choice(p["short"]), p["category"], p["ci"], p["service"], p["group"], note,
                    p["impact"], p["urgency"])
        n = NOISE_COUNT if phase == "history" else STREAM_NOISE_PER_DAY * STREAM_DAYS
        for _ in range(n):
            cat, shorts, resolution, classes = rng.choice(NOISE)
            ci = rng.choice(pool[rng.choice(classes)]) if classes else ""
            when = lo + timedelta(seconds=rng.uniform(0, (hi - lo).total_seconds()))
            add(when.replace(microsecond=0), phase, "noise", rng.choice(shorts), cat, ci,
                cis[ci]["service"] if ci else "", "SYN Service Desk", resolution)
    base = anchor - timedelta(days=rng.randint(15, 30))
    for cat, short, resolution in DECOY["items"]:
        when = base + timedelta(days=rng.randint(0, 9), hours=rng.randint(14, 21), minutes=rng.randint(0, 59))
        add(when, "history", "decoy", short, cat, DECOY["ci"], DECOY["service"], DECOY["group"], resolution)

    rows.sort(key=lambda r: (r["opened_at"], r["short_description"]))
    for i, r in enumerate(rows, 1):
        r["key"] = f"I{i:04d}"
    clusters = {k: [r["key"] for r in rows if r["cluster"] == k] for k in (*PATTERNS, "decoy")}
    truth = {
        "seed": seed, "anchor": anchor.isoformat(),
        "clusters": {k: {"mechanism": PATTERNS[k]["mechanism"], "ci": PATTERNS[k]["ci"], "catalog_id": CATALOG[k]["id"],
                         "history": [x for x in clusters[k] if next(r for r in rows if r["key"] == x)["phase"] == "history"],
                         "stream": [x for x in clusters[k] if next(r for r in rows if r["key"] == x)["phase"] == "stream"],
                         "expected": "closed_fix_applied"} for k in PATTERNS},
        "decoy": {"ci": DECOY["ci"], "incidents": clusters["decoy"], "expected": "no_problem_or_held_rca_unconfirmed"},
        "noise": len([r for r in rows if r["cluster"] == "noise"]),
    }
    catalog = [{**CATALOG[k], "mechanism": PATTERNS[k]["mechanism"], "ci": PATTERNS[k]["ci"],
                "service": PATTERNS[k]["service"], "group": PATTERNS[k]["group"],
                "workaround": PATTERNS[k]["workaround"]} for k in PATTERNS]
    return {"seed": seed, "anchor": anchor.isoformat(), "incidents": rows, "catalog": catalog, "ground_truth": truth}
