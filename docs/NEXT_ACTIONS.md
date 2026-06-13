# Next Actions



Last aligned: 2026-06-13



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



**Checklist item:** _None queued_



**Why this is next:** G-06 is complete, the checklist has no open `[ ]` rows,
and there are no remaining queued candidate items in this file.



**Owning spec:** _TBD when the next checklist item is selected_



**Implementation scope:**



- Add the next checklist item here before starting another NEXT ACTION batch.
- If a new audit uncovers work, add it first to the owning source-of-truth spec
  and [IMPLEMENTATION_CHECKLIST.md](./IMPLEMENTATION_CHECKLIST.md), then queue it
  here.



**Acceptance evidence:**



- _N/A until the next batch is queued._



## Next Batch Candidates



Pick the next item from this list after Current Batch is done:



| Order | Checklist item | Purpose |

|-------|----------------|---------|

| _None_ | _TBD_ | Add the next checklist item after G-06 is complete |



## Completed Batch Notes

- **Queue closeout (2026-06-13):** Confirmed `IMPLEMENTATION_CHECKLIST.md`
  has no open `[ ]` rows, aligned the progress summary to the actual completed
  counts including section J, and updated `SPEC_INDEX.md` so the former
  post-MVP follow-up list no longer reads as open work. `Current Batch` remains
  `_None queued_` until a new checklist item is added.

- **G-06 (2026-06-13):** Hardened the localhost Worker trust boundary. Worker
  CORS now uses configured Electron/dev/file origins instead of wildcard
  origins, mutating HTTP APIs require `X-TC-Studio-Worker-Token`, disallowed
  origins and missing/invalid tokens are rejected before filesystem/settings
  mutations, and `/ws/logs/{job_id}` requires the same token via query string
  plus allowed Origin. Electron main generates the session token, passes it to
  the Worker env and renderer API client, and main-process connector IPC uses
  it for Worker POST calls. Live E2E scripts now require
  `TC_STUDIO_WORKER_TOKEN` through a shared HTTP client helper. Focused
  security/path/settings tests, script compile checks, the Worker non-e2e
  suite, and `npm run build` passed.

- **C11-05 (2026-06-13):** Hardened Project IDE generated-file path
  containment. All generated-file read/write/create/delete/rename/tree/search
  operations now resolve paths under the generated root with
  `Path.resolve()` + `relative_to(root)`, reject absolute/drive/UNC/traversal/
  sibling-prefix/symlink escape paths before filesystem side effects, return
  400 for unsafe paths and 404 for missing projects, and preserve allowed
  nested file CRUD/search. Focused containment tests and generated-file status/
  regeneration regressions plus the Worker non-e2e suite passed;
  live-Webwright-dependent IDE e2e still fails before generation on this
  machine, at the known raw-generation prerequisite.

- **C9-09 (2026-06-13):** Hardened Worker run/job identity and artifact
  isolation. Webwright output roots now include `WebwrightRun.id`, generated
  runner `runId` values include `ExecutionRun.id`, both artifact directories
  are reserved with no-overwrite semantics before subprocess work starts, and
  Webwright queue/retry plus execution/rerun APIs return request-unique
  WebSocket `jobId` values. Regression tests cover two same-second Webwright
  starts for one case and two same-second parallel generated-runner executions
  with distinct logs, metadata, result paths, DB rows, and job IDs; focused
  suites, the Worker non-e2e suite, and generated browser contract e2e passed.

- **C3-10 (2026-06-13):** Hardened WSL Webwright command construction. Worker
  raw-generation now builds the Webwright CLI argv separately, invokes
  `wsl.exe bash -lc` only with a constant `.venv` activation wrapper, passes
  root/config/prompt/start URL/task ID/model/shell/step/output values as
  positional argv, and avoids Windows `cwd` for WSL subprocesses. Regression
  tests cover spaces, quotes, parentheses, ampersands, Korean text, and
  shell-looking strings, alongside native subprocess and runtime regressions.

