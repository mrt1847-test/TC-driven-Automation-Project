# Structuring Spec

Last aligned: 2026-06-05

This document defines how Webwright raw output becomes a maintainable
Playwright pytest project.

Generate Raw produces raw artifacts. Automation IDE owns review, structure,
generation, execution, and feedback.

Related specs:

- [GENERATED_PROJECT_SPEC.md](./GENERATED_PROJECT_SPEC.md)
- [RUNTIME_SPEC.md](./RUNTIME_SPEC.md)
- [DB_SCHEMA.md](./DB_SCHEMA.md)
- [SELF_HEALING_SPEC.md](./SELF_HEALING_SPEC.md)

## Pipeline

```text
Imported TC
  -> Webwright final_script.py / trajectory.json
  -> ArtifactAsset / SelectorCandidate
  -> RawAction
  -> CaseActionMapping / CaseActionMappingAction
  -> StructuredFlow / StructuredStep
  -> PageObject / PageObjectMethod
  -> GeneratedFile / GeneratedFileOrigin
  -> generated tests, flows, pages, fixtures, mappings
```

Raw files are evidence. Structured DB entities are the source of truth for code
generation.

For an already structured/generated project, rerunning Webwright for selected
TCs is a raw refresh operation. It must not discard the existing structured
model and start from zero unless the user explicitly chooses a reset.

## Raw Inputs

| Input | Role | Stored in DB |
|-------|------|--------------|
| `final_script.py` | primary raw code source | path and extracted facts |
| `trajectory.json` | browser-event enrichment | path and extracted facts |
| screenshots/logs | review evidence | artifact path/hash/metadata |
| imported TC steps | user intent | normalized fields and JSON |

Do not store full generated source as primary DB data. Store facts, relations,
and traceability links.

## Step 1: Action Extraction

`final_script.py` and `trajectory.json` should produce ordered `RawAction`
records.

Extraction must preserve:

- action order;
- Playwright action type;
- locator/selector expression;
- target/value/text/input data;
- source line;
- originating Webwright run;
- artifact evidence when available;
- selector candidates and confidence when available;
- parse warnings for unsupported code.

Minimum action coverage:

- navigation: `goto`;
- interaction: `click`, `fill`, `press`, `check`, `uncheck`, `select_option`,
  `set_input_files`, `hover`, `drag_to`;
- assertion: `expect(...).to_*`;
- waiting: `wait_for_*`, locator wait, network/load state wait;
- custom/unsupported: preserve raw text and require review.

C5-05 implementation behavior:

- parse the complete `final_script.py` with Python `ast` before falling back to
  the legacy line parser;
- walk Playwright calls in source order, including calls inside functions,
  multi-line statements, `await` expressions, `with`/`async with` contexts,
  and chained locators;
- resolve simple locator aliases assigned from Playwright locator expressions
  before action, assertion, wait, and unsupported-call extraction;
- extract supported `expect(...).to_*` assertions with selector/value metadata;
- preserve unsupported Playwright calls as `custom_code` with focused raw text
  so Mapping Review can inspect them;
- keep deterministic `order_index`, `source_line`, selector, value, and
  action-type metadata compatible with mapping and trajectory enrichment.

## Step 2: TC Mapping

Reviewed mapping connects TC steps to one or more raw actions.

| Status | Meaning |
|--------|---------|
| `mapped` | accepted relation |
| `needs_review` | uncertain relation |
| `unmapped` | TC step has no raw action |
| `ignored` | raw action should not generate code |

One TC step may map to multiple raw actions. `CaseActionMappingAction` should
preserve ordered joins.

Mapping review API requirements:

- allow reviewed raw actions to be created, updated, and deleted only through a
  selected project/case route;
- allow reviewed assertion/wait actions to be inserted through a selected
  project/case/TC-step route, with unsupported action types rejected before
  mutation;
- validate edited or deleted action ownership against the selected case's
  Webwright runs before mutation;
- validate step-scoped assertion/wait updates against both selected-case action
  ownership and the selected TC step's ordered mapping links;
- when deleting an action, remove selected-case ordered joins to it, keep
  `CaseActionMapping.raw_action_id` aligned to the first remaining action, and
  mark mappings with no remaining actions as `unmapped`/review-required;
