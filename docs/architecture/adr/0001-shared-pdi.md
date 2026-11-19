# ADR 0001: One shared PDI: dev406825

Status: proposed (2026-11-12; instance corrected 2026-11-19)

## Context

Each repository was verified on its own PDI: pm-agent on the pm-agent PDI, the change repository on
dev181865 (its `docs/setup/PDI_AND_WORKSTATION_SETUP.md`), the incident repository on dev406825 (its ADR 0002,
"Findings from the first PDI load"). A case can only flow across practices on one instance.

## Decision

Use dev406825 (corrected 2026-11-19: dev181865 is not the instance to use). Re-verify every finding made on
another PDI there, the change repository's included (probes P0-P15; P0 first checks the Larkspur seed is there).

## Reasons

**To confirm.** The first version chose the change repository's PDI because its seed is the heaviest to rebuild
(about 1,500 changes through Import Sets, maintenance schedules, approval-group memberships); pm-agent's 200
incidents reseed in minutes. It is not yet known whether the change repository's Larkspur world is on dev406825
or has to be loaded there (open question 1).

## Consequences

- Needs the owner's agreement (cocheuno), and an answer on where the Larkspur world is.
- Findings from dev181865 (change approvals, states, `u_caused_by`, Larkspur CIs, service accounts) and from the
  pm-agent PDI (read-only `problem.state`, Known Error KB behaviour, knowledge-count access) may differ.
- The incident repository found that dev406825 refuses basic-auth API calls from users that can log in
  interactively, `admin` included, unless allowed. The probes' admin login needs that allowance (for example
  `snc_basic_auth_api_access` on the admin account), or the probes use a web-service-only account.

## Check

`itsm probe --all` reports PASS or a recorded fallback for P0-P15 on dev406825.
