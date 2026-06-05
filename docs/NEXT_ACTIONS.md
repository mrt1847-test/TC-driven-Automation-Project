# Next Actions

Last aligned: 2026-06-05

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
8. Advance the queue:
   - First, move the next still-open item from **Next Batch Candidates** into
     **Current Batch** and remove/reorder that candidate list.
   - If **Next Batch Candidates** is empty or all listed candidates are already
     complete, scan [IMPLEMENTATION_CHECKLIST.md](./IMPLEMENTATION_CHECKLIST.md)
     for the next unchecked checklist item whose dependencies are already
     complete.
   - Prefer items called out by the implementation audit/spec-gap notes, then
     continue in checklist order within the same phase/layer.
   - Populate **Current Batch** with the checklist item, owning specs, concise
     scope, and acceptance evidence from the checklist and owning spec.
9. Add a short note under **Completed Batch Notes**.

If the current batch cannot be completed, do not advance the queue. Record the
blocker in the final response and leave `Current Batch` unchanged.

If no valid current batch, candidate, or dependency-satisfied unchecked
checklist item remains, set **Current Batch** to no current batch and report
that the queue is empty. Do not invent work outside the checklist.

## Rules For AI

1. Do not add a new docs file unless the user explicitly asks for a new document.
2. Do not duplicate source-of-truth content from specs into this file.
3. Close at most one main checklist item per implementation batch unless the user asks for a larger batch.
4. If a task uncovers a planning gap, update the owning source-of-truth spec and checklist, not a new side document.
5. Keep supporting guides subordinate to the owning spec listed in [SPEC_INDEX.md](./SPEC_INDEX.md).
6. Keep this file short: it should identify the next task, not restate the whole spec.

## Current Batch

**Checklist item:** G-03 generated project secret separation

**Why this is next:** F-02 is complete and there is no explicit queued
candidate. The next dependency-satisfied unchecked Phase 1 item is G-03, whose
dependency B1-03 is already complete and whose scope belongs to the generated
project template contract.

**Owning specs:** [GENERATED_PROJECT_SPEC.md](./GENERATED_PROJECT_SPEC.md),
[RUNTIME_SPEC.md](./RUNTIME_SPEC.md)

**Implementation scope:**

- Inspect the generated template config files, runner fixtures, runtime
  manifest generation, project generator copy/write path, and `.gitignore`
  before editing.
- Ensure generated `config/env.*.json`, `config/automation.yaml`, README,
  runtime manifest, runner outputs, and committed template files never contain
  plaintext API keys or provider secrets.
- Keep secrets supplied through environment variables, Studio/keytar-backed
  runtime injection, or ignored local override files.
- Preserve standalone runner behavior for environment selection, browser
  options, base URL, storage state, and artifact policy.
- Add focused template/generator tests for secret separation and run the
  relevant generated-template and worker regression tests.

**Acceptance evidence:**

- Generated project outputs and tracked template files contain placeholders or
  variable names only, not secret values.
- Secret-bearing local override files are ignored by generated Git output and
  are not included in runtime manifests, results, logs, or generated metadata.
- Standalone and Studio runner paths still receive required non-secret runtime
  settings.
- Build and focused template/worker regression tests pass as far as the local
  environment allows.

## Next Batch Candidates

Pick the next item from this list after Current Batch is done:

| Order | Checklist item | Purpose |
|-------|----------------|---------|
| - | - | No explicit queued candidate; after G-03, scan the checklist for the next dependency-satisfied open item. |

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
- 2026-06-04: Completed C6-07 ordered multi-action Mapping API. Mapping GET/PUT
  now round-trips ordered joins, atomically replaces/removes stale links, keeps
  the legacy first-action field aligned, and rejects invalid or foreign action
  IDs without partial rewrites.
- 2026-06-04: Completed C7-11 structured method body planner coverage.
  Structuring now produces deterministic ordered plans with stable source IDs,
  preserves supported selectors/value templates, and forces review for
  unsupported/missing actions and hard waits.
- 2026-06-05: Completed C8-07 GeneratedFileOrigin link persistence. Generation
  now records complete case and structured origins, aggregates shared-file
  origins, and replaces stale links and duplicate path metadata on regeneration.
- 2026-06-05: Completed C7-12 selected raw refresh merge. Selected Webwright
  reruns now preserve reviewed structure and unrelated cases, update safely
  matched raw links/body plans in place, and route ambiguous changes to review.
- 2026-06-05: Completed C8-09 selected TC incremental regeneration. Selected
  generation now rewrites only selected and origin-linked shared files, merges
  mappings, replaces rewritten-file origins, and preserves unrelated files,
  metadata, runtime content, and artifacts.
