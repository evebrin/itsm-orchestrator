# ADR 0006: Held cases are terminal

Status: proposed (2026-11-12)

## Context

Fail closed requires somewhere for refused or unevaluable decisions to go, without a human inside the run.

## Decision

A held case ends the automated run with a terminal state, the reason on the problem and the change, and an entry on the Decisions page. A person may act afterwards in ServiceNow, outside the run.

## Reasons

No path can quietly wait on a human; ticks and other cases continue.

## Consequences

Held work accumulates until someone reviews it; the Metrics page shows held cases by reason.

## Check

E2E-3 ends held_change and the same tick still resolves incidents.