- persist and return each step's `action_ids` in submitted join order;
- validate action ownership against the selected case's Webwright runs before
  replacing mappings;
- replace or remove stale joins atomically, without partially rewriting a
  reviewed case on validation failure;
- keep legacy `CaseActionMapping.raw_action_id` aligned with the first ordered
  action for backward compatibility.

## Step 3: Structured Flow

`StructuredFlow` is a versioned automation intent model for a TC.

Each `StructuredStep` should contain:

- order index;
- reviewed human-readable step name;
- kind: navigation, interaction, assertion, wait, helper, custom_code;
- mapping ID;
- related raw action IDs through the mapping join;
- page object method link;
- metadata for env/test data placeholders where needed.

The flow is still data, not Python.

## Step 4: Page Object Method Planning

`PageObjectMethod` must describe executable behavior before Python generation.

`body_plan_json` should be a deterministic ordered list:

```json
[
  {
    "action": "fill",
    "selector": "page.get_by_label(\"Email\")",
    "value": "${env.user.email}",
    "sourceRawActionId": "act_001",
    "sourceMappingId": "map_001"
  },
  {
    "action": "click",
    "selector": "page.get_by_role(\"button\", name=\"Login\")",
    "sourceRawActionId": "act_002",
    "sourceMappingId": "map_001"
  },
  {
    "action": "expect_visible",
    "selector": "page.get_by_text(\"Dashboard\")",
    "sourceRawActionId": "act_003",
    "sourceMappingId": "map_002"
  }
]
```

Planner requirements:

- compile multi-action mapped steps into one method when the TC step represents
  one business action;
- preserve individual methods when reuse or clarity is better;
- represent assertions and waits explicitly;
- convert hard waits into review warnings unless they are intentionally accepted;
- support value placeholders from env config or test data;
- mark unsupported actions as `custom` and require review before generation;
- keep method names deterministic.

Persisted planner entry contract:

- `order` follows `CaseActionMappingAction.order_index`;
- `sourceMappingId` and `sourceRawActionId` are present on every entry;
- `selector`, `value`, and `target` preserve the extracted values without
  rewriting data/env placeholders;
- supported assertion, wait, select, check, upload, and interaction actions
  remain explicit action types;
- unsupported/missing actions and hard waits set `requiresReview=true` with a
  stable `reviewReason`;
- any review-required entry keeps the PageObjectMethod in `draft`, marks the
  StructuredFlow `needs_review`, and is reported by structure validation.

## Step 5: Code Generation

The generator reads structured DB entities:

| Generated output | Source |
|------------------|--------|
| `flows/{automation_key}_flow.py` | `StructuredFlow` + ordered `StructuredStep` |
| `pages/generated_page.py` or page-specific files | `PageObject` + `PageObjectMethod.body_plan_json` |
| `tests/test_{automation_key}.py` | TestCase + flow |
| `mappings/cases.yaml` | TestCase + generation metadata |
| runtime manifest | template + runtime/generation metadata |

Generated code should not inspect raw scripts directly. If raw evidence changes,
the pipeline should update RawAction/mapping/structured data first, then
regenerate.

## Generated File Traceability

Each generated file needs:

- relative path;
- content hash;
- status: generated, edited, stale, conflict;
- primary source type/source ID for simple lookup;
- `GeneratedFileOrigin` rows for every relevant origin.

Recommended origins:

- TestCase;
- StructuredFlow;
- StructuredStep;
- PageObject;
- PageObjectMethod;
- CaseActionMapping;
- RawAction;
- WebwrightRun.

Generation persistence contract:

- write generated-file metadata after the corresponding file exists so
  `content_hash` describes the actual output;
- keep one active `GeneratedFile` row per project and relative path;
- attach the complete relevant origin set to case-specific files;
- attach the union of current relevant case origins to shared page and mappings
  files;
- replace the origin set on regeneration, removing stale origins and duplicate
  metadata rows while retaining the primary source fields for compatibility.

This is required for:

- impact analysis when raw actions or mappings change;
- safe regeneration;
- self-healing proposals;
- explaining why a line of generated code exists.

