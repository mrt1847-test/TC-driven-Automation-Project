# Self-Healing And Failure Disposition Spec

Last aligned: 2026-06-04

Webwright produces raw code, logs, screenshots, trajectory, and run metadata.
Generated pytest runs produce logs, screenshots, traces, videos, and
`results.json`. These artifacts are retained so Automation IDE can diagnose a
failed TC and route it to the correct maintenance action.

**Product workspace:** Automation IDE
([PRODUCT_PILLARS.md - Workspace 2](./PRODUCT_PILLARS.md#workspace-2-automation-ide---structure--edit--run)).
Raw artifacts originate in Generate Raw; diagnosis and repair happen inside
Automation IDE, with reverse handoff to Generate Raw only when a selected TC
needs a fresh Webwright run.

## Goal

When a generated automation project fails, the system must distinguish:

- a selector-only change that can be handled by self-healing;
- a selected raw refresh where the user reruns Webwright for already-structured
  TCs and expects the new raw script/actions to merge into the existing
  structured/generated project;
- a removed product area that requires a human-confirmed TC retire/delete and
  generated artifact cleanup;
- an unknown failure that needs manual diagnosis.

The user should not have to regenerate a whole 50-case project because one TC
needs a new raw script. Unrelated generated tests must remain untouched.

## Artifact Sources

| Source | Examples | Usage |
|--------|----------|-------|
| Webwright generation | `final_script.py`, `trajectory.json`, screenshots, logs | original selector/action/flow evidence |
| Mapping review | raw code, screenshots, log snippets, user-edited mappings | human validation context |
| Structured DB entities | `StructuredStep`, `PageObjectMethod`, `GeneratedFileOrigin` | impact analysis and regeneration target |
| Generated project run | pytest logs, Playwright trace, screenshots, videos, `results.json` | failure evidence |
| External TC source | TC steps, expected result, source metadata | intent validation and retire/delete context |

Store paths and metadata, not large blobs:

- artifact type;
- file path;
- related `automation_key`;
- related raw action / structured step / page object method / execution result;
- timestamp and content hash;
- metadata JSON for viewport, URL, DOM hints, error category, and confidence.

## Failure Disposition

Each failed case should receive one disposition with evidence and confidence.

| Disposition | Meaning | Primary action |
|-------------|---------|----------------|
| `selector_changed` | Same user flow, but locator no longer resolves or strict matching changed | create selector healing proposal |
| `raw_refresh_required` | Existing structured/generated TC needs fresh Webwright raw evidence, either from a failure or a user-selected maintenance refresh | rerun Webwright for selected TC, merge raw actions into existing structured data, incrementally regenerate affected files |
| `feature_removed_retire_tc` | Product area or TC intent is no longer valid | require human confirmation, retire/delete TC, cleanup generated artifacts |
| `unknown` | Not enough evidence or mixed causes | show evidence and ask for manual diagnosis |

The classifier must link the failure back through:

```text
ExecutionResult
  -> automation_key
  -> GeneratedFile / GeneratedFileOrigin
  -> PageObjectMethod / StructuredStep
  -> CaseActionMapping
  -> RawAction
  -> Webwright artifacts / SelectorCandidate
```

Classification is read-only and conservative:

- unresolved or ambiguous target links return `unknown`;
- mixed disposition signals return `unknown`;
- `selector_changed` requires a resolved target plus linked selector context;
- classification does not create/apply proposals or mutate structured data.

## Selector Healing

Selector healing is a reviewable patch, not a silent rewrite.

```json
{
  "kind": "selector_replace",
  "disposition": "selector_changed",
  "target": {
    "page_object_method_id": "pom_123",
    "old_selector": "page.locator(\"#login\")"
  },
  "proposal": {
    "new_selector": "page.get_by_role(\"button\", name=\"Login\")",
    "confidence": 0.88,
    "evidence_artifact_ids": ["art_001", "art_009"]
  },
  "status": "proposed"
}
```

Suggested statuses:

- `proposed`
- `accepted`
- `rejected`
- `applied`
- `superseded`

Automatic apply is allowed only when all are true:

- failure is selector-not-found or strict-mode selector mismatch;
- exactly one high-confidence candidate exists;
- proposed selector points to the same accessible role/text or same stable test id;
- no manually edited/conflict generated file would be overwritten;
- user has enabled auto-apply for this project.

Otherwise, create a proposal and require user confirmation.

## Selected TC Raw Refresh

Use this path when the failure disposition is `raw_refresh_required`, or when
the user explicitly chooses to rerun Webwright for selected TCs that are already
structured/generated.

```text
Already structured/generated TC
  -> user selects "Refresh Webwright raw for this TC"
  -> Generate Raw reruns only selected case_id / automation_key
  -> RawAction and mapping candidates refresh for that TC
  -> raw refresh merge updates existing StructuredStep/PageObjectMethod plans
  -> selected incremental generation rewrites only affected generated files
  -> user reruns selected TC
```

Requirements:

- preserve the selected `case_id` and `automation_key` across the workspace
  handoff;
- keep old raw artifacts available for comparison;
- preserve reviewed structured names, TC intent, and user edits when the new raw
  actions still match the existing intent;
- stop at `needs_review` or `conflict` when the new raw actions cannot be safely
  merged into the existing structured model;
- do not delete unrelated generated tests, flows, pages, or mappings;
- mark generated files as `stale` or `conflict` when origin/hash checks cannot
  safely apply the update;
- show the affected-file list before applying changes.

## TC Retire/Delete

Use this path when the failure disposition is `feature_removed_retire_tc`.

The system may recommend retire/delete, but the human must confirm it. The UI
must explain why the TC appears obsolete, using execution failure evidence and
source TC context.

After confirmation:

- set the TC to `retired` or delete it according to project policy;
- remove the generated test file for that TC;
- remove or update `mappings/cases.yaml` entries;
- remove flow/POM code only when no other TC still references it;
- update `GeneratedFile` / `GeneratedFileOrigin` status and hashes;
- preserve artifacts and execution history for audit.

## UI Requirements

Self-healing and failure disposition belong inside Automation IDE.

Recommended panels:

- Failure Diagnosis panel;
- screenshot / trace / log evidence tabs;
- selector candidates table;
- disposition badge with confidence and reason;
- action buttons for Self-Heal, Rerun Webwright for Selected TC, Retire TC, or
  Manual Diagnosis;
- proposed patch or affected-file diff before apply;
- rerun selected/failed cases after apply.

## Non-Goals

- Do not silently rewrite generated code without traceability.
- Do not store screenshots or traces as DB blobs.
- Do not treat visual similarity alone as enough for auto-apply.
- Do not retire/delete a TC automatically.
- Do not regenerate the whole project for a selected TC maintenance action
  unless the user explicitly requests full regeneration.

## Implementation Status

Done:

- Webwright artifacts are indexed.
- raw action selector candidates are persisted.
- execution failure artifacts are indexed.
- C12-04 failure-to-structured target resolver returns linked target/evidence
  IDs with deterministic resolved, missing, or ambiguous status.
- C12-08 failure disposition classifier and execution diagnosis API return one
  evidence-backed disposition per failed result, with conservative `unknown`
  fallback for unresolved, mixed, or unsupported evidence.
- baseline GUI diagnosis panel exists.

Open:

- C12-05: healing proposal API.
- C12-06: accepted proposal apply/regenerate/rerun flow.
- C12-07: safe auto-apply guardrails.
- C12-09: selected TC Webwright refresh regeneration flow.
- C12-10: TC retire recommendation and cleanup flow.
- D6-09/D6-10: disposition actions and diff review UI.
- E-11/E-12: E2E coverage for selected raw refresh and retire cleanup.
