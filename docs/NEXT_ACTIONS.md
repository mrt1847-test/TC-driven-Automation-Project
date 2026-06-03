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

**Checklist item:** I-08 clean Windows `dist:win:full` validation

**Why this is next:** Live Webwright raw generation and generated pytest/browser
execution are now proven locally. The next gate is validating the same runtime
chain from a clean Windows installer/bundled-runtime path.

**Owning spec:** [RUNTIME_SPEC.md](./RUNTIME_SPEC.md)

**Implementation scope:**

- Run `npm run dist:win:full` or the closest locally available equivalent.
- Verify `prepare-runtime.ps1` stages vendored Webwright, embeddable Python,
  generated-template, Chromium browser assets, and `THIRD_PARTY_NOTICES.txt`.
- Verify bundled runtime settings/readiness on Windows.
- If possible, install/run the packaged app and execute the raw-generation ->
  generated-project -> in-app runner chain.

**Acceptance evidence:**

- Build/staging command output is recorded.
- `runtime-staging/runtime-manifest.json` and `THIRD_PARTY_NOTICES.txt` exist.
- Bundled `runtime/webwright` contains real vendored Webwright with license and
  configs, not a mock placeholder.
- Bundled Python can import Worker requirements, `webwright.run.cli`, and
  Playwright.
- Chromium browser executable is available from the bundled browser cache.
- If clean Windows installer execution is unavailable, keep I-08 open and record
  the blocker instead of advancing the queue.

**Current blocker:**

- Not yet investigated in this batch. Start by validating runtime staging output
  and determine whether a full installer run is possible in the local
  environment.

**Unblock I-08:**

- From repo root, run `npm run dist:win:full` if feasible.
- If full packaging is too slow or unavailable, run `scripts/prepare-runtime.ps1`
  and validate the staged runtime contents directly, but leave I-08 open unless
  the checklist acceptance can be proven.

## Next Batch Candidates

Pick the next item from this list after Current Batch is done:

| Order | Checklist item | Purpose |
|-------|----------------|---------|
| 1 | C12-08 | Classify failed generated cases into selector, raw-refresh, retire, or unknown disposition |
| 2 | C7-12 | Merge selected Webwright raw refresh into existing structured entities |
| 3 | C8-09 | Add selected TC incremental regeneration without wiping unrelated generated cases |
| 4 | C12-09 | Connect selected TC Webwright refresh to structured merge and incremental generation |
| 5 | C12-10 | Add human-confirmed TC retire/delete cleanup flow |

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
