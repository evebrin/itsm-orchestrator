# ADR 0003: Vendor repositories as pinned git submodules

Status: proposed (2026-11-12)

## Context

The prompt asks to compare submodules with `pip install git+...@<tag>`.

## Decision

Git submodules under vendor/, pinned to a commit; the change repository installed editable from its submodule.

## Reasons

Two of three repositories are not packages. cm_agents.settings.repo_root() walks up to a pyproject.toml to find .env, config/policy.yaml, fixtures and var/; installed into site-packages it falls back to the current directory.

## Consequences

Moving a pin is a deliberate commit. If PRs I1 and C1 merge, a switch to pip pins becomes possible.

## Check

`git submodule status` shows the three pinned SHAs; `git -C vendor/<repo> status --porcelain` is empty after a run.
