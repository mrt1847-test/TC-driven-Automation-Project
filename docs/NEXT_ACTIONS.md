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



**Checklist item:** G-05 raw-script credential value separation



**Why this is next:** C8-12 delivered the `${env.*}` placeholder mechanism
G-05 depends on. Credential-like values typed during raw generation (password
fills, secret env values) still flow verbatim from `RawAction.value` into
`body_plan_json` and generated source. Structuring must detect them, replace
them with env placeholders, flag the step for review, and never persist the
literal.



**Owning spec:** [GENERATED_PROJECT_SPEC.md](./GENERATED_PROJECT_SPEC.md) (§13.3 architecture), [STRUCTURING_SPEC.md](./STRUCTURING_SPEC.md)



**Implementation scope:**



- Detect credential-like fill values during structuring: password-type
  selectors/fields, values equal to known secret env values, and
  secret-looking strings.

- Replace detected literals with `${env.*}` placeholders before writing
  `body_plan_json`; mark the affected plan entry/step for review.

- Ensure the literal never reaches `body_plan_json`, generated files, or
  refresh-merge previews; placeholder rendering reuses the C8-12 mechanism.

- Update GENERATED_PROJECT_SPEC/STRUCTURING_SPEC contract text for the
  credential separation rules.



**Acceptance evidence:**



- Focused pytest covering password-field detection, secret-env-value
  detection, placeholder substitution into body plans, review flagging, and
  absence of literals in generated output.

- Existing structuring/codegen/regeneration guard tests still pass.

- Checklist G-05 marked `[x]` with verification note.



## Next Batch Candidates



Pick the next item from this list after Current Batch is done:



| Order | Checklist item | Purpose |

|-------|----------------|---------|

| 1 | C7-15 | POM method identity/collision policy (stop silent cross-case overwrite) |

| 2 | C6-08 | Trajectory-based multi-action auto mapping |

| 3 | C7-16 | Selector candidate ranking in body plans |

| 4 | C3-09 | Webwright subprocess cancel |

| 5 | C9-08 | Execution `runner.cli` subprocess cancel |

| 6 | D4-07 | Generate Raw Worker C2 prompt API GUI wiring |

| 7 | C12-11 | Artifact read API |

| 8 | C12-12 | Selector-candidates read API |

| 9 | C7-13 | Project-level stale/conflict API |

| 10 | C1-08, C1-09, C10-07, C10-08, G-04 | Real TestRail/Sheets connector depth |

| 11 | D5-08 | Worker structure validate in Mapping |

| 12 | I-10 | Third-party legal packaging gate |

| 13 | J.* | Optional Post-MVP extensions (`C7-17` page segmentation lives here) |



## Completed Batch Notes



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

