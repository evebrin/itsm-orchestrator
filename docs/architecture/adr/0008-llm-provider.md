# ADR 0008: One LLM provider: xAI Grok

Status: proposed (2026-11-12)

## Context

Three LLM setups and naming schemes exist.

## Decision

XAI_API_KEY and XAI_MODEL in the orchestrator .env; the change repository uses them directly; pm-agent gets LLM_PROVIDER=xai with the same key and model.

## Reasons

The change repository depends on langchain-xai structured output; pm-agent supports xai; the incident runtime uses scikit-learn, not an LLM.

## Consequences

One vendor dependency; every decision is still made by code, so an outage only removes rationale text.

## Check

`python vendor/pm-agent/llm.py --test` and a cm_agents structured call both succeed with the shared settings.