- 2026-06-05: Completed C12-09 selected TC Webwright refresh regeneration.
  The maintenance API now safely chains selected rerun, raw merge, and
  incremental generation, returning review-required results before generation.
- 2026-06-05: Completed C8-10 TC retire/delete generated artifact cleanup.
  Confirmed soft cleanup now preserves audit history and shared content while
  removing only provably selected files and stopping on edit/shared conflicts.
- 2026-06-05: Completed C12-10 TC retire recommendation and cleanup flow.
  Diagnosis-bound retire/delete now validates the failed result and selected TC
  before cleanup, rejects unsafe requests without mutation, and returns
  diagnosis evidence with cleanup details.
- 2026-06-05: Completed C12-05 healing proposal generation API. Selector
  failures now create evidence-backed proposal rows, duplicate requests return
  the existing proposal, and non-selector/unresolved diagnoses stay
  proposal-free.
- 2026-06-05: Completed C7-10 stale/conflict detection. Generated-file status
  refresh now detects on-disk edits, marks planned source changes as stale or
  conflict, blocks source-changed edited incremental rewrites, and surfaces
  status through generated-file metadata and structure validation.
- 2026-06-05: Completed C8-06 deterministic regeneration guard. Full and
  selected generation now preflight tracked files before rewrite/delete, block
  edited/conflict files with deterministic summaries, and prove unchanged full
  regeneration is byte-stable.
- 2026-06-05: Completed C12-06 accepted proposal apply/regenerate/rerun flow.
  Proposal decisions now preserve evidence, accepted selector replacements
  patch structured selectors through guarded selected regeneration, and
  conflicts stop before persisted mutation or file rewrite.
- 2026-06-05: Completed C12-07 safe auto-apply guardrails. Auto-apply is
  project-enabled only, requires strict selector evidence and one
  high-confidence semantic candidate, reuses the accepted apply path, and
  blocks low-confidence, ambiguous, stale, or conflict cases without selector
  or generated-file content mutation.
- 2026-06-05: Completed C2-04 batch prompt and per-case override model. Worker
  prompt composer state now round-trips through project-scoped storage,
  rejects foreign case overrides, and appends effective context to Webwright
  prompts while preserving no-context behavior.
- 2026-06-05: Completed C2-05 prompt preset model. Worker preset APIs now seed
  stable built-ins, round-trip project presets with deterministic ordering,
  reject foreign/built-in collisions, and keep existing Webwright prompt
  composition unchanged until preview/run payload features opt in.
- 2026-06-05: Completed C2-06 prompt preview API. Worker preview now combines
  base TC prompt, optional built-in/project preset guidance, saved batch
  prompt, and per-case override without starting Webwright or creating
  run/history rows.
- 2026-06-05: Completed C2-07 prompt payload traceability. Webwright run
  creation now records immutable prompt payload snapshots with final/base
  prompt, selected preset, batch/case context, environment, start URL, and
  effective model config; list/read APIs expose history by project, case, and
  run.
- 2026-06-05: Completed C8-04 Git repo-capable generated output. Generation
  now writes deterministic Git-ready ignore rules, keeps
  `artifacts/runs/.gitkeep`, excludes stale template caches/artifacts, and
  preserves existing `.git`, `.gitattributes`, and `.gitmodules` metadata.
- 2026-06-05: Completed C8-08 generated-project runtime manifest. Generation
  now writes deterministic `config/runtime-manifest.json`, tracks it as
  generated metadata, preserves selected-generation summaries unless runtime
  inputs change, and blocks edited manifests before overwrite.
- 2026-06-05: Completed C9-07 per-project runtime install state/cache.
  Generated runtime bootstrap now caches successful project/runtime readiness,
  skips redundant install commands on valid hits, invalidates stale runtime
  inputs, and keeps failed installs out of ready cache state.
- 2026-06-05: Completed C6-03 action CRUD. Mapping review now has
  project/case-scoped action create/update/delete APIs with ownership
  validation, ordered join repair on delete, and structure-sync handoff tests.
- 2026-06-05: Completed C6-04 assertion/wait additions. Mapping review now has
  step-scoped assertion/wait insertion/update APIs with ordered join placement,
  ownership/type validation, and structure-sync body-plan coverage.
- 2026-06-05: Completed F-02 Mapping error UX. Mapping Review now surfaces
  Mapping API validation failures inline, preserves local edits and selected TC
  on failed save/auto-map requests, and shares FastAPI detail extraction across
  Mapping save/action/assertion-wait client calls.
