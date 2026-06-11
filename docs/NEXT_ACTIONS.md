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

2. Use [IMPLEMENTATION_CHECKLIST.md](./IMPLEMENTATION_CHECKLIST.md) as the source of truth for status and dependencies.

3. Use [SPEC_INDEX.md](./SPEC_INDEX.md) to locate the owning source-of-truth spec.

4. Inspect the current code before editing.

5. Implement and verify the current batch as far as the local environment allows.

6. When the batch is complete, update the relevant checklist line from `[ ]` to `[x]` with a short verification note.

7. Update any directly affected source-of-truth spec, but do not create a new doc.

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



**Checklist item:** C3-09 Webwright subprocess cancel



**Why this is next:** Post-MVP docs audit added open follow-ups after MVP

checklist closure. Stop/Cancel UX is wired in D4-02/D7-01, but Worker cancel

endpoints still update DB status only (`API_SPEC` Partial).



**Owning spec:** [API_SPEC.md](./API_SPEC.md), [RUNTIME_SPEC.md](./RUNTIME_SPEC.md)



**Implementation scope:**



- Track and terminate in-flight Webwright CLI subprocesses on cancel.

- Close or mark the related log stream cleanly.

- Preserve existing retry/history behavior.



**Acceptance evidence:**



- Targeted pytest and/or manual cancel verification.

- Checklist C3-09 marked `[x]` with verification note.



## Next Batch Candidates



Pick the next item from this list after Current Batch is done:



| Order | Checklist item | Purpose |

|-------|----------------|---------|

| 1 | C9-08 | Execution `runner.cli` subprocess cancel |

| 2 | D4-07 | Generate Raw Worker C2 prompt API GUI wiring |

| 3 | C12-11 | Artifact read API |

| 4 | C12-12 | Selector-candidates read API |

| 5 | C7-13 | Project-level stale/conflict API |

| 6 | C1-08, C1-09, C10-07, C10-08, G-04 | Real TestRail/Sheets connector depth |

| 7 | D5-08 | Worker structure validate in Mapping |

| 8 | I-10 | Third-party legal packaging gate |

| 9 | J.* | Optional Post-MVP extensions |



## Completed Batch Notes



- **Checklist post-MVP audit (2026-06-06):** Added 17 open follow-up rows for

  subprocess cancel, prompt API wiring, Planned/Partial API depth, connector

  real integrations, and optional Post-MVP extensions.

- **I-09 (2026-06-06):** Docs UTF-8 audit found no mojibake; duplicate `B1-02`

  removed from section I; progress summary aligned.

- **G-02 (2026-06-06):** Worker and generated-template logs mask provider keys,

  bearer tokens, cookies, and secret env values centrally in WebSocket buffers.

- **F-04 (2026-06-06):** Automation IDE Export panel classifies validation,

  API, and Excel partial failures with retry and mapping/results/Settings links.

