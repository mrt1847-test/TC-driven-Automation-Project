# Next Actions

Last aligned: 2026-06-03

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

**Checklist item:** E-10 generated pytest/browser contract E2E

**Why this is next:** Live Webwright raw generation is now proven locally. The
next gate is proving that a generated structured project can run its pytest
browser contract end to end through the generated template/runner path.

**Owning spec:** [GENERATED_PROJECT_SPEC.md](./GENERATED_PROJECT_SPEC.md)

**Implementation scope:**

- Generate or use a structured automation project containing at least one case.
- Run the generated pytest/Playwright contract through the in-app runner path.
- Assert generated fixtures provide browser/context/page/env/artifact behavior.
- Assert runner artifacts include command/return code/log paths and deterministic
  screenshot/trace/video paths according to the generated-template contract.

**Acceptance evidence:**

- E2E validates generated pytest runs through `runner.cli`, not a mock path.
- Browser fixtures are exercised with local Chromium and artifact settings.
- Runner result JSON/logs expose pytest command, return code, and per-case
  artifact paths.
- If generated pytest/browser execution is unavailable, the batch remains open
  and the blocker is recorded instead of marking E-10 complete.

**Current blocker:**

- Not yet investigated in this batch. Start by running the existing generated
  template/runner tests, then decide whether E-10 needs a new end-to-end case or
  can close with an existing gate plus stronger assertions.

**Unblock E-10:**

- From `apps/worker`, run the existing generated runtime/template checks first:
  `python -m pytest tests/test_generated_template_fixture_policy.py tests/e2e/test_cli_standalone.py tests/test_generated_runtime.py -q`
- Inspect generated-template runner/browser fixture outputs and add/adjust the
  narrowest E2E needed for E-10 acceptance.

## Next Batch Candidates

Pick the next item from this list after Current Batch is done:

| Order | Checklist item | Purpose |
|-------|----------------|---------|
| 1 | I-08 | Clean Windows `dist:win:full` validation |
| 2 | C12-08 | Classify failed generated cases into selector, raw-refresh, retire, or unknown disposition |
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
