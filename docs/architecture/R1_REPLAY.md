# Rule R1 replay

Rule R1 (design §5.8) confirms a root cause only in code. This note records its replay, which design §5.8
and check E2E-2 require before R1 is relied on.

## Run

- pm-agent run `20261119-014420`, seed 451, on a fresh PDI (the reference run `20261029-192408` was on a
  PDI that has since been reclaimed, so its evidence could no longer be read).
- `python -m itsm replay-r1 --run-id 20261119-014420`: pm-agent's evidence gathering and both RCA engines
  (rule engine; LLM `anthropic claude-sonnet-4-6`), R1 applied, the answer key read only afterwards.
- The evidence was gathered after the run had finished, so it includes the run's own work notes
  (for example "Known Error article created"). The RCA step itself saw the evidence before those notes.

## Revision 1 result: differs from the expectation

| Problem | Answer key | Rule engine | LLM | R1 rev. 1 |
|---|---|---|---|---|
| PRB0040001 | planted b | cert_job_no_restart | cert_job_no_restart | confirmed |
| PRB0040002 | planted d | monthend_batch_lock | monthend_batch_lock | confirmed |
| PRB0040003 | planted a | log_growth | log_growth | confirmed |
| PRB0040004 | planted c | firmware_defect | firmware_defect | confirmed |
| PRB0040005 | unplanted (Wi-Fi decoy on core-sw-01) | firmware_defect (wrong) | firmware_defect (wrong) | **confirmed (wrong)** |
| PRB0040006 | unplanted | none | none | held |

Why PRB0040005 was confirmed:

- The rule engine actually answered "Not determined from the evidence: the work notes on core-sw-01
  (firmware_version 16.12.4) only record how incidents were handled…". Revision 1 did not enforce
  criterion (1) of §5.8 (a determined cause), and the words "firmware" and "version" in the CI label made
  the text match `firmware_defect`.
- The LLM answered "The evidence does not supply diagnostic logs or error codes that identify the precise
  failure mechanism; … The most probable cause is a firmware defect or misconfiguration…": a guess, which
  matched the same category.

## Revision 2

- A text that admits the evidence does not establish the cause ("not determined", "cannot be determined",
  "does not supply", "does not identify", "insufficient evidence", …) names no category, whichever engine
  wrote it. This enforces §5.8 criterion (1) and applies it to the LLM too.
- `firmware_defect` requires "firmware" and one of bug / defect / fixed in / known issue / advisory;
  "version" was removed because every CI label carries `firmware_version`.
- Unit tests use the two texts above.

Re-scored on the same saved answers, without new LLM calls: **4 of 4 planted confirmed, 2 of 2 unplanted
held.**

## Limits

- Revision 2 was written after seeing this run's answers, so this re-score is not an independent test.
  The next fresh run (or the phase 1b data) is.
- Keyword categories remain a heuristic. A held problem is not lost: it ends `held_rca_unconfirmed` for
  a human, which is the safe direction.