## Regeneration Rule

Regeneration must be deterministic:

- same structured data + same template version = same generated files;
- edited generated files must be detected by comparing stored hash with current
  file hash;
- if the source changed and the file was edited, mark conflict instead of
  silently overwriting;
- if the source changed and the file was untouched, regenerate and update hash;
- protected regions may be introduced later, but conflict detection comes first.

## Selected Raw Refresh Merge

Selected raw refresh is the maintenance path where the user picks one or more
already-structured TCs and reruns Webwright to get fresh raw scripts/actions.
This is not limited to flow/order failures. It may be user-initiated because the
target application changed, the original raw script was weak, or the user wants
to refresh only a few cases in a larger generated project.

The merge target is the existing structured state:

```text
new WebwrightRun / RawAction
  -> compare with previous RawAction and CaseActionMapping
  -> update mapping candidates for selected TC
  -> preserve reviewed StructuredStep names/order where intent still matches
  -> update PageObjectMethod.body_plan_json where actions/selectors changed
  -> mark ambiguous changes as needs_review or conflict
  -> selected incremental generation
```

Merge requirements:

- preserve `automation_key`, TC identity, reviewed step names, and human-edited
  intent wherever possible;
- compare old and new raw action sequences by action type, selector candidates,
  target URL, text/value, and surrounding artifact evidence;
- carry forward existing mappings when a new action is equivalent or clearly
  replaces an old action;
- create new mapping candidates when new raw actions appear;
- mark removed or unmatched structured steps as `needs_review` instead of
  silently deleting them;
- update `PageObjectMethod.body_plan_json` from the new raw actions only after
  the mapping/intent match is safe;
- keep old raw artifacts linked for diff/review;
- never regenerate unrelated cases as part of the merge.

If the merge cannot prove intent continuity, it should stop at reviewed mapping
state and require Automation IDE review before code generation.

## Selected TC Incremental Regeneration

When generation is requested for selected `caseIds`, the generator must treat it
as an incremental maintenance operation unless the request explicitly says
`mode=full`.

Selected regeneration must:

- preserve unrelated generated tests, flows, page files, runner files, fixtures,
  and artifact folders;
- consume the merged structured state from Selected Raw Refresh Merge when a
  selected TC was rerun through Webwright;
- update only files whose `GeneratedFileOrigin` links reference the selected
  TestCase, StructuredFlow, StructuredStep, PageObjectMethod, mapping, raw
  action, or Webwright run;
- merge `mappings/cases.yaml` entries instead of rewriting it from only the
  selected case subset;
- use the stored `content_hash` to detect user-edited files;
- mark a file `conflict` when a selected source changed but the file was edited;
- mark a file `stale` when impacted source data changed but regeneration was
  deferred;
- return an affected-file summary so Automation IDE can show the user what
  changed and what remained untouched.

The current product goal is to support a project with many generated TCs where
one failed TC can be rerun through Webwright, restructured, and regenerated
without deleting the other generated tests.

Full regeneration is allowed only when the user explicitly requests it. Full
regeneration still must respect stale/conflict guards for edited files.

C8-09 implementation behavior:

- selected `caseIds` default to incremental mode and reuse the latest merged
  structured flow instead of rebuilding structure;
- selected test/flow files and origin-linked shared page/mapping files are
  rewritten, while unrelated generated/runtime/artifact files and metadata
  remain untouched;
- `mappings/cases.yaml` replaces selected entries in place and preserves
  unrelated entries;
- only rewritten files receive replacement `GeneratedFileOrigin` sets;
- the API returns deterministic affected, content-changed, and preserved file
  lists;
- selected structure in `needs_review` stops before file writes.

C8-06 implementation behavior:

- full and selected generation preflight tracked generated files before any
  rewrite/delete, including tracked files scheduled to disappear in a full
  rebuild;
- edited or conflict files block generation with a deterministic conflict
  summary before the output tree is modified;
- source-changed but untouched files can be regenerated and return to
  `generated` after metadata/hash replacement;
- unchanged full regeneration is byte-stable and reports no changed files;
- selected generation preserves unrelated generated/runtime/artifact files, and
  full regeneration deletes/rebuilds only after the guard passes.

