# Structuring Spec

Last aligned: 2026-06-04

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

Open:

- C6-07: ordered multi-action mapping API follow-up.
- C7-10: stale/conflict detection.
- C7-11: structured method body planner coverage.
- C7-12: selected raw refresh merge into existing structure.
- C8-06: deterministic regeneration guard.
- C8-07: `GeneratedFileOrigin` link persistence.
- C8-09: selected TC incremental regeneration.
- C8-10: TC retire/delete generated artifact cleanup.
- C12-09: selected TC Webwright refresh regeneration flow.
- C12-10: TC retire recommendation and cleanup flow.
- E-11: selected TC Webwright refresh incremental regeneration E2E.
- E-12: feature-removed TC retire cleanup E2E.
- E-10: generated pytest/browser contract E2E.
