# ADR 0001: One shared PDI: dev181865

Status: proposed (2026-11-12)

## Context

Each repository was verified on its own PDI (pm-agent on the pm-agent PDI, the change repository on dev181865, the incident repository unstated). A case can only flow across practices on one instance.

## Decision

Use dev181865. Re-verify every pm-agent and incident-repository finding there (probes P1-P15).

## Reasons

The change repository's seed is the heaviest to rebuild (about 1,500 changes through Import Sets, maintenance schedules, approval-group memberships) and its discovery notes are the most complete. pm-agent's 200 incidents reseed in minutes.

## Consequences

Needs the owner's agreement (cocheuno). pm-agent findings (read-only problem.state, Known Error KB behaviour) may differ there.

## Check

`itsm probe --all` reports PASS or a recorded fallback for P1-P15 on dev181865.