- **C1-10 (2026-06-13):** Added a project-scoped active `automation_key`
  policy across Worker import, generation, mapping merge, and export
  validation. Excel/TestRail/TestRail-clone/Google Sheets imports now normalize
  explicit and generated keys through the same slug/suffix rule, retired and
  deleted cases no longer reserve keys, generation blocks legacy active
  duplicate keys or duplicate flow/test/mapping paths before writing, and
  export validation flags ambiguous active cases, mappings, ExecutionResult
  rows, and results updates. Focused policy, import/export, and generation
  regression tests passed.

- **D9-04 (2026-06-13):** Added a structured desktop Settings control for
  project-scoped selector auto-apply. The new Self-healing section toggles the
  current project ID in canonical `self_healing.autoApplyProjectIds`, merges
  legacy snake_case IDs into the control, preserves unrelated Settings fields
  and advanced JSON editing, and keeps Worker C12-07 guardrails unchanged.
  `npm run build` and focused healing proposal tests passed.

- **D1-08 (2026-06-13):** Added project-scoped `automation_key` deep linking
  in the desktop GUI. The app shell resolves `?automation_key=<key>` against
  the active project's cases and updates selected TC state beyond persisted
  handoff state. Cases, Mapping, and Webwright reuse loaded case lists for
  selection; Mapping no longer silently falls back to the first TC while a
  deeplink is pending; IDE, Results, export-error, and healing handoff actions
  now preserve automation keys when opening Mapping/Webwright. `npm run build`
  passed.

- **C7-17 (2026-06-13):** Added route-segmented generated PageObjects. Worker
  structuring now assigns methods to deterministic route page files from mapped
  Webwright trajectory URLs, generated flows import/instantiate only the page
  classes they use, mapping YAML records actual page object files, selected
  regeneration preserves unrelated route pages, and retire cleanup rebuilds
  shared segmented page files from remaining active origins. Focused
  segmentation/regeneration/retire tests and the non-e2e Worker suite passed.

- **C7-14 (2026-06-13):** Added generated protected regions for page, flow,
  and test Python outputs. Regeneration now merges existing protected-region
  bodies into planned content before preflight/dry-run/write paths, status
  hashing normalizes protected bodies so valid region-only edits remain
  generated, retire control-file rewrites preserve protected content, and
  unprotected edits still surface as edited/conflict. Focused regeneration/
  status/codegen/retire tests and the non-e2e Worker suite passed.

- **C12-13 (2026-06-13):** Extended Worker healing proposals beyond
  `selector_replace`. The create endpoint now accepts explicit `kind` plus a
  structured `proposal` payload and can infer wait/assertion proposals from
  resolved failure evidence or artifact metadata hints. `wait_adjust`,
  `assertion_update`, and `pom_method_patch` persist compact JSON old/new patch
  payloads with diagnosis/target/artifact evidence, share accept/reject status
  transitions, require accepted status before apply, patch targeted
  wait/assertion/POM body-plan state through guarded selected regeneration with
  conflict rollback, keep auto-apply selector-only, and render wait timeouts
  into generated Playwright waits. Focused healing proposal tests, target/
  diagnosis/codegen regressions, and targeted `py_compile` passed.

- **I-10 (2026-06-13):** Strengthened the third-party legal packaging gate.
  `scripts/validate-third-party.ps1 -Strict` now validates vendored Webwright
  notice/license/version metadata, Electron `runtime-staging` to
  `resources/runtime` packaging config, staged and packaged
  `THIRD_PARTY_NOTICES.txt`, live runtime manifests, required notice sections,
  vendored commit consistency, and notice freshness against source
  attribution/license files before distribution. The direct PowerShell command,
  `npm.cmd run validate:third-party`, and `git diff --check` passed.

- **D5-08 (2026-06-13):** Mapping Review now calls the Worker
  `structure/validate` endpoint for the selected case through the Desktop API
  client, merges saved Worker structure/generated-file issues with local draft
  preflight issues, labels issue source as draft or worker, surfaces
  generated-file edited/stale/conflict and Worker validation request failures
  inline without clearing unsaved mapping edits, and refreshes Worker
  validation after Auto Map or Save Edits. `npm run build`, focused Worker
  structure/generated-file validation tests, and `git diff --check` passed.

