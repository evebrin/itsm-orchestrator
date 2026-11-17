"""itsm command line.

    python -m itsm probe --list
    python -m itsm probe --all --dry-run          # print every probe's plan; sends no request
    python -m itsm probe --all                    # run on the instance in .env (phase 1b)
    python -m itsm probe P3 P12                   # selected probes
    python -m itsm replay-r1 --run-id 20261029-192408 [--pm-home ~/pm-agent]
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
    a = ap.parse_args(argv)
    return cmd_probe(a) if a.cmd == "probe" else cmd_replay(a)


if __name__ == "__main__":
    sys.exit(main())
