# Data Model Spec

Last aligned: 2026-06-02

이 문서는 Local Worker의 SQLite/SQLModel 데이터 모델 계약을 정리한다. 모델은 `automation_key`를 중심으로 TC, raw run, mapping, structured flow, generated file, execution result를 연결한다.

Full relational DDL is specified in [DB_SCHEMA.md](./DB_SCHEMA.md). Raw-to-structured conversion is specified in [STRUCTURING_SPEC.md](./STRUCTURING_SPEC.md).
Artifact-backed self-healing is specified in [SELF_HEALING_SPEC.md](./SELF_HEALING_SPEC.md).

## Product Workspace Ownership

[PRODUCT_PILLARS.md](./PRODUCT_PILLARS.md) 기준 엔티티 소유 workspace:

| Workspace | Primary entities | Handoff object |
|-----------|------------------|----------------|
| **Generate Raw** | `TestCase`, `WebwrightRun`, `RawAction`, prompt payload (C2), import metadata | `TestCase` + latest `WebwrightRun` + `RawAction[]` |
| **Automation IDE** | `CaseActionMapping`, `StructuredFlow`, `StructuredStep`, `PageObject`, `PageObjectMethod`, `GeneratedFile`, `ExecutionRun`, `ExecutionResult`, `ExportLog`, `HealingProposal` | reviewed mappings, generated files, execution results |
| **Shared** | `SchemaVersion`, `Project`, settings (file), credentials (OS store) | schema baseline, `project_id`, app config |

Reverse handoff (Automation IDE → Generate Raw rerun) reuses `TestCase` and `WebwrightRun`; no separate handoff table at baseline.

## Storage Principles

- SQLite는 로컬 앱 데이터 저장소다.
- 프로젝트별 데이터는 `project_id`로 격리한다.
- raw Webwright output과 generated project 파일은 파일 시스템에 있고, DB에는 경로와 메타데이터를 저장한다.
- secrets는 DB 또는 settings JSON에 저장하지 않는다.

## Entity Relationship

```text
Project
  ├─ TestCase
  │   ├─ WebwrightRun
  │   │   ├─ RawAction
  │   │   └─ ArtifactAsset
  │   ├─ CaseActionMapping
  │   │   └─ CaseActionMappingAction
  │   └─ StructuredFlow
  │       └─ StructuredStep
  ├─ PageObject
  │   └─ PageObjectMethod
  │       └─ SelectorCandidate
  ├─ GeneratedFile
  │   └─ GeneratedFileOrigin
  └─ ExecutionRun
      ├─ ExecutionResult
      │   └─ HealingProposal
      └─ ExportLog
```

## SchemaVersion

Checklist: A2-12

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `id` | string | yes | Baseline marker key, currently `tc_studio` |
| `version` | int | yes | Current local schema baseline version |
| `description` | string | no | Human-readable baseline description |
| `applied_at` | datetime | yes | UTC timestamp first recorded |
| `updated_at` | datetime | yes | UTC timestamp last updated |

## Project

Checklist: A2-01

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `id` | string | yes | Primary key, e.g. `proj_...` |
| `name` | string | yes | User-visible project name |
| `root_path` | string | yes | Local project workspace |
| `generated_project_path` | string | no | Generated automation project output path |
| `default_env` | string | yes | Default runner environment, usually `stg` |
| `created_at` | datetime | yes | UTC timestamp |
| `updated_at` | datetime | yes | UTC timestamp |

## TestCase

Checklist: A2-02, C1-01

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `id` | string | yes | Primary key, e.g. `tc_...` |
| `project_id` | string | yes | Owning project |
| `source_type` | string | yes | `excel`, `testrail_clone`, `testrail`, `google_sheets` |
| `source_case_id` | string | yes | Case ID from original source |
| `source_location_json` | string | no | File/sheet/row/API origin |
| `title` | string | yes | TC title |
| `preconditions_json` | string | no | JSON encoded string array |
| `steps_json` | string | yes | JSON encoded `TestStep[]` |
| `expected_result` | string | no | Overall expected result |
| `automation_key` | string | yes | Stable automation link key |
| `tags_json` | string | no | JSON encoded string array |
| `priority` | string | no | Source priority |
| `start_url` | string | no | URL used by prompt/Webwright |
| `status` | string | yes | See TestCaseStatus |
| `created_at` | datetime | yes | UTC timestamp |
| `updated_at` | datetime | yes | UTC timestamp |

### TestCaseStatus

| Status | Meaning |
|--------|---------|
| `imported` | TC was imported and has no Webwright run yet |
| `webwright_pending` | Webwright run is queued |
| `webwright_running` | Webwright is running |
| `webwright_completed` | Raw Webwright output exists |
| `webwright_failed` | Webwright run failed |
| `needs_review` | Mapping needs user review |
| `mapped` | TC steps and actions are mapped |
| `structured` | Structured flow/code representation exists |
| `generated` | Generated project files exist |

## WebwrightRun