C8-04 implementation behavior:

- generated output always includes deterministic Git-ready ignore rules and an
  `artifacts/runs/.gitkeep` placeholder;
- full regeneration preserves existing `.git`, `.gitattributes`, and
  `.gitmodules` metadata while rebuilding generated/template content;
- template copy excludes local caches and stale run artifacts so generated
  projects start clean for Git tracking.

C7-10 implementation behavior:

- generated-file status refresh compares each tracked file's stored
  `content_hash` with the current on-disk hash and marks mismatches as
  `edited`;
- planned incremental generation compares the future generated content hash
  with the stored hash to identify source-changed files;
- source-changed and untouched files are reported as `stale` before rewrite,
  then return to `generated` after successful regeneration updates metadata;
- source-changed and edited files are marked `conflict` and block file writes
  before any overwrite;
- generated-file status is surfaced in `/generated-files` metadata and
  `structure/validate` issues when `edited`, `stale`, or `conflict`.

## TC Retire / Delete Cleanup

When failure disposition concludes that a product area was removed, the system
may recommend retiring or deleting the TC. The user must confirm the action.

Retire/delete cleanup must:

- preserve execution history and artifact records for audit;
- set the TC to a project-defined retired/deleted state before generated cleanup;
- remove or mark obsolete the generated test file for that TC;
- remove or update the `mappings/cases.yaml` entry;
- remove flow code only when no active TC references the same flow;
- remove page object methods only when no active TC references the same method;
- update `GeneratedFile` and `GeneratedFileOrigin` rows after cleanup;
- return a cleanup summary including preserved shared files.

Shared page objects and helper methods must be reference-counted through origin
links before deletion. If the impact cannot be proven, mark the generated file
for manual review instead of deleting it.

C8-10 implementation behavior:

- requires explicit human confirmation and supports soft `retired` or `deleted`
  TestCase terminal states so all source/raw/structured/execution/artifact
  history remains queryable;
- preflights every impacted generated file against stored status, hash, and
  active-case origin links before changing TC state or files;
- removes selected private test/flow files and marks their metadata `obsolete`
  while retaining historical origins;
- removes the selected mapping entry and rebuilds shared page/mapping files and
  origins from remaining active cases, preserving methods still referenced by
  another case;
- returns deterministic affected/removed/updated/obsolete/preserved/conflict
  summaries;
- returns `conflict` without cleanup when edited/hash-mismatched files or
  unproven shared references are present.

C12-10 disposition binding behavior:

- accepts retire/delete only for an explicitly confirmed failed execution
  result classified as `feature_removed_retire_tc`;
- verifies the resolved diagnosis project, execution, automation key, source
  context, and sole target TC match the selected case before cleanup;
- rejects unresolved, non-feature-removed, mismatched, or unconfirmed requests
  without changing the TC or generated files;
- delegates safe requests to C8-10 and returns diagnosis reason, confidence,
  evidence, target, and deterministic cleanup details together.

## Structure Validation

`/projects/{project_id}/cases/{case_id}/structure/validate` should report:

- missing structured flow;
- missing mappings;
- mappings in `needs_review`;
- unmapped required TC steps;
- missing step names;
- missing or unsupported PageObjectMethod plans;
- step count mismatch;
- unsupported actions requiring manual review;
- stale/conflict status for generated files when known.

## Self-Healing Relationship

Execution failures should trace back through:

```text
ExecutionResult
  -> automationKey
  -> GeneratedFile / GeneratedFileOrigin
  -> PageObjectMethod / StructuredStep
  -> CaseActionMapping
  -> RawAction
  -> Webwright artifacts / SelectorCandidate
```

The generated Python file should not be patched first. Preferred order:

1. create healing proposal;
2. update `PageObjectMethod` or structured metadata if accepted;
3. regenerate or apply a guarded patch;
4. rerun selected/failed case.

## Implementation Status

Done:

- StructuredFlow and StructuredStep models exist.
- PageObject and PageObjectMethod models exist.
- structure sync and validate APIs exist.
- project generator reads structured entities.
- GeneratedFile stores hash/status and simple source fields.
- failure disposition classifier resolves structured targets before returning
  evidence-backed maintenance dispositions.
