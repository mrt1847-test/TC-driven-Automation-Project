# Self-Healing And Failure Disposition Spec

Last aligned: 2026-06-13

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
SelectorCandidate rows already bound to a PageObjectMethod as failure/healing
evidence must remain proposal evidence until accepted; structuring-time selector
ranking may use extraction-time RawAction candidates, but it must not silently
apply post-failure healing-only candidates.

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

C12-05 implementation behavior:

- `POST /executions/{execution_id}/healing-proposals` creates
  `selector_replace` proposals only after reusing the resolved
  `selector_changed` diagnosis for the requested failed result;
- proposals persist target execution result, POM method, structured step, old
  selector, proposed selector, confidence, and evidence JSON;
- non-selector, unresolved, or ambiguous diagnoses return a non-applicable
  outcome without mutating structured data, regenerated files, or runner state;
- repeated matching requests return the existing proposal instead of creating
  confusing duplicates;
- project/key proposal list and detail endpoints expose review state for the
  apply flow.

C12-06 implementation behavior:

- accept/reject endpoints make proposal decisions idempotent where safe and
  preserve the original evidence payload;
- rejected proposals never mutate structured selectors or generated files;
- applying an accepted `selector_replace` proposal updates the targeted
  `PageObjectMethod` selector/body plan and marks the proposal `applied`;
- apply uses selected incremental regeneration and the generated-file guard, so
  edited/conflict files return a conflict summary before selector mutation or
  file rewrite is persisted;
- successful apply returns traceable proposal, mutation, generation, and rerun
  next-step context.

C12-07 implementation behavior:

- auto-apply is disabled by default and is enabled only when
  `settings.self_healing.autoApplyProjectIds` contains the project ID;
- enabled auto-apply still creates a normal `selector_replace` proposal first,
  then requires selector-not-found or strict-mode evidence, exactly one
  candidate at or above the high-confidence threshold, supported
  role/text/test-id semantics, and a current non-stale POM/step target;
- eligible proposals reuse the C12-06 accept/apply path, so successful
  auto-apply preserves the proposal status trail, audit evidence, guarded
  selected regeneration, and rerun context;
- low-confidence, ambiguous, stale, unsafe evidence, semantic mismatch, edited
  file, or generation-conflict cases return a concrete `blocked` reason and do
  not persist selector/body-plan changes or rewrite generated files.

## Extended Proposal Kinds

C12-13 extends the same reviewable proposal table and decision flow beyond
selector replacement. The create endpoint may receive an explicit `kind` and
structured `proposal` payload for `wait_adjust`, `assertion_update`, or
`pom_method_patch`; it may also infer wait/assertion proposals from a resolved
failure target and error evidence when no selector proposal applies. Artifact
metadata may provide a `healing_proposal`, `healingProposal`, or `proposal`
object with one of those kinds.

Extended proposal values are stored in `old_value` and `new_value` as compact
JSON patch payloads, while `evidence_json` stores the proposal kind, diagnosis
reason/disposition, target POM/step IDs, diagnosis artifact IDs, and source
artifact hint when available. Duplicate requests for the same result, target,
kind, old value, and new value return the existing row.

Supported apply behavior:

- `wait_adjust` patches the targeted wait body-plan entry with `timeoutMs`,
  mirrors the timeout into `StructuredStep.wait_json`, and regenerates the
  selected case so generated Playwright waits include `timeout=...`;
- `assertion_update` patches the targeted assertion body-plan value, mirrors it
  into `StructuredStep.assertion_json`, and regenerates selected files;
- `pom_method_patch` accepts a bounded body-plan/method patch payload, validates
  supported generated actions, updates the targeted `PageObjectMethod`, and
  regenerates selected files.

All extended kinds reuse accept/reject status transitions, require `accepted`
before apply, preserve `selector_replace` compatibility, and use the same
selected incremental regeneration and generated-file conflict rollback path.
Auto-apply remains selector-only; extended proposal kinds require review.

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
- return traceable run, merge, and generation outcomes; review-required
  outcomes must return without invoking generation;
- do not delete unrelated generated tests, flows, pages, or mappings;
- mark generated files as `stale` or `conflict` when origin/hash checks cannot
  safely apply the update;
- show the affected-file list before applying changes.

## TC Retire/Delete

Use this path when the failure disposition is `feature_removed_retire_tc`.