Checklist: A2-03, C4-02

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `id` | string | yes | Primary key |
| `project_id` | string | yes | Owning project |
| `test_case_id` | string | yes | Source TC |
| `automation_key` | string | yes | Copied from TC |
| `status` | string | yes | See WebwrightRunStatus |
| `output_path` | string | no | Run artifact folder |
| `final_script_path` | string | no | Webwright `final_script.py` |
| `trajectory_path` | string | no | Webwright trajectory JSON |
| `error_message` | string | no | Failure detail |
| `started_at` | datetime | no | UTC timestamp |
| `ended_at` | datetime | no | UTC timestamp |
| `created_at` | datetime | yes | UTC timestamp |

### WebwrightRunStatus

| Status | Meaning |
|--------|---------|
| `pending` | Queued |
| `running` | In progress |
| `completed` | Raw output collected |
| `failed` | Run failed |
| `cancelled` | User cancelled |
| `needs_review` | Output requires mapping review |
| `structured` | Structured flow generated |
| `generated` | Project files generated |

## RawAction

Checklist: A2-04, C5-04

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `id` | string | yes | Primary key |
| `webwright_run_id` | string | yes | Source run |
| `automation_key` | string | yes | Link key |
| `order_index` | int | yes | Action order |
| `type` | string | yes | Normalized action type |
| `target` | string | no | Human-readable target |
| `selector` | string | no | Playwright selector |
| `value` | string | no | Fill/text/value |
| `source_line` | int | no | Line in raw script |
| `confidence` | float | no | Extraction confidence |
| `metadata_json` | string | no | Selector/artifact/trajectory hints |

### Initial Action Types

The implementation should normalize at least these common Playwright concepts before expanding to the full action enum:

- `goto`
- `click`
- `fill`
- `press`
- `select_option`
- `check`
- `uncheck`
- `hover`
- `expect_visible`
- `expect_text`
- `wait`
- `screenshot`

## CaseActionMapping

Checklist: A2-05, C6

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `id` | string | yes | Primary key |
| `test_case_id` | string | yes | Source TC |
| `raw_action_id` | string | no | Linked raw action |
| `tc_step_index` | int | yes | Source TC step |
| `normalized_step_id` | string | no | Structured step identifier |
| `normalized_step_name` | string | no | User-visible step name |
| `pom_method_name` | string | no | Page Object method name |
| `status` | string | yes | `mapped`, `needs_review`, `ignored` |

### Mapping Cardinality

The current baseline stores one optional `raw_action_id` on each mapping row. The intended schema uses a join table, because one TC step often maps to multiple browser actions.

```text
CaseActionMapping
  └─ CaseActionMappingAction
      └─ RawAction
```

## StructuredFlow

Checklist: C7-01

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `id` | string | yes | Primary key |
| `project_id` | string | yes | Owning project |
| `test_case_id` | string | yes | Source TC |
| `automation_key` | string | yes | Link key |
| `name` | string | yes | Flow class/function name |
| `status` | string | yes | `draft`, `needs_review`, `approved`, `generated`, `stale` |
| `version` | int | yes | Increment when regenerated from mapping |
| `created_at` | datetime | yes | UTC timestamp |
| `updated_at` | datetime | yes | UTC timestamp |

## StructuredStep

Checklist: C7-01, C7-05

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `id` | string | yes | Primary key |
| `structured_flow_id` | string | yes | Parent flow |
| `mapping_id` | string | no | Source mapping |
| `order_index` | int | yes | Step order |
| `name` | string | yes | Normalized step name |
| `kind` | string | yes | `navigation`, `interaction`, `assertion`, `wait`, `helper`, `custom_code` |
| `page_object_method_id` | string | no | Planned POM method |
| `assertion_json` | string | no | Assertion metadata |
| `wait_json` | string | no | Wait metadata |
| `metadata_json` | string | no | Extra generator metadata |
| `created_at` | datetime | yes | UTC timestamp |
| `updated_at` | datetime | yes | UTC timestamp |

## PageObject

Checklist: C7-02

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `id` | string | yes | Primary key |
| `project_id` | string | yes | Owning project |
| `name` | string | yes | Page object class name |
| `file_path` | string | yes | Target generated file path |
| `url_pattern` | string | no | Optional page URL pattern |
| `description` | string | no | Human-readable page description |
| `created_at` | datetime | yes | UTC timestamp |
| `updated_at` | datetime | yes | UTC timestamp |

## PageObjectMethod

Checklist: C7-02, C7-05

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `id` | string | yes | Primary key |
| `page_object_id` | string | yes | Parent page object |
| `name` | string | yes | Method name |
| `method_type` | string | yes | `navigate`, `click`, `fill`, `assert`, `wait`, `composite`, `custom` |
| `selector` | string | no | Main selector when applicable |
| `value_template` | string | no | Parameterized value |
| `return_type` | string | no | Usually `None` for Python |
| `body_plan_json` | string | yes | Ordered action/assertion plan |
| `source_mapping_id` | string | no | Origin mapping |
| `status` | string | yes | `draft`, `approved`, `generated`, `stale` |
| `created_at` | datetime | yes | UTC timestamp |
| `updated_at` | datetime | yes | UTC timestamp |

