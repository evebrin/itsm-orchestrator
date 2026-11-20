"""itsm command line.

    python -m itsm probe --list
    python -m itsm probe --all --dry-run          # print every probe's plan; sends no request
    python -m itsm probe --all                    # run on the instance in .env (phase 1b)
    python -m itsm probe P3 P12                   # selected probes
    python -m itsm replay-r1 --run-id 20261029-192408 [--pm-home ~/pm-agent]
    python -m itsm seed --run-id 20261119-1530 --dry-run   # what would be loaded; sends no request
    python -m itsm seed --run-id 20261119-1530 [--check]   # load (admin), or check a loaded run
    python -m itsm teardown --run-id 20261119-1530         # delete the run's records and identities
    python -m itsm run --run-id 20261119-2106 --case planted-a --dry-run   # phase 3 thin slice; writes nothing
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def cmd_probe(a: argparse.Namespace) -> int:
    from itsm.probes import BY_ID, ORDER, PROBES

    if a.list or a.dry_run:
        ids = ORDER if (a.all or a.list or not a.ids) else [i.upper() for i in a.ids]
        for pid in ids:
            p = BY_ID[pid]
            kind = "read-only" if p.kind == "read" else "temporary records, deleted afterwards"
            print(f"{p.id:4} [{kind}] {p.title}")
            if a.dry_run:
                for step in p.plan:
                    print(f"       - {step}")
        if a.dry_run:
            print("\n(dry run: no request was sent)")
        return 0
    ids = ORDER if a.all else [i.upper() for i in a.ids]
    unknown = [i for i in ids if i not in BY_ID]
    if not ids or unknown:
        print(f"name probes ({', '.join(p.id for p in PROBES)}) or use --all; unknown: {unknown}")
        return 2

    from itsm.platform import settings
    from itsm.platform.audit import Audit
    from itsm.probes import ProbeRun, run_probes

    s = settings.load(required=("SN_INSTANCE_URL", "SN_ADMIN_USER", "SN_ADMIN_PASSWORD"))
    run = ProbeRun(s, Audit(run_id="probe"))
    print(f"probing {s.instance.split('//')[1].split('.')[0]} (tag {run.tag})")
    results, errors, residue = run_probes(ids, run)
    for r in results:
        print(f"{r.id:4} {r.status:12} {r.detail}")
    if residue:
        print(f"residue after cleanup: {residue}")
    for e in errors:
        print(f"cleanup error: {e}")
    out = ROOT / "var" / f"probes_{run.tag}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"tag": run.tag, "results": [r.__dict__ for r in results], "residue": residue,
                               "cleanup_errors": errors}, indent=2, default=str))
    clean = not errors and not any(residue.values())
    bad = [r.id for r in results if r.status in ("FAIL", "INCONCLUSIVE")]
    print(f"details: {out.relative_to(ROOT)}")
    print("RESULT: " + ("PROBES OK" if clean and not bad else f"ATTENTION: {bad or ''} {'' if clean else 'cleanup incomplete'}"))
    return 0 if clean and not bad else 1


def cmd_replay(a: argparse.Namespace) -> int:
    from itsm.replay_r1 import print_report, replay

    out = replay(a.run_id, Path(a.pm_home).expanduser())
    print_report(out)
    return 0 if out["passed"] else 1


def cmd_seed(a: argparse.Namespace) -> int:
    from collections import Counter

    from itsm.data import load

    load.tag(a.run_id)
    if a.dry_run:
        from itsm.data.generate import plan

        p = plan()
        hist = [r for r in p["incidents"] if r["phase"] == "history"]
        print(f"seed {load.tag(a.run_id)} (dry run: no request was sent)")
        print("  identities: " + ", ".join(load.USER_PREFIX + d for d in load.DUTIES) + " (web service access only)")
        print(f"  history incidents: {len(hist)} " + str(dict(Counter(r['cluster'] for r in hist))))
        print(f"  kept for the run, not loaded: {len(p['incidents']) - len(hist)} stream incidents, "
              f"{len(p['catalog'])} fix catalog entries, the ground truth")
        return 0
    admin = _admin()
    if a.check:
        rows = load.check(admin, a.run_id)
        for name, ok, detail in rows:
            print(f"  {'PASS' if ok else 'FAIL'}  {name}: {detail}")
        ok = all(r[1] for r in rows)
        print("RESULT: " + ("SEED OK" if ok else "SEED CHECK FAILED"))
        return 0 if ok else 1
    m = load.seed(admin, a.run_id)
    print(f"seeded {m['tag']}: {len(m['incidents'])} incidents, identities {', '.join(i['user'] for i in m['identities'].values())}"
          " (passwords written to .env, not shown)")
    return 0


def cmd_teardown(a: argparse.Namespace) -> int:
    from itsm.data import load

    out = load.teardown(_admin(), a.run_id)
    print("deleted: " + (", ".join(f"{n} {t}" for t, n in out["deleted"].items()) or "nothing"))
    print(f"left: {out['left']}; records this project did not create unchanged: {out['untagged_unchanged']}")
    ok = not any(out["left"].values()) and (out["untagged_unchanged"] is None or all(out["untagged_unchanged"].values()))
    print("RESULT: " + ("TEARDOWN OK" if ok else "TEARDOWN INCOMPLETE"))
    return 0 if ok else 1


def cmd_run(a: argparse.Namespace) -> int:
    if not a.dry_run:
        print("only --dry-run exists until phase 4")
        return 2
    from itsm.run import dry_run, print_report

    out = dry_run(a.run_id, a.case)
    print_report(out)
    return 0 if not out.get("error") and out["writes_sent"] == 0 else 1


def _admin():
    from itsm.platform import settings
    from itsm.platform.audit import Audit
    from itsm.platform.sn import SNClient

    s = settings.load(required=("SN_INSTANCE_URL", "SN_ADMIN_USER", "SN_ADMIN_PASSWORD"))
    return SNClient(s.instance, s.get("SN_ADMIN_USER"), s.get("SN_ADMIN_PASSWORD"), identity="admin",
                    audit=Audit(run_id="seed"), secrets=s.secrets())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m itsm", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("probe", help="phase 1 probes on the shared PDI")
    p.add_argument("ids", nargs="*")
    p.add_argument("--all", action="store_true")
    p.add_argument("--list", action="store_true")
    p.add_argument("--dry-run", action="store_true", help="print the plan; send nothing")
    r = sub.add_parser("replay-r1", help="replay rule R1 on pm-agent's reference run (read-only)")
    r.add_argument("--run-id", required=True)
    r.add_argument("--pm-home", default="~/pm-agent")
    s = sub.add_parser("seed", help="load the combined world's incidents and identities (admin)")
    s.add_argument("--run-id", required=True)
    s.add_argument("--dry-run", action="store_true", help="print what would be loaded; send nothing")
    s.add_argument("--check", action="store_true", help="check a loaded run against its manifest")
    t = sub.add_parser("teardown", help="delete a run's records and identities (admin)")
    t.add_argument("--run-id", required=True)
    r2 = sub.add_parser("run", help="drive one case through the case graph (phase 3: --dry-run only)")
    r2.add_argument("--run-id", required=True)
    r2.add_argument("--case", required=True, choices=["planted-a", "planted-b", "planted-c", "planted-d", "decoy"])
    r2.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    return {"probe": cmd_probe, "replay-r1": cmd_replay, "seed": cmd_seed, "teardown": cmd_teardown,
            "run": cmd_run}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