The system may recommend retire/delete, but the human must confirm it. The UI
must explain why the TC appears obsolete, using execution failure evidence and
source TC context.

The disposition action must be tied to a specific failed execution result. It
must reclassify that result and verify a resolved `feature_removed_retire_tc`
target whose project, execution, automation key, source context, and sole
target TC match the human-selected case. Unconfirmed, unresolved,
non-feature-removed, or mismatched requests must stop without cleanup.

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

D6-09 implementation behavior:

- Automation IDE diagnosis calls the Worker execution diagnosis API and renders
  disposition, confidence, reason, target status, evidence IDs, selector
  candidate IDs, screenshot, and trace context per failed result;
- `selector_changed` actions create selector healing proposals, then accept,
  reject, or accept-and-apply through the existing proposal APIs;
- `raw_refresh_required` actions call selected TC Webwright refresh and
  regeneration for the resolved case only;
- `feature_removed_retire_tc` actions require an explicit UI confirmation
  before invoking the diagnosis-bound retire/delete endpoint;
- `unknown` provides evidence review and Mapping Review navigation only, with
  no mutation action.

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
- C12-11 artifact read API returns project-scoped Webwright/execution evidence
  rows with automation-key, source/run filters, metadata, and safe path
  suppression for paths outside known artifact roots.
- C12-12 selector-candidates read API returns project-scoped persisted
  raw-action and PageObjectMethod selector candidates for the selected case,
  including source artifact metadata links and grouped review context.
- C12-04 failure-to-structured target resolver returns linked target/evidence
  IDs with deterministic resolved, missing, or ambiguous status.
- C12-08 failure disposition classifier and execution diagnosis API return one
  evidence-backed disposition per failed result, with conservative `unknown`
  fallback for unresolved, mixed, or unsupported evidence.
- C7-12 selected raw refresh merge preserves reviewed structured identities and
  intent for safely matched reruns, updates raw links/body plans in place, and
  routes ambiguous or shared-method changes to review before regeneration.
- C12-09 selected raw refresh regeneration API preserves prior raw evidence,
  returns traceable run/merge/generation outcomes, incrementally regenerates
  only after safe merges, and stops before generation on review-required
  changes.
- C8-10 human-confirmed cleanup foundation preserves audit history and shared
  generated content while removing only provably selected files and stopping
  on edited or unproven shared conflicts.
- C12-10 diagnosis-bound retire/delete validates the failed result disposition
  and selected TC identity before invoking C8-10, rejects unsafe requests
  without mutation, and returns diagnosis evidence with the cleanup summary.
- C12-05 healing proposal generation persists evidence-backed
  `selector_replace` proposals for resolved selector failures and remains
  proposal-only for non-selector or unresolved diagnoses.
- C12-06 accepted proposal apply accepts or rejects review decisions, applies
  accepted selector replacements through guarded selected regeneration, blocks
  edited/conflict generated files before mutation, and returns rerun context.
- C12-07 safe auto-apply guardrails keep proposal creation review-only by
  default and allow project-enabled selector auto-apply only under conservative
  evidence, confidence, semantic, stale-target, and generation-conflict checks.
- C12-13 extended proposal kinds persist and apply reviewed `wait_adjust`,
  `assertion_update`, and `pom_method_patch` proposals with JSON patch payloads,
  evidence metadata, guarded selected regeneration, stale-target checks, and
  selector proposal compatibility.
- C7-16 structuring-time selector ranking uses extraction-time RawAction
  candidates for body-plan selectors while preserving PageObjectMethod-bound
  failure/healing candidates as proposal evidence until accepted.
- baseline GUI diagnosis panel exists.
- D6-09 Automation IDE disposition actions are wired to existing diagnosis,
  healing proposal, selected raw refresh/regeneration, and diagnosis-bound
  retire/delete APIs without adding Worker endpoints; unknown failures stay
  manual-only.
- D6-10 maintenance impact review requires preview before apply for selected
  raw refresh/regeneration and diagnosis-bound retire/delete; Worker preview
  endpoints return affected, preserved, changed/removed, conflict, and
  unaffected-case summaries without mutation.

- E-11 selected raw refresh incremental regeneration E2E covers preview plus
  selected refresh/regenerate with safe merge and unrelated-case preservation.
- E-12 feature-removed TC retire cleanup E2E covers diagnosis,
  preview-without-mutation, confirmed retire, and unrelated-case preservation.
