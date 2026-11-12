# ADR 0005: Agents approve normal changes through ServiceNow approval rows

Status: proposed (2026-11-12)

## Context

No human may act inside the run. The change repository forbids agents writing approval rows; pm-agent approves as admin; the platform requires assignment group then CAB Approval for every normal tier.

## Decision

A dedicated approver identity, member of the SYN assignment groups and CAB Approval, approves its own approval row when rule A1 passes. Low and Moderate tiers may be auto-approved; High is held.

## Reasons

Approval rows are the only approval record in ServiceNow; no approval definition or ACL is edited; the approver differs from requester, assessor and deployer.

## Consequences

Reverses the change repository's rule deliberately (PR C3). Depends on probe P9.

## Check

E2E-1: approval rows approved by syn.svc.e2e_approver; E2E-5: any other identity approving is refused.