- C5-03 action extraction covers the core 17 action types plus file upload and
  drag interactions, preserving unsupported Playwright calls as reviewable
  `custom_code`.
- C5-05 action extraction parses complete Python ASTs for multi-line,
  async/await, chained locator, locator-alias, context-manager, and assertion
  shapes, while retaining the legacy line parser as a syntax-error fallback and
  preserving unsupported Playwright calls as reviewable `custom_code`.
- C6-07 Mapping GET/PUT round-trips ordered multi-action joins, atomically
  replaces/removes stale links, validates selected-case action ownership, and
  keeps the legacy first-action field aligned.
- C6-03 action CRUD creates reviewed actions on the selected case's latest run,
  updates only selected-case actions, deletes selected-case actions while
  repairing ordered joins and legacy first-action compatibility, and rejects
  foreign action mutation before partial writes.
- C6-04 assertion/wait insertion adds step-scoped review APIs that create or
  update only supported assertion/wait actions, place them in the selected TC
  step's ordered mapping joins, and preserve explicit assertion/wait body-plan
  entries through structure sync.
- C7-11 structuring compiles ordered mapping joins into deterministic,
  source-traceable PageObjectMethod body plans and preserves unsupported or
  hard-wait actions as explicit review-required entries.
- C8-07 generation persists complete `GeneratedFileOrigin` sets, aggregates
  shared-file origins, and replaces stale origins and duplicate path metadata
  during regeneration.
- C7-10 generated-file status refresh detects on-disk edits from stored hashes,
  marks planned source changes as stale/conflict before incremental rewrites,
  blocks source-changed edited files, and exposes generated-file status through
  file metadata and structure validation.
- C8-06 full/selected generation guard runs before rewrite/delete, blocks
  edited/conflict tracked files with deterministic summaries, and keeps
  unchanged regeneration byte-stable.
- C7-12 selected raw refresh conservatively merges equivalent replacement
  actions into existing reviewed mappings, flows, steps, and method body plans
  in place, while preserving unrelated cases and routing count, order,
  ambiguity, or shared-method conflicts to `needs_review`.
- C8-09 selected incremental generation rewrites selected case files and
  origin-linked shared files, merges mappings, replaces only rewritten-file
  origins, preserves unrelated files/artifacts/metadata, and returns affected,
  changed, and preserved file summaries.
- C12-09 selected raw refresh regeneration chains a selected run and safe raw
  merge into incremental generation, returns traceable outcomes, and stops
  before generation on review-required changes.
- C8-10 confirmed retire/delete cleanup removes only provably selected
  generated artifacts, preserves shared content and audit history, and stops
  without cleanup on edited or unproven shared conflicts.
- C12-10 diagnosis-bound retire/delete invokes cleanup only for the resolved
  selected TC and preserves diagnosis evidence in the maintenance response.
- E-11 selected raw refresh incremental regeneration E2E proves many-case
  projects preserve unrelated generated artifacts while only selected-case files
  change after safe merge and incremental regeneration.
- E-12 feature-removed TC retire cleanup E2E proves diagnosis-bound retire
  preview/apply removes only the selected TC artifacts while preserving unrelated
  generated cases and execution evidence.
- C8-11 code generation renders the full ordered `body_plan_json` per method:
  all plan entries emit in order, planned `select`/`set_input_files`/`drag_to`
  interactions, locator/load-state waits, and `assert_*` entries materialize as
  Playwright `expect(...)` assertions, while `wait_for_request/response`,
  review-required, and unsupported entries remain deterministic review
  comments (see GENERATED_PROJECT_SPEC code generation contract).
- C8-12 code generation parameterizes values: `goto` URLs matching the
  configured default-env `baseUrl` origin emit as relative paths resolved by
  the runtime context `base_url` (so `TC_ENV` switching applies), foreign
  origins stay absolute, and `${env.dot.path}` placeholders in body-plan
  values render as runtime `self._env_value(...)` lookups backed by a
  self-contained env-config loader emitted only when placeholders exist
  (see GENERATED_PROJECT_SPEC value parameterization contract).
