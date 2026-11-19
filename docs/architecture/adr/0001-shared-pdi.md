# ADR 0001: One shared PDI: dev181865

Status: proposed (2026-11-12; confirmed again 2026-11-19 after a brief switch to dev406825, which was not the
instance to use)

## Context

Each repository was verified on its own PDI: pm-agent on the pm-agent PDI, the change repository on
dev181865 (its `docs/setup/PDI_AND_WORKSTATION_SETUP.md`), the incident repository on dev406825 (its ADR 0002,
"Findings from the first PDI load"). A case can only flow across practices on one instance.

## Decision

Use dev181865. Re-verify every pm-agent and incident-repository finding there (probes P0-P15; P0 first checks
the Larkspur seed is there).

## Reasons

The change repository's seed is the heaviest to rebuild (about 1,500 changes through Import Sets, maintenance
schedules, approval-group memberships) and its discovery notes are the most complete. Its Phase 6 report says
the instance was left on seed 42. pm-agent's 200 incidents reseed in minutes.

## Consequences

Needs the owner's agreement (cocheuno). pm-agent findings (read-only problem.state, Known Error KB behaviour,
knowledge-count access) and incident-repository findings may differ there.

## Check

`itsm probe --all` reports PASS or a recorded fallback for P0-P15 on dev181865.
