# Next Actions

Last aligned: 2026-06-04

Use this file as the operating queue for AI work. The user should be able to say
only:

```text
NEXT ACTION
```

and the AI should infer the current batch, required specs, checklist updates,
and next queue update from this document.

This file is not a separate source of truth. The source of truth remains:

- [IMPLEMENTATION_CHECKLIST.md](./IMPLEMENTATION_CHECKLIST.md) for work items and status.
- [SPEC_INDEX.md](./SPEC_INDEX.md) for document ownership.
- The owning spec linked by the current checklist item for acceptance details.

## Operating Protocol

When the user asks to work from NEXT ACTION, the AI must:

1. Read this file first and implement **Current Batch**.
2. Use [IMPLEMENTATION_CHECKLIST.md](./IMPLEMENTATION_CHECKLIST.md) as the source of truth for status and dependencies.
3. Use [SPEC_INDEX.md](./SPEC_INDEX.md) to locate the owning source-of-truth spec.
4. Inspect the current code before editing.
5. Implement and verify the current batch as far as the local environment allows.
6. When the batch is complete, update the relevant checklist line from `[ ]` to `[x]` with a short verification note.
7. Update any directly affected source-of-truth spec, but do not create a new spec doc.
8. Move the next item from **Next Batch Candidates** into **Current Batch**.
9. Remove or reorder that item in **Next Batch Candidates**.
10. Add a short note under **Completed Batch Notes**.

If the current batch cannot be completed, do not advance the queue. Record the
blocker in the final response and leave `Current Batch` unchanged.

## Rules For AI

1. Do not add a new docs file unless the user explicitly asks for a new document.
2. Do not duplicate source-of-truth content from specs into this file.
3. Close at most one main checklist item per implementation batch unless the user asks for a larger batch.
4. If a task uncovers a planning gap, update the owning source-of-truth spec and checklist, not a new side document.
5. Keep supporting guides subordinate to the owning spec listed in [SPEC_INDEX.md](./SPEC_INDEX.md).
6. Keep this file short: it should identify the next task, not restate the whole spec.

## Current Batch

**Checklist item:** C6-07 ordered multi-action mapping API

**Why this is next:** C5-03 now preserves the expanded action sequence required
by C7-11. Before deterministic method body planning can consume that sequence,
one reviewed TC step must reliably round-trip an ordered list of raw actions
through the Mapping API.

**Owning specs:** [STRUCTURING_SPEC.md](./STRUCTURING_SPEC.md),
[DB_SCHEMA.md](./DB_SCHEMA.md)

**Implementation scope:**

- Harden Mapping GET/PUT so each TC step persists and returns ordered
  `action_ids` through `CaseActionMappingAction`.
- Keep `CaseActionMapping.raw_action_id` aligned with the first ordered action
  for backward compatibility.
- Replace/remove stale join rows deterministically on mapping updates and reject
  action IDs that do not belong to the selected case's raw runs.
- Add focused Worker tests for ordered round-trip, replacement/removal, and
  invalid or foreign action IDs.

**Acceptance evidence:**

- One TC step round-trips multiple raw action IDs in the submitted order.
- Updating that step replaces its join rows without stale links and keeps the
  legacy first-action field aligned.
- Foreign/invalid action IDs are rejected without partially rewriting mappings.
- Existing and focused Mapping API tests pass.

## Next Batch Candidates

Pick the next item from this list after Current Batch is done:

| Order | Checklist item | Purpose |
|-------|----------------|---------|
| 1 | C7-11 | Compile expanded/multi-action mappings into deterministic method body plans |
| 2 | C8-07 | Persist complete GeneratedFileOrigin links needed for impact analysis |
| 3 | C7-12 | Merge selected Webwright raw refresh into existing structured entities |
| 4 | C8-09 | Add selected TC incremental regeneration without wiping unrelated generated cases |
| 5 | C12-09 | Connect selected TC Webwright refresh to structured merge and incremental generation |
| 6 | C12-10 | Add human-confirmed TC retire/delete cleanup flow |

## Completed Batch Notes

Add only short completion notes here when a batch closes. Detailed status belongs
in [IMPLEMENTATION_CHECKLIST.md](./IMPLEMENTATION_CHECKLIST.md).

- 2026-06-03: Completed C3-07 live Webwright CLI readiness probe. Health now
  separates root/python/config/CLI readiness and explicit mock mode; Webwright
  runs use the same readiness result.
- 2026-06-03: Completed C3-08 Webwright package source/version freeze.
  `prepare-runtime.ps1` now defaults to live staging from vendored
  `third_party/webwright`, still supports explicit external source/package
  overrides, rejects unpinned pip specs, and allows placeholder staging only
  through explicit mock mode.
- 2026-06-03: Completed C9-06 generated runtime bootstrap fail-fast. Runner
  bootstrap failures now stop before `runner.cli`, write deterministic logs and
  `results.json`, and are covered by worker tests.
- 2026-06-03: Completed B3-04 generated pytest fixture/browser policy.
  Generated-template fixtures now provide env config, base URL, browser/context
  args, storage state, artifact directory, and trace/screenshot/video policy.
- 2026-06-03: Completed B2-08 pytest runner artifact contract hardening.
  Runner results now include pytest command/return code/log paths and
  deterministic per-case artifact paths for screenshot/trace/video outputs.
- 2026-06-03: Completed E-09 live Webwright runtime E2E. The live pytest gate
  passed with real Webwright, `gpt-5-mini`, Git Bash shell readiness, nested
  `final_script.py` harvesting, RawAction rows, indexed artifacts, and no mock
  mode.
- 2026-06-03: Completed E-10 generated pytest/browser contract E2E. Worker
  `run_project` now proves `runner.cli` -> pytest-playwright with local
  Chromium, `page`/`context`/`base_url`/env/artifact fixtures, preserved pytest
  logs, and `[chromium]` screenshot/trace mapping into results and DB rows.
- 2026-06-04: Completed I-08 clean Windows installer validation. A clean
  `dist:win:full` installer was installed into a new directory and launched
  with a fresh Electron profile; installed bundled live health passed, real
  Webwright produced a non-mock final script and three RawAction rows, and the
  generated project completed the bundled Chromium Runner with one passed case.
- 2026-06-04: Completed C12-04 failure target resolver. Failed execution results
  now resolve through latest generated-file/origin links to structured
  step/POM targets and return linked mapping, raw-action, run, and artifact IDs
  with deterministic resolved, missing, or ambiguous outcomes.
- 2026-06-04: Completed C12-08 failure disposition classifier. Execution
  diagnosis now returns exactly one evidence-backed disposition per failed
  result and conservatively falls back to `unknown` for unresolved, mixed, or
  unsupported evidence without applying maintenance actions.
- 2026-06-04: Completed C5-03 expanded action type coverage. Line-based
  extraction now covers the core 17 types plus upload/drag interactions,
  preserves ordered selector/value/source metadata across sync and async
  shapes, and retains unsupported Playwright calls as reviewable `custom_code`.
