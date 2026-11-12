# ADR 0007: The incident workflow is built in the orchestrator

Status: proposed (2026-11-12)

## Context

The incident repository has tools but no workflow; its client's list_all and update_with_before_image and its rollback are TODO(student) stubs.

## Decision

Build the incident nodes in the orchestrator, calling the repository's registry, write functions, routing, SLA and classifier, with the orchestrator's client injected as `sn`.

## Reasons

The write functions already take the client as a parameter; no student exercise has to be completed by PR; the tier and approval safeguards are kept.

## Consequences

The orchestrator's client must implement get, list and update_with_before_image correctly; tested in the orchestrator.

## Check

Unit test: assign_incident through Registry.dispatch with an agent approval writes the group and returns a before-image.
