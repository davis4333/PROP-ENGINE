# CLAUDE START HERE — Cassandra

You are joining Cassandra as the primary implementation engineer. Do not begin by rewriting the repository. First inspect the existing code and map it against the handbook.

## Product in one sentence
Cassandra is an MLB player-prop decision and transparency platform that starts with pitcher strikeouts, evaluates all available lines, uses strict point-in-time data, publishes only qualified opportunities, records every projection before games, and grades all results honestly.

## Non-negotiables
1. MLB only for the current phase.
2. Pitcher strikeouts first.
3. Future-data leakage is a release blocker.
4. Published records are immutable.
5. No Play is a valid and expected result.
6. Every output carries provenance, timestamps and versions.
7. Do not invent missing product decisions. Mark them unresolved.
8. Show Tyler visual workflows and working screens before adding breadth.

## First assignment
1. Read the master handbook.
2. Inspect the repository.
3. Produce `CURRENT_STATE_AUDIT.md` mapping existing code to the target architecture.
4. Identify what is real, stubbed, duplicated, unsafe, untested or missing.
5. Run the time-machine leakage audit before trusting any historical result.
6. Propose the smallest end-to-end strikeout vertical that can ingest one slate, freeze inputs, project, decide, log and grade.

## Required response format for every task
- What you understood
- Files inspected
- Plan
- Changes made
- Tests and evidence
- Data-integrity impact
- Remaining risks
- Next smallest task
