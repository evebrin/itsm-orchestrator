# Integration contract: `cocheuno/ChangeManagementAgent` (Change Enablement, Release, Deployment)

Pinned: `main` @ `9450f95` (the accepted Phase 6 build; `grok-build` is the same commit) (submodule
`vendor/ChangeManagementAgent`). Installed with `pip install -e vendor/ChangeManagementAgent`, so
`cm_agents.settings.repo_root()` resolves to the submodule and finds `config/policy.yaml`,
`data/synthetic/fixtures.json` and `var/` there.

## Entry points the orchestrator calls

| Call | Source | Use |
|---|---|---|
| `cm_agents.settings.Settings(...)` | `settings.py` | built directly from the orchestrator `.env` (no second `.env`) |
| `cm_agents.graphs.runner.start_change(settings, request, thread_id)` | `graphs/runner.py` | start one change thread; `thread_id` = case id (must start `SYN-`) |
| `cm_agents.graphs.runner.resume_change(settings, thread_id, resume)` | same | after the approver agent acts (`{}`) or with a go/no-go decision `{decision, by, reason}` |
| `build_change_graph(SqliteSaver)` + `graph.get_state(config)` | `graphs/change_graph.py` | read the pending interrupt kind and the final `ChangeState` |
| `cm_agents.servicenow.changes.exact_ci`, `find_by_correlation` | `servicenow/changes.py` | RFC completeness and idempotency checks |
| `cm_agents.enablement.guard.injection_markers`, `blocks_schedule` | `enablement/guard.py` | shared marker list; rule A1 criterion d |
| `cm_agents.enablement.route.lead_days` | `enablement/route.py` | rule A1 criterion e |
| `cm-agents seed` / `cm-agents teardown` | `cli.py` | the Larkspur world (setup only, admin) |

`runner._invoke` prints its result and returns an exit code; the adapter reads state through
`get_state` rather than parsing stdout (PR C2 makes the result a return value).

## Request (input)

See `END_TO_END_ITSM.md` §4.3 for the field map. Required: `requester`, `summary`, `description`, `cis`
(names), `justification`, `implementation_plan` (starts `Deployment method:`), `backout_plan`,
`test_plan`, `proposed_window: next_maintenance` or `proposed_start`/`proposed_end`, `deployment_method`,
`deployment_strategy`, `simulated_now`.

## Interrupts and the orchestrator's answer

| Interrupt `kind` | Answer |
|---|---|
| `requester_info` | none: case ends `held_change` |
| `authorization` | `change_approver` writes the approval row (or holds), then `resume_change(…, {})` |
| `go_no_go` | `go_no_go` agent → `resume_change(…, {"decision", "by": "agent:go_no_go", "reason"})` |
| `rollback_failed` | none: case ends `held_rollback_failed` |

## ServiceNow records touched

Everything the change graph writes today (`change_request`, `task_ci`, `task_cmdb_ci_service`,
`change_task`, work notes, `incident` with `u_caused_by` on a failed PROD deployment), as
`syn.svc.change_agents`. The orchestrator additionally writes `sysapproval_approver` rows as
`syn.svc.e2e_approver` (not the change repository's code).

## Check

`pytest -m "not live"` in `vendor/ChangeManagementAgent` green (174 tests at the pin in the shared environment); a dry probe thread `SYN-PROBE-…` started and
resumed by the adapter reaches `go_no_go` after two approver-agent steps (phase 1, probe P9).
