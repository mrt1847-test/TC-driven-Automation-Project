# Structuring Spec

Last aligned: 2026-05-31

이 문서는 Webwright가 만든 raw output을 유지보수 가능한 Playwright/pytest 프로젝트로 바꾸는 구조화 계약을 정의한다.

**Product workspace:** Automation IDE ([PRODUCT_PILLARS.md — Workspace 2](./PRODUCT_PILLARS.md#workspace-2-automation-ide---structure--edit--run)). Generate Raw는 raw input(`RawAction`, artifacts)만 제공한다.

## Conclusion

현재 구현처럼 `RawAction`과 `CaseActionMapping`만 DB에 저장한 뒤 바로 파일을 생성하는 방식은 MVP smoke에는 가능하다. 하지만 다음 기능을 지원하려면 구조화 결과도 관계형 DB에 저장해야 한다.

- mapping review 이후 구조화 결과를 다시 열어 검토
- POM method 이름, selector, assertion, wait를 GUI에서 안정적으로 편집
- regenerated file diff 최소화
- `automation_key` 기준 검색과 영향 범위 분석
- 한 TC의 flow가 여러 page object method를 참조하는 관계 추적
- 생성된 코드가 어떤 raw action과 TC step에서 왔는지 역추적
- Webwright/runner artifact를 구조화 이후 selector healing에 재사용

따라서 권장 구조는 다음과 같다.

```text
Webwright final_script.py / trajectory.json
  -> ArtifactAsset / SelectorCandidate
  -> RawAction
  -> CaseActionMapping
  -> StructuredFlow / StructuredStep
  -> PageObject / PageObjectMethod
  -> HealingProposal when execution fails
  -> GeneratedFile
  -> tests, flows, pages, fixtures
```

## Raw Inputs

| Input | Role | Stored in DB |
|-------|------|--------------|
| `final_script.py` | primary raw code source | path only |
| `trajectory.json` | optional browser-event enrichment | path only |
| screenshots/logs | review artifacts | path only |
| imported TC steps | human intent | normalized fields and JSON |

Raw files stay on disk. DB stores paths, extracted facts, selector candidates, mapping, structured metadata, and healing proposals.

## Step 1: Action Extraction

Source: `final_script.py`, optionally `trajectory.json`

Output: `RawAction`

Extraction should preserve:

- action order
- Playwright action type
- locator/selector expression
- value/text/input data
- source line
- artifact reference when available
- selector candidates when available
- confidence and parse warnings when extraction is uncertain

Example:

```json
{
  "type": "click",
  "selector": "page.get_by_role(\"button\", name=\"Login\")",
  "target": "Login button",
  "value": null,
  "source_line": 18,
  "order_index": 3
}
```

## Step 2: TC Mapping

Source: imported TC steps + `RawAction`

Output: `CaseActionMapping`

Mapping is a reviewable relation, not a one-time guess. One TC step can map to zero, one, or many raw actions.

Mapping statuses:

| Status | Meaning |
|--------|---------|
| `mapped` | user or auto-mapper accepts relation |
| `needs_review` | relation is uncertain |
| `unmapped` | TC step has no raw action |
| `ignored` | raw action should not generate code |

## Step 3: Normalized Flow

Source: reviewed `CaseActionMapping`

Output: `StructuredFlow`, `StructuredStep`

The normalized flow is the automation-level intent for one TC. It is still data, not Python code.

Example:

```json
{
  "automation_key": "user_login_001",
  "flow_name": "UserLogin001Flow",
  "steps": [
    {
      "order_index": 1,
      "name": "open_login_page",
      "kind": "navigation",
      "raw_action_ids": ["act_001"]
    },
    {
      "order_index": 2,
      "name": "submit_login",
      "kind": "interaction",
      "raw_action_ids": ["act_002", "act_003", "act_004"]
    }
  ]
}
```

## Step 4: Page Object Method Planning

Source: `StructuredStep` + selectors/actions

Output: `PageObject`, `PageObjectMethod`

Page object methods are reusable units. They should be deterministic and editable.

Method generation rules:

- navigation actions can become page-level methods such as `open()`.
- click/fill/check sequences become verb-based methods such as `submit_login`.
- assertions become `expect_*` methods or inline test assertions depending on reuse.
- hard waits should be flagged as review risks.
- selectors are stored as data before code generation.

Example method plan:

```json
{
  "page_name": "LoginPage",
  "method_name": "submit_login",
  "return_type": "None",
  "steps": [
    { "action": "fill", "selector": "page.get_by_label(\"Email\")", "value": "${email}" },
    { "action": "fill", "selector": "page.get_by_label(\"Password\")", "value": "${password}" },
    { "action": "click", "selector": "page.get_by_role(\"button\", name=\"Login\")" }
  ]
}
```

## Step 5: Code Generation

Source: structured DB entities

Output: generated files

Generated files are not source of truth for mapping. They are reproducible output from reviewed structure plus templates.

```text
StructuredFlow
  -> flows/{automation_key}_flow.py

PageObject / PageObjectMethod
  -> pages/{page_name}.py

TestCase + StructuredFlow
  -> tests/test_{automation_key}.py

TestCase + GeneratedFile
  -> mappings/cases.yaml
```

## Step 6: Artifact-Backed Self-Healing

Source: Webwright artifacts + generated project run artifacts + structured metadata

Output: healing proposal, structured metadata patch, regenerated file patch

Self-healing uses the same traceability chain as generation:

```text
ExecutionResult failure
  -> automation_key
  -> generated test / flow / page method
  -> PageObjectMethod selector plan
  -> StructuredStep
  -> CaseActionMapping
  -> RawAction
  -> Webwright screenshots/logs/trajectory
  -> SelectorCandidate
  -> HealingProposal
```

The generated Python file is not the first place to patch. The safer order is:

1. create healing proposal
2. update `PageObjectMethod` or `StructuredStep` metadata if accepted
3. regenerate or patch generated file
4. rerun selected/failed case

See [SELF_HEALING_SPEC.md](./SELF_HEALING_SPEC.md).

## Regeneration Rule

Regeneration should be deterministic:

- same mapping + same structured entities = same file output
- manual code edits in IDE should either be preserved through protected regions or marked as diverged
- generated file metadata should store content hash to detect drift

Recommended generated file statuses:

| Status | Meaning |
|--------|---------|
| `generated` | file matches generated metadata |
| `edited` | user edited file after generation |
| `stale` | source structure changed after file generation |
| `conflict` | regeneration cannot safely overwrite |

## What Goes In DB

Store:

- extracted actions
- mapping decisions
- normalized flow and step metadata
- page object and method metadata
- artifact paths and selector candidate metadata
- healing proposals and decisions
- generated file paths, hashes, and origin links

Do not store:

- full raw `final_script.py`
- full generated source code as primary data
- screenshots/traces as blobs
- API keys/secrets

## MVP Cut

For the first end-to-end MVP, it is acceptable to implement:

- `RawAction`
- `CaseActionMapping`
- `StructuredFlow`
- `StructuredStep`
- `PageObject`
- `PageObjectMethod`
- `ArtifactAsset`
- `SelectorCandidate`
- `HealingProposal`
- `GeneratedFile` with hash/status

This keeps the database small while making structure review and deterministic regeneration possible.
