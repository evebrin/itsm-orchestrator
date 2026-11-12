# ADR 0010: One case id: SYN-E2E-<run_id>-P<nn>

Status: proposed (2026-11-12)

## Context

correlation_id is used three ways; the change graph requires thread ids that start SYN- and stores the thread id as correlation_id.

## Decision

Run tag SYN-E2E-<run_id> on run incidents; case id SYN-E2E-<run_id>-P<nn> on the problem, the change and its deployment incident; article titles carry the case id; incidents joined to a case get a [case <id>] work note.

## Reasons

Satisfies the change graph's rule, sits outside its metric prefixes (SYN-CHG-, SYN-OPEN-, SYN-REL-, SYN-INC-), and never starts with the incident repository's [SYN] description marker.

## Consequences

The change repository's remove_scenario_records would also delete SYN-E2E- changes and incidents; documented in the runbook. Needs PR P2 in pm-agent.

## Check

Probe P15: each prefix query returns the run's rows in exactly one query.
