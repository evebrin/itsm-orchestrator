# itsm-orchestrator

Integration layer that joins three ITSM agent repositories (Incident, Problem, Change) into one
agent-driven Incident → Problem → Change workflow on a ServiceNow PDI. ITSCM 451Z, UW–Whitewater.

Status: phase 1a (setup, probe tool, rule R1). Design: [docs/architecture/END_TO_END_ITSM.md](docs/architecture/END_TO_END_ITSM.md).

## Setup

```
git clone --recurse-submodules https://github.com/evebrin/itsm-orchestrator.git && cd itsm-orchestrator
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt && .venv/bin/pip install -e vendor/ChangeManagementAgent
cp .env.example .env        # fill in; .env is gitignored
```

The three repositories are pinned git submodules under `vendor/` (ADR 0003) and are never modified here.

## Checks

```
.venv/bin/python -m pytest                                         # orchestrator unit tests
(cd vendor/ChangeManagementAgent && ../../.venv/bin/python -m pytest -m "not live")
(cd vendor/itscm-451z-agent && ../../.venv/bin/python -m pytest)
(cd vendor/pm-agent && ../../.venv/bin/python -m unittest discover tests)
```

## Phase 1 commands

```
.venv/bin/python -m itsm probe --list                 # P0-P15 and their kind
.venv/bin/python -m itsm probe --all --dry-run        # every probe's plan; sends no request
.venv/bin/python -m itsm probe --all                  # run on the PDI in .env (needs the admin login)
.venv/bin/python -m itsm replay-r1 --run-id 20261029-192408   # rule R1 on pm-agent's reference run (read-only)
```

Read-only probes write nothing. Probes marked "temporary records" create users `syn.probe.e2e_<duty>` and
records tagged `SYN-PROBE-E2E-<hex>`, delete them all afterwards (also after a failure) and report any residue.
