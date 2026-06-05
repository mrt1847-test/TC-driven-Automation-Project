# Next Actions

Last aligned: 2026-06-06

Use this file as the next-task queue for AI sessions. Read it first when the
user asks to work from NEXT ACTION, and the AI should infer the current batch,
required specs, checklist updates, and next queue update from this document.

This file is not a separate source of truth. The source of truth remains:

- [IMPLEMENTATION_CHECKLIST.md](./IMPLEMENTATION_CHECKLIST.md) for work items and status.
- [SPEC_INDEX.md](./SPEC_INDEX.md) for document ownership.
- The owning spec linked by the current checklist item for acceptance details.

## Operating Protocol

When the user asks to work from NEXT ACTION, the AI must:

1. Read this file first and implement **Current Batch**.
2. Use [IMPLEMENTATION_CHECKLIST.md](./IMPLEMENTATION_CHECKLIST.md) for the source of truth for status and dependencies.
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

**Checklist item:** None — `IMPLEMENTATION_CHECKLIST.md` has no open rows.

**Why this is next:** I-09 closed the last checklist item. Add a new checklist
row or ask for a specific follow-up before using this queue again.

**Owning spec:** N/A until a new checklist item is added.

**Implementation scope:**

- Re-read [IMPLEMENTATION_CHECKLIST.md](./IMPLEMENTATION_CHECKLIST.md) before starting new work.
- Prefer adding a new checklist ID for product gaps instead of reopening closed rows.

**Acceptance evidence:**

- New work is tracked by a checklist line before implementation starts.

## Next Batch Candidates

No queued checklist items. Suggested follow-ups when new work is planned:

| Order | Suggested area | Purpose |
|-------|----------------|---------|
| 1 | Product gap | Add a new checklist ID for any post-MVP feature or regression |
| 2 | Release QA | Repeat I-08 style clean-install validation after packaging changes |

## Completed Batch Notes

- **I-09 (2026-06-06):** Docs UTF-8 audit found no mojibake; duplicate `B1-02`
  removed from section I; progress summary aligned; runtime planning gaps closed.
- **G-02 (2026-06-06):** Worker and generated-template logs mask provider keys,
  bearer tokens, cookies, and secret env values centrally in WebSocket buffers.
- **F-04 (2026-06-06):** Automation IDE Export panel classifies validation,
  API, and Excel partial failures with retry and mapping/results/Settings links.
- **F-03 (2026-06-06):** Automation IDE Runner/Results classify bootstrap and
  test failures with Health Check, Install Dependencies, rerun-failed, Diagnosis,
  and artifact links.
- **Generation conflict UX (2026-06-06):** Automation IDE now parses Worker 409
  generation conflict summaries, shows edited/stale/conflict guidance, supports
  preview/apply regeneration, and surfaces conflicts in maintenance actions.
- **F-01 (2026-06-06):** Generate Raw and Mapping now show classified Webwright
  failure guidance with retry and artifact links.
- **E-12 (2026-06-06):** E2E covers diagnosis-bound retire cleanup with unrelated
  case preservation.
- **E-11 (2026-06-06):** E2E covers selected raw refresh incremental regeneration.
