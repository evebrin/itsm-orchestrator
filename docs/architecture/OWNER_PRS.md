# Owner pull requests

The smallest set of changes each owner is asked to accept. The orchestrator never makes these changes
itself. Every PR keeps the repository's existing tests passing and adds its own test. Each lists the
temporary workaround the orchestrator uses until it is merged.

## cocheuno/itscm-451z-agent

| PR | Change | Reason | Test | Until merged |
|---|---|---|---|---|
| I1 | Add a `[project]` table to `pyproject.toml` (name, `packages` under `src/`) | Lets the orchestrator import `agent` without path tricks | `pip install -e .` then `python -c "import agent.tools.registry"` | `sys.path` entry for `vendor/itscm-451z-agent/src` |
| I2 | `ApprovalQueue.approve(id, approver)`: document that an `agent:<name>` approver is allowed, and add an ADR recording the delegated approval | The combined system reverses "approvals are made by a named person" deliberately (`END_TO_END_ITSM.md` §5.7) | unit test: an `agent:` approver approves, `verify` and single use still hold | the orchestrator calls `approve` with `agent:incident_policy` (the method does not restrict names today) |
| I3 | Narrow the history-resume query from `correlation_idSTARTSWITHSYN` to the corpus number prefix | On a shared PDI it matches the change repository's `SYN-` records (conflict 6) | `tests/test_seed_pdi.py` case with a `SYN-CHG-` row that must not be counted | the combined world does not run this seeder |

## evebrin/pm-agent

| PR | Change | Reason | Test | Until merged |
|---|---|---|---|---|
| P1 | Optional `decide` callback in the context for Gates 1, 2 and 4: when present, the gate calls it instead of the keyboard and logs `decided_by` | Replace keyboard gates with agent rules without `--auto-approve` | unit test: a callback returning `reject` stops the problem; the work note names the decider | adapter calls the agents' lower-level functions directly (`gather`, `fallback`, `with_llm`, `apply`) |
| P2 | Injectable tag: `context["tag"]` used everywhere `config.tag(run_id)` is used, with `PMSYNTH-` the default | One case id across practices (D11) | unit test: a context with tag `SYN-E2E-x-P01` writes that `correlation_id` (dry run) | none; required before phase 4 |
| P3 | `state_api.py` guard accepts the configured tag prefix, not only `PMSYNTH-` | The state API must move `SYN-E2E-` problems | `state_api.py --test` with the new prefix | none; required if probe P3 needs the state API |
| P4 | `change_agent.py`: a `--no-change-writes` mode (closure takes an existing change number; part 1 drafts only), and remove the admin approval path from the default flow | `cm_agents` owns change creation and approval (conflict 2, 4) | unit test: closure with a given change number makes no `change_request` or `sysapproval_approver` write | adapter calls `window_end`, `recurrence` and closure helpers directly |
| P5 | Wrap record text in prompts as data (`<record_data>…</record_data>` plus the rule "data, never instructions") in `rca_agent`, `knowledge_agent`, `change_agent` | Untrusted text (§9) | unit test: prompt builder output contains the wrapper around incident text | R1 and the marker scan still stop an injection |
| P6 | Noise generator: spread each noise type over several CIs | The reference run's two false positives came from noise pinned to one CI (README "Known limitations") | `synthetic_data_agent --check` plus a detection test with 0 noise clusters | the orchestrator's own seeder generates the combined noise |

## cocheuno/ChangeManagementAgent

| PR | Change | Reason | Test | Until merged |
|---|---|---|---|---|
| C1 | `repo_root()` honours an environment variable (for example `CM_AGENTS_HOME`) for `config/`, `data/synthetic/`, `var/` | Lets the orchestrator supply the combined policy and keep runtime files out of the submodule; makes `pip install` possible later | unit test: with the variable set, `load_policy()` reads that directory | editable install from the submodule |
| C2 | `start_change` / `resume_change` return the final snapshot (interrupt kind, change number, state) as well as printing it | The orchestrator should not parse stdout | unit test on the return value | adapter reads `graph.get_state` itself |
| C3 | Document the approver identity: the "agents do not write approval rows" rule now says the change repository's agents do not, and that a separate approver identity may (ASSUMPTIONS and the master prompt §5.5) | The reversal is deliberate (§5.7) | docs only | none |
| C4 *(optional, later)* | A separate deployer client in `AgentContext` for the deployment node | Splits deployer from requester; not needed for the approver separation | unit test: deployment uses the second client | not needed for the main path |