- **C10-08 (2026-06-13):** Replaced Google Sheets result export local-mock
  with authenticated Sheets API v4 `values:batchUpdate` when the Google Sheets
  integration is enabled. Worker export resolves non-secret spreadsheet, sheet,
  header-row, and result-column config from settings or request config, receives
  one-time credential JSON through desktop main-process secure credential
  mediation, keeps preview read-only with target payloads, validates
  mapping/ExecutionResult identity plus spreadsheet/sheet/row targets before
  mutation, creates missing result headers, writes per-row result cells, logs
  API failures as failed masked `ExportLog` rows, and keeps disabled/mock mode
  available for local/dev tests. Generated mappings now include
  `resultTargets.googleSheets` for Google Sheets sourced cases, Desktop
  Export/IDE panels route non-preview Google Sheets export through secure IPC,
  focused export/import/log/settings tests passed, generated runtime/status
  regressions passed, and `npm run build` passed.

- **C10-07 (2026-06-13):** Replaced TestRail result export local-mock with
  authenticated API v2 `add_result_for_case/{run_id}/{case_id}` when the
  TestRail integration is enabled. Worker export resolves non-secret
  base URL/username/result run ID from settings or request config, receives the
  one-time API token through desktop main-process secure credential mediation,
  keeps preview read-only, validates mapping/ExecutionResult identity before
  mutation, writes status/duration/comment payloads with automation-key
  traceability, logs API failures as failed masked `ExportLog` rows, and keeps
  disabled/mock mode available for local/dev tests. Focused export, log masking,
  settings secret tests, and `npm run build` passed; the broader MVP4 e2e still
  failed before export because its prerequisite Webwright run returned `failed`.

- **C1-09 (2026-06-13):** Replaced the Google Sheets placeholder import with
  authenticated Sheets API v4 values preview/import paths. Worker requests
  receive a one-time OAuth/access-token JSON or service-account JSON from the
  desktop main process secure credential account
  `connector:googleSheets:serviceAccountJson`, keeping plaintext credential JSON
  out of renderer and `settings.json`. Sheet rows normalize through the
  Excel-compatible column mapping into `NormalizedTestCase`, durable import
  saves source location/preconditions/tags/priority/start URL, explicit `mock`
  mode keeps local/dev connector flow usable, and credential-bearing API errors
  are masked. Focused Google Sheets import tests, existing TestRail/import/
  settings/log masking tests, result export validation tests, and `npm run
  build` passed.

- **C1-08 (2026-06-13):** Replaced the TestRail placeholder import with
  authenticated API v2 `get_cases` preview/import paths. Worker requests merge
  non-secret TestRail settings with a one-time token supplied by desktop main
  process from secure credential account `connector:testrail:apiToken`, keeping
  plaintext tokens out of renderer and `settings.json`. TestRail legacy and
  paginated payloads normalize into `NormalizedTestCase`, durable import saves
  source location/preconditions/tags/priority/start URL, explicit `mock` mode
  keeps local/dev connector flow usable, and token-bearing API errors are
  masked. Focused TestRail import tests, existing import/settings/log masking
  tests, result export validation tests, and `npm run build` passed.

- **G-04 (2026-06-13):** Added connector credential metadata via
  `GET /settings/connector-credentials` for TestRail and Google Sheets secure
  store service/account names without returning plaintext secrets. Desktop
  Settings now stores TestRail API tokens and Google Sheets service-account JSON
  through Electron keytar/safeStorage IPC while keeping only non-secret
  integration config in `settings.json`. Settings sanitization now strips
  `serviceAccountJson`, connector metadata masks loggable secret-looking values,
  focused settings/security tests passed, related secret masking suites passed,
  and `npm run build` passed.

- **C7-13 (2026-06-13):** Added project-scoped
  `GET /projects/{project_id}/generated-files/status` for generated-file
  maintenance state. Responses refresh tracked file hashes, preserve known
  source-change `stale`/`conflict` states, include
  edited/stale/conflict/obsolete counts, severity-ordered file rows,
  automation key, primary source, resolved origins, hash/edit/source-change
  flags, and GUI guidance. Focused endpoint tests passed, and existing
  generated-file status, regeneration guard, incremental generation, origin,
  and retire cleanup suites passed.

