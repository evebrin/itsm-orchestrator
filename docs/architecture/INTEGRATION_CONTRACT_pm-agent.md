# Integration contract: `evebrin/pm-agent` (Problem Management)

Pinned: `main` @ `a717139398bb3d5971eecef07b5e6b3e905ed304` (submodule `vendor/pm-agent`).
Import path: `vendor/pm-agent` on `sys.path` (flat modules). Configuration through environment variables
set by the adapter before import: `SN_INSTANCE`, `SN_USER`, `SN_PASSWORD` (problem identity),
`SN_ADMIN_USER`, `SN_ADMIN_PASSWORD` (setup only), `LLM_PROVIDER=xai`, `LLM_MODEL`, `LLM_API_KEY`.

## Entry points the orchestrator calls

| Call | Source | Use |
|---|---|---|
| `detection_agent.run(context)` | `detection_agent.py` | candidate clusters, problems, incident links (Gate 1 replaced via PR P1) |
| `rca_agent.gather`, `rca_agent.fallback`, `rca_agent.with_llm`, `rca_agent.validate`, `rca_agent.apply` | `rca_agent.py` | both engines' results for rule R1; apply the confirmed cause |
| `knowledge_agent.run(context)` | `knowledge_agent.py` | publish the known error article, mark the problem |
| `state_api.install / move / publish / remove` | `state_api.py` | problem state moves (only if probe P3 needs it) |
| `change_agent.window_end`, `change_agent.recurrence`, closure without Gate 4 (PR P4) | `change_agent.py` | verification window and recurrence check, close |
| `synthetic_data_agent.post_change(...)` | `synthetic_data_agent.py` | seed the verification window |
| `config.tag(run_id)` | `config.py` | replaced by an injected tag (PR P2) |

**Not called**: `change_agent.run` part 1 (change creation and admin approvals), `orchestrator.py`, the
keyboard gates, `reset.py` (the orchestrator's teardown deletes `SYN-E2E-` records).

## Inputs and outputs

- Input: the pm-agent `context` dict built from the case record: `run_id`, `tag` (case id), `problems` restricted to the case, `dry_run`, and a `decide` callback (PR P1).
- Output: the context's per-phase results (problem numbers, accepted analyses, article numbers, closure results), and ServiceNow records below.

## ServiceNow records touched

`problem` (create, `assigned_to`, `cause_notes`, `workaround`, `fix_notes`, `known_error`,
`primary_known_error_article`, `rfc`, `resolution_code`, `close_notes`, `work_notes`, state through the
state API); `incident.parent`, `incident.work_notes`; `kb_knowledge` (Known Error template) and the
platform's side rows (`kb_version`, `m2m_kb_task`, `kb_knowledge_summary`); seeded window incidents.
Identity: `syn.svc.e2e_problem`.

## Check

`python -m unittest discover vendor/pm-agent/tests` → 17 tests OK; adapter dry run on one case lists the
intended writes and makes none.
