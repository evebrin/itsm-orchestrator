# ADR 0009: One allowed instance change

Status: proposed (2026-11-12)

## Context

pm-agent installs a Scripted REST API; the change repository forbids instance changes.

## Decision

No instance changes except pm-agent's tagged Problem State Scripted REST API, and only if probe P3 shows problem.state is read-only to the Table API on dev181865. Users and group memberships are data, not instance changes.

## Reasons

It is the only way found to move problem state; it is guarded to tagged records and removed by teardown.

## Consequences

If P3 shows the field is writable, the API is not installed.

## Check

After teardown, no sys_ws_definition named [PMSYNTH] Problem State exists.
