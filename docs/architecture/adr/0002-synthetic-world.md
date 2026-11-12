# ADR 0002: One synthetic world: Larkspur Outfitters

Status: proposed (2026-11-12)

## Context

Three worlds exist: the incident repository's CSV corpus, pm-agent's seeded CIs, and the change repository's Larkspur Outfitters CMDB.

## Decision

Larkspur's CMDB is the shared world. The orchestrator seeds incidents with pm-agent's four planted mechanisms re-targeted onto Larkspur CIs, a decoy and noise, plus a fix catalog and one ground_truth.json. The incident repository's corpus stays for classifier evaluation.

## Reasons

The change graph only accepts CIs present in its fixtures.json and catalog services (intake._resolve_cis, _services). Any other world would require changing the change repository.

## Consequences

pm-agent's own synthetic agent is not used for the combined world; its patterns are reproduced by the orchestrator's seeder. The incident classifier was trained on a different corpus; its accuracy on Larkspur incidents is measured, not assumed.

## Check

`itsm seed --check` counts match ground_truth.json; every planted CI resolves with exact_ci.
