# ADR 0004: LangGraph composition: tick graph, case graphs, change threads

Status: proposed (2026-11-12)

## Context

The combined system must use LangGraph with no LLM supervisor; the change repository already has a checkpointed graph; pm-agent and the incident repository have none.

## Decision

A tick graph (one thread per run) polls incidents, restores them and runs detection each simulated hour. A case graph (one thread per problem, thread id = case id) runs RCA to closure. Its change node drives the unchanged change graph through start_change and resume_change. Routing is deterministic conditional edges. Checkpointer: SqliteSaver.

## Reasons

Reuses the change graph without modification; pm-agent agents become plain node functions; a tick on a simulated clock needs no instance change and is replayable (webhooks would need a business rule or outbound REST).

## Consequences

Two SQLite files (orchestrator and change repository). ServiceNow remains the source of truth for where a case is.

## Check

A run interrupted with Ctrl-C and restarted continues each case from its last node; `itsm status <case>` agrees with ServiceNow.