- **C12-12 (2026-06-13):** Added selected-case
  `GET /projects/{project_id}/cases/{case_id}/selector-candidates` for
  persisted selector candidate evidence. Responses validate case project
  ownership, include stable selector IDs/type/value/confidence/metadata,
  selected-case raw-action and PageObjectMethod review context, grouped
  raw-action/POM candidate IDs, and project-owned source artifact metadata with
  the same safe path suppression used by the artifact API. Focused endpoint
  tests passed, selector ranking and failure diagnosis tests passed, and
  proposal/retire/model self-healing suites passed. The broader live queued
  Webwright selector extraction e2e still fails before this read API because
  local raw generation returns `failed`.

- **C12-11 (2026-06-12):** Added project-scoped
  `GET /projects/{project_id}/artifacts` for indexed Webwright/execution
  evidence with automation-key, source/source-id, artifact-type, Webwright run,
  and execution filters. Responses include stable artifact IDs,
  source/kind/title/hash/timestamps, parsed metadata, and `filePath` only when
  the path is inside known Webwright output or execution result artifact roots.
  Focused API tests passed, self-healing diagnosis/proposal/target resolver
  tests passed, and direct artifact model/indexing tests passed. Broader live
  queued Webwright artifact e2e still fails before the read API because local
  raw generation returns `failed`.

- **D4-07 (2026-06-12):** Generate Raw prompt composer now uses Worker
  `prompt-composer`, `prompt-presets`, and `prompt-preview` APIs instead of
  settings-only/local prompt state. Worker composer state stores selected
  preset continuity, the desktop API client exposes prompt endpoints, project
  presets can be saved/deleted through Worker state, run requests include the
  selected preset, and Worker API failures preserve local draft prompt
  selection. Focused prompt composer/preset/preview tests passed, targeted
  Python compile passed, and `npm run build` passed.

- **C9-08 (2026-06-12):** Execution runs and `rerun-failed` now register active
  `runner.cli` subprocesses by `ExecutionRun.id` and returned `jobId`; cancel
  performs graceful terminate with kill fallback, writes masked cancellation
  diagnostics to stdout/stderr/results artifacts, marks the log stream
  cancelled, and preserves `cancelled` against background overwrite. Cancelled
  runs delete stale `ExecutionResult` rows, index log/metadata artifacts, and a
  later rerun uses a fresh run directory. Focused fake runner cancel tests
  passed, generated-runtime/runner-contract tests passed, and the non-e2e
  Worker suite passed with 164 tests. Two broader live-Webwright-dependent e2e
  runner tests still fail before runner execution because their Webwright raw
  generation setup returns `failed`.

- **C3-09 (2026-06-12):** Webwright live runs now register active
  subprocesses by `WebwrightRun.id` and returned `jobId`; cancel performs
  graceful terminate with kill fallback, stops heartbeat/pipe tasks, writes
  masked cancellation diagnostics to stdout/stderr/log streams, and preserves
  run/case `cancelled` during background artifact harvest. Cancelled runs keep
  harvested log/metadata artifacts, completed-path action extraction is skipped
  for cancelled runs, and retry creates a fresh run row. Focused fake
  long-running Webwright cancel tests passed, existing Webwright/action
  extraction tests passed, and the non-e2e Worker suite passed with 161 tests.

- **C7-16 (2026-06-12):** Structuring now ranks extraction-time
  `SelectorCandidate` rows before writing body-plan selectors, choosing
  compatible high-confidence candidates with stability order
  `test_id > role > text > css > xpath`. Body-plan entries keep raw selector,
  selected candidate, runner-up confidence/provenance, and fallback metadata;
  low-confidence, ambiguous, incompatible, missing, and healing-only candidates
  preserve raw selectors. The same path is used during selected raw refresh
  merge, and generated code consumes the ranked selector. Focused selector
  ranking tests passed, targeted structuring/codegen/raw-refresh/regeneration
  tests passed, and the non-e2e Worker suite passed with 159 tests.

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

