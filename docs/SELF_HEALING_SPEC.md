# Self-Healing Spec

Last aligned: 2026-05-30

Webwright는 raw code뿐 아니라 logs, screenshots, trajectory, run metadata를 만든다. 이 산출물은 구조화 이후에도 버리지 않고 selector healing, failure diagnosis, regeneration hint에 활용한다.

## Goal

구조화된 자동화 프로젝트가 실패했을 때, 실패 원인을 raw artifact와 structured metadata에 연결해서 사용자가 빠르게 고치거나, 안전한 경우 자동 수정 제안을 적용할 수 있게 한다.

```text
Webwright raw artifacts
  -> RawAction artifact context
  -> StructuredStep / PageObjectMethod selector plan
  -> Execution failure artifact
  -> Healing proposal
  -> user accepts
  -> PageObjectMethod / generated file update
  -> rerun
```

## Artifact Sources

| Source | Examples | Usage |
|--------|----------|-------|
| Webwright generation | `final_script.py`, `trajectory.json`, screenshots, logs | original selector/action evidence |
| Mapping review | raw code, screenshot, log snippets | human validation context |
| Generated project run | pytest logs, Playwright trace, screenshots, videos | failure evidence |
| External TC source | TC steps, expected result, source metadata | intent validation |

## What To Store

Store paths and metadata, not large blobs.

- artifact type
- file path
- related `automation_key`
- related raw action / structured step / page object method / execution result
- timestamp
- hash
- metadata JSON for viewport, URL, DOM hints, or error category

## Selector Candidate Model

For each action that interacts with the page, capture multiple selector candidates where possible.

```json
{
  "raw_action_id": "act_123",
  "primary_selector": "page.get_by_role(\"button\", name=\"Login\")",
  "candidates": [
    { "type": "role", "value": "button[name=Login]", "confidence": 0.92 },
    { "type": "text", "value": "text=Login", "confidence": 0.72 },
    { "type": "css", "value": "button[type=submit]", "confidence": 0.64 }
  ]
}
```

These candidates can come from:

- Webwright-generated locator expressions
- trajectory/DOM metadata
- screenshot OCR or visual element hints when available
- user edits in Mapping & Review
- failed-run trace analysis

## Healing Proposal

A healing proposal is a reviewable patch, not an automatic silent rewrite.

```json
{
  "kind": "selector_replace",
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

## Healing Flow

1. Execution fails.
2. Worker parses error, trace, screenshot, and runner log.
3. Worker links failure to `automation_key`, test file, `StructuredStep`, and `PageObjectMethod`.
4. Worker compares failed selector with raw Webwright selector candidates and previous artifacts.
5. Worker creates one or more healing proposals.
6. Automation IDE shows proposal with evidence: before selector, after selector, screenshot/trace/log.
7. User accepts or rejects.
8. Accepted proposal updates structured metadata first.
9. Generated files are regenerated or patched.
10. User reruns current TC or failed cases.

## Safe-Healing Rules

Automatic apply is allowed only when all are true:

- failure is selector-not-found or strict-mode selector mismatch
- exactly one high-confidence candidate exists
- proposed selector points to same accessible role/text or same stable test id
- no manual edited/conflict file would be overwritten
- user has enabled auto-apply for this project

Otherwise, create a proposal and require user confirmation.

## UI Requirements

Self-healing belongs inside Automation IDE.

Recommended panels:

- Failure Diagnosis panel
- Screenshot / trace / log evidence tabs
- Selector candidates table
- Proposed patch diff
- Accept, reject, rerun buttons

## Non-Goals

- Do not silently rewrite generated code without traceability.
- Do not store screenshots or traces as DB blobs.
- Do not treat visual similarity alone as enough for auto-apply.
- Do not overwrite manually edited files without conflict handling.

