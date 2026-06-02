# Next Actions

Last aligned: 2026-06-03

Use this file as the operating queue for AI work. The user should be able to say
only:

```text
NEXT ACTION 기반으로 작업 진행해
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

**Checklist item:** C9-06 generated runtime bootstrap fail-fast

**Why this is next:** after bundled runtime staging can no longer fake a live
Webwright install, generated project execution needs the same fail-fast
discipline before `runner.cli` starts.

**Owning spec:** [RUNTIME_SPEC.md](./RUNTIME_SPEC.md),
[GENERATED_PROJECT_SPEC.md](./GENERATED_PROJECT_SPEC.md)

**Implementation scope:**

- Ensure generated project bootstrap stops before runner execution when
  `requirements.txt`, `pip install`, `pytest-playwright`, Playwright install, or
  browser executable checks fail.
- Return actionable install logs and status through the Runner API.
- Keep the existing **Install Runtime** UX path compatible with the same
  bootstrap result shape.
- Avoid repeated installs when a project/runtime pair is already ready where the
  current implementation can do so safely.

**Acceptance evidence:**

- A missing `requirements.txt` or failed dependency/browser check returns a
  failure before `runner.cli` execution.
- Successful bootstrap still allows generated project runs.
- Worker tests cover at least one fail-fast path and one success path.

## Next Batch Candidates

Pick the next item from this list after Current Batch is done:

| Order | Checklist item | Purpose |
|-------|----------------|---------|
| 1 | B3-04 | Implement generated pytest fixture/browser policy |
| 2 | B2-08 | Harden runner artifact contract |
| 3 | E-09 | Live Webwright runtime E2E |
| 4 | E-10 | Generated pytest/browser contract E2E |
| 5 | I-08 | Clean Windows `dist:win:full` validation |
| 6 | C12-08 | Classify failed generated cases into selector, raw-refresh, retire, or unknown disposition |
| 7 | C7-12 | Merge selected Webwright raw refresh into existing structured entities |
| 8 | C8-09 | Add selected TC incremental regeneration without wiping unrelated generated cases |
| 9 | C12-09 | Connect selected TC Webwright refresh to structured merge and incremental generation |
| 10 | C12-10 | Add human-confirmed TC retire/delete cleanup flow |

## Completed Batch Notes

Add only short completion notes here when a batch closes. Detailed status belongs
in [IMPLEMENTATION_CHECKLIST.md](./IMPLEMENTATION_CHECKLIST.md).

- 2026-06-03: Completed C3-07 live Webwright CLI readiness probe. Health now
  separates root/python/config/CLI readiness and explicit mock mode; Webwright
  runs use the same readiness result.
- 2026-06-03: Completed C3-08 Webwright package source/version freeze.
  `prepare-runtime.ps1` now defaults to live staging, fails without a pinned
  Webwright source/package, rejects unpinned pip specs, and allows placeholder
  staging only through explicit mock mode.
