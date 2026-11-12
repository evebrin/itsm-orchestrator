# Integration contract: `cocheuno/itscm-451z-agent` (Incident Management)

Pinned: `main` @ `c5cc1856ff1d9d4440185f7a12fc753493507369` (submodule `vendor/itscm-451z-agent`).
Import path: `vendor/itscm-451z-agent/src` on `sys.path` (the repository is not a package; PR I1).

## Entry points the orchestrator calls

| Call | Source | Use |
|---|---|---|
| `agent.tools.registry.Registry(approvals=ApprovalQueue(path))` | `tools/registry.py` | the one door for every incident write; tiers enforced at dispatch |
| `Registry.bind(name, fn)`, `Registry.dispatch(name, args, approval_id=, audit=, ticket=)` | same | propose, then execute with an approval id |
| `agent.approvals.ApprovalQueue.propose / approve / verify / mark_executed` | `approvals.py` | the incident policy agent approves as `agent:incident_policy` |
| `agent.tools.writes.assign_incident(sn, sys_id, assignment_group, rationale, live=)` | `tools/writes.py` | assign |
| `agent.tools.writes.resolve_incident(sn, sys_id, close_code, close_notes, live=)` | same | restore |
| `agent.tools.writes.add_comment(sn, sys_id, comment, live=)` | same | workaround to the caller |
| `agent.workflow.routing.route(category)` | `workflow/routing.py` | category → group |
| `agent.workflow.sla.priority(impact, urgency)` | `workflow/sla.py` | priority matrix |
| `agent.analytics.predict.classify(ticket)` | `analytics/predict.py` | category suggestion (scikit-learn artifact in `src/agent/models/`) |
| `agent.audit.AuditEntry`, `idempotency_key` | `audit.py` | key format reused in the orchestrator audit |

The `sn` argument is the orchestrator's client. It must provide `get(table, sys_id, fields)`,
`list(table, query, fields, limit=)` and `update_with_before_image(table, sys_id, payload) -> (before, after)`,
because the repository's own `update_with_before_image` and `list_all` are `TODO(student)` stubs.
`agent.config.load()` is never called (it requires `ANTHROPIC_API_KEY`); `live=` is always passed explicitly.

## Inputs and outputs

- Input: incident rows read by the orchestrator (`sys_id`, `number`, `short_description`, `description`, `category`, `subcategory`, `impact`, `urgency`, `cmdb_ci`).
- Output: write results with `before_image` (`{table, sys_id, fields}`), proposals in `logs/approvals.jsonl` under the orchestrator's `var/incident/`.

## ServiceNow records touched

`incident`: `assignment_group`, `work_notes` (`[agent] …`), `state` (Resolved `6`), `close_code`, `close_notes`, `comments`. Reads: `sys_user_group` (by name), `kb_knowledge`, `cmdb_ci`. Identity: `syn.svc.e2e_incident`.

## Not used

Its history seeder and reset (`scripts/seed_pdi.py`, `scripts/reset_pdi.py`), the MCP server, the bake-off, and the eval harness at runtime (the harness still runs in the repository's own CI).

## Check

`python -c "import sys; sys.path.insert(0,'vendor/itscm-451z-agent/src'); from agent.tools.registry import Registry; print(sorted(Registry().tools))"`
→ the seven tool names.
