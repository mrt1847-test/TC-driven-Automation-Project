# Next Actions



Last aligned: 2026-06-11



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



**Checklist item:** C7-16 selector candidate ranking in body plans



**Why this is next:** C6-08 now seeds ordered multi-action chunks, so the next
structuring quality gap is selector choice inside body plans. The planner still
copies raw selectors directly even when `SelectorCandidate` rows contain more
stable alternatives.



**Owning spec:** [STRUCTURING_SPEC.md](./STRUCTURING_SPEC.md)



**Implementation scope:**



- Rank selector candidates while building PageObjectMethod body plans, preferring
  stable selectors such as test id, role, and text over brittle CSS/XPath when
  confidence and evidence support the replacement.

- Preserve raw selector fallback when candidates are missing, low-confidence, or
  ambiguous.

- Keep source traceability from body-plan entries back to RawAction and
  SelectorCandidate evidence.

- Reuse the same ranking path for selected raw refresh merge.



**Acceptance evidence:**



- Focused pytest for selector priority ordering, low-confidence/ambiguous
  fallback, body-plan traceability, and selected raw refresh merge.

- Existing structuring/codegen/regeneration guard tests still pass.

- Checklist C7-16 marked `[x]` with verification note.



## Next Batch Candidates



Pick the next item from this list after Current Batch is done:



| Order | Checklist item | Purpose |

|-------|----------------|---------|

| 1 | C3-09 | Webwright subprocess cancel |

| 2 | C9-08 | Execution `runner.cli` subprocess cancel |

| 3 | D4-07 | Generate Raw Worker C2 prompt API GUI wiring |

| 4 | C12-11 | Artifact read API |

| 5 | C12-12 | Selector-candidates read API |

| 6 | C7-13 | Project-level stale/conflict API |

| 7 | C1-08, C1-09, C10-07, C10-08, G-04 | Real TestRail/Sheets connector depth |

| 8 | D5-08 | Worker structure validate in Mapping |

| 9 | I-10 | Third-party legal packaging gate |

| 10 | J.* | Optional Post-MVP extensions (`C7-17` page segmentation lives here) |



## Completed Batch Notes

- **C6-08 (2026-06-11):** `auto_map_case` now plans contiguous ordered
  RawAction chunks per TC step using selected-run order plus trajectory
  URL/page-title/selector/target/value/accessibility evidence when available.
  Multi-action matches persist ordered `CaseActionMappingAction` links, missing
  or low-confidence chunks stay visible as `needs_review`, malformed/missing
  trajectory files fall back deterministically, and auto-seeded multi-action
  mappings feed selected raw refresh merge correctly. Focused auto-mapping tests
  passed, targeted structuring/codegen/raw-refresh/mapping-join tests passed,
  and the non-e2e Worker suite passed with 155 tests.



- **C7-15 (2026-06-11):** PageObjectMethod identity is now case-scoped as
  `{automation_key}__step_{tc_step_index}_{base}` while readable mapping/step
  names remain unchanged. Same-named steps across cases no longer overwrite
  body plans, identical cross-case plans remain separately scoped, and selected
  raw refresh repairs legacy shared POMs before merging. Selected generation
  and retire cleanup preserve/remove the scoped page methods and origins
  correctly. Single-case legacy POMs are renamed in place to preserve
  selector/healing links. Focused structuring/raw-refresh/generation/retire
  tests passed, and the non-e2e Worker suite passed with 150 tests.

- **G-05 (2026-06-11):** Structuring now detects credential-like `fill`
  values from password fields, known secret env values, and secret-looking
  token/key strings; replaces body-plan `value`, matching `target`, and
  `value_template` with `${env.*}` placeholders; marks affected entries/flows
  for review with `credential_value_placeholder`; and keeps credential literals
  out of generated page/flow/test output. Raw refresh merge reuses the same
  planner path. Focused structuring/codegen/raw-refresh/regeneration guard tests
  passed, and the non-e2e Worker suite passed.

- **C8-12 (2026-06-11):** Generated `goto` now resolves through the project
  default-env `baseUrl` (output config first, template fallback): matching
  scheme+origin emits relative-path goto resolved by the runtime context
  `base_url` so `TC_ENV` switching applies; foreign origins stay absolute.
  `${env.dot.path}` placeholders in body-plan values render as runtime
  `self._env_value(...)` lookups (mixed text via `.format`), backed by a
  self-contained env-config helper emitted only when placeholders exist.
  Retire-path page rebuilds reuse the same base-url resolution. Codegen tests
  grew to 19 (all passed), full non-e2e worker suite 141 passed; the known
  live-Webwright e2e failures reproduce unchanged on a clean tree.

- **C8-11 (2026-06-11):** `_method_body` now renders every ordered body-plan
  entry; codegen covers select/upload/drag/press interactions, locator and
  load-state waits, and `assert_*` entries emitted as Playwright `expect(...)`
  with a conditional `expect` import; `wait_for_request/response`,
  review-required, and unsupported entries stay deterministic comments. New
  `tests/test_generated_codegen.py` (12 tests) plus generation/guard/origin/
  healing/planner/raw-refresh suites passed. Pre-existing local Webwright-run
  E2E failures (`e2e/test_generation`, `mvp1`, `mvp2`) reproduce without this
  change — runs fail at raw generation on this machine, unrelated to codegen.

- **Structuring/codegen gap audit (2026-06-11):** Code review of
  `structuring_service.py`, `mapping.py`, and `project_generator.py` against
  STRUCTURING_SPEC found the codegen layer drops body-plan data (first entry
  only, no assertion/wait codegen), hard-codes raw URLs/values including
  credentials, overwrites same-named POM methods across cases, and leaves
  SelectorCandidate ranking and multi-action auto mapping unused. Added open
  rows C8-11, C8-12, G-05, C7-15, C6-08, C7-16, and optional C7-17; queue
  re-pointed at C8-11 (C3-09 returned to candidates).

- **Checklist post-MVP audit (2026-06-06):** Added 17 open follow-up rows for

  subprocess cancel, prompt API wiring, Planned/Partial API depth, connector

  real integrations, and optional Post-MVP extensions.

- **I-09 (2026-06-06):** Docs UTF-8 audit found no mojibake; duplicate `B1-02`

  removed from section I; progress summary aligned.

- **G-02 (2026-06-06):** Worker and generated-template logs mask provider keys,

  bearer tokens, cookies, and secret env values centrally in WebSocket buffers.

- **F-04 (2026-06-06):** Automation IDE Export panel classifies validation,

  API, and Excel partial failures with retry and mapping/results/Settings links.