## ArtifactAsset

Checklist: A2-13

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `id` | string | yes | Primary key |
| `project_id` | string | yes | Owning project |
| `automation_key` | string | no | Link key |
| `source_type` | string | yes | `webwright_run`, `raw_action`, `execution_result`, etc. |
| `source_id` | string | no | Source row ID |
| `artifact_type` | string | yes | `final_script`, `trajectory`, `screenshot`, `trace`, `log`, etc. |
| `file_path` | string | yes | Local file path |
| `content_hash` | string | no | Artifact hash |
| `metadata_json` | string | no | URL, viewport, error category, DOM hints |
| `created_at` | datetime | yes | UTC timestamp |

## SelectorCandidate

Checklist: A2-14

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `id` | string | yes | Primary key |
| `raw_action_id` | string | no | Source raw action |
| `page_object_method_id` | string | no | Related POM method |
| `selector_type` | string | yes | `role`, `text`, `test_id`, `css`, `xpath`, etc. |
| `selector_value` | string | yes | Candidate selector |
| `confidence` | float | yes | Candidate confidence |
| `source_artifact_id` | string | no | Evidence artifact |
| `metadata_json` | string | no | Extra evidence |
| `created_at` | datetime | yes | UTC timestamp |

## HealingProposal

Checklist: A2-15

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `id` | string | yes | Primary key |
| `project_id` | string | yes | Owning project |
| `automation_key` | string | yes | Link key |
| `execution_result_id` | string | no | Failure result that triggered proposal |
| `page_object_method_id` | string | no | Target method |
| `structured_step_id` | string | no | Target structured step |
| `kind` | string | yes | `selector_replace`, `wait_adjust`, `assertion_update`, etc. |
| `old_value` | string | no | Existing selector/value |
| `new_value` | string | yes | Proposed selector/value |
| `confidence` | float | yes | Proposal confidence |
| `status` | string | yes | `proposed`, `accepted`, `rejected`, `applied`, `superseded` |
| `evidence_json` | string | yes | Evidence artifact IDs and notes |
| `created_at` | datetime | yes | UTC timestamp |
| `updated_at` | datetime | yes | UTC timestamp |

## ExecutionRun

Checklist: A2-06, C9

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `id` | string | yes | Primary key |
| `project_id` | string | yes | Owning project |
| `run_id` | string | yes | Runner-side run identifier |
| `env` | string | yes | Environment key, e.g. `stg` |
| `browser` | string | yes | Browser key |
| `headed` | bool | yes | Headed/headless mode |
| `status` | string | yes | `pending`, `running`, `passed`, `failed`, `cancelled` |
| `result_path` | string | no | `results.json` path |
| `started_at` | datetime | no | UTC timestamp |
| `ended_at` | datetime | no | UTC timestamp |
| `created_at` | datetime | yes | UTC timestamp |

## ExecutionResult

Checklist: A2-06, C9-04

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `id` | string | yes | Primary key |
| `execution_run_id` | string | yes | Parent execution |
| `automation_key` | string | yes | Link key |
| `source_type` | string | no | Original TC source |
| `source_case_id` | string | no | Original TC case ID |
| `title` | string | no | Case title snapshot |
| `status` | string | yes | `passed`, `failed`, `skipped` |
| `duration_ms` | int | no | Runtime |
| `error` | string | no | Failure detail |
| `screenshot_path` | string | no | Artifact path |
| `trace_path` | string | no | Artifact path |

## GeneratedFile

Checklist: C8-02, C11

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `id` | string | yes | Primary key |
| `project_id` | string | yes | Owning project |
| `relative_path` | string | yes | Path under generated project root |
| `automation_key` | string | no | Linked TC when applicable |
| `source_type` | string | no | Origin class, e.g. `structured_flow` |
| `source_id` | string | no | Origin ID |
| `content_hash` | string | no | Last generated content hash |
| `status` | string | yes | `generated`, `edited`, `stale`, `conflict` |
| `created_at` | datetime | yes | UTC timestamp |
| `updated_at` | datetime | yes | UTC timestamp |

## GeneratedFileOrigin

Checklist: C8-02, C11-03

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `generated_file_id` | string | yes | Parent generated file |
| `origin_type` | string | yes | `test_case`, `raw_action`, `mapping`, `structured_flow`, `structured_step`, `page_object`, `page_object_method` |
| `origin_id` | string | yes | Origin row ID |

## ExportLog

Checklist: C10, D8-03

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `id` | string | yes | Primary key |
| `execution_run_id` | string | yes | Source execution |
| `target` | string | yes | `testrail_clone`, `testrail`, `excel`, `google_sheets` |
| `status` | string | yes | `previewed`, `exported`, `failed` |
| `message` | string | no | Summary/error |
| `created_at` | datetime | yes | UTC timestamp |

## Migration Rule

- During early Phase 0/1, `SQLModel.metadata.create_all` is acceptable for baseline local development.
- The A2-12 baseline records the current schema in `schema_versions`; broader production use still needs explicit migrations.
- Any field rename must include a data migration note in the PR.
