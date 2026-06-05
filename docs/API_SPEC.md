# API Spec

Last aligned: 2026-06-05

Base URL in development: `http://127.0.0.1:8765`

이 문서는 Local Worker(FastAPI)가 Electron GUI와 generated automation project를 연결하기 위해 제공하는 HTTP/WebSocket 계약을 정리한다. GUI 호출은 [PRODUCT_PILLARS.md](./PRODUCT_PILLARS.md)의 workspace별 surface와 대응한다.

런타임 경로·환경 변수 계약은 [RUNTIME_SPEC.md](./RUNTIME_SPEC.md)를 따른다.

## Principles

- API는 로컬 전용이다. 기본 바인딩은 `127.0.0.1`이다.
- GUI는 자동화 로직을 직접 수행하지 않고 Worker API를 호출한다.
- 모든 프로젝트 종속 리소스는 가능하면 `/projects/{project_id}/...` 아래에 둔다.
- 장기 작업은 즉시 `jobId`를 반환하고 로그는 `/ws/logs/{job_id}`로 스트리밍한다.
- `automation_key`는 TC, raw action, structured test, execution result를 잇는 핵심 키다.
- Python/Playwright/Webwright 경로는 `RuntimeProfile`로 통일한다 ([RUNTIME_SPEC.md](./RUNTIME_SPEC.md)).

## API By Product Workspace

| Workspace | API groups | Primary GUI surfaces |
|-----------|------------|----------------------|
| **Generate Raw** | Projects, Cases/Import, Webwright Runs, Prompt (C2), Settings/Health | Dashboard, Import, Cases, Prompt, Webwright, Artifacts |
| **Automation IDE** | Mapping, Structure, Generation, IDE files, Executions, Export, Healing | Mapping, Structure, IDE, Runner/Results/Export panels |
| **Supporting** | Settings, Health | Setup Wizard, Settings |

Handoff note: reverse handoff (Automation IDE → Generate Raw rerun) reuses **Webwright Runs** and **Cases** APIs with the same `project_id` and `case_id`; no separate handoff endpoint is required at baseline.

## Status Legend

| Status | Meaning |
|--------|---------|
| Implemented | 현재 코드에 라우트가 존재한다. |
| Partial | 라우트는 있으나 persistence, validation, cancel, integration depth가 제한적이다. |
| Planned | architecture/checklist에는 있으나 아직 라우트가 없다. |

## Common Shapes

### Error

FastAPI 기본 오류 형식을 따른다.

```json
{
  "detail": "Project not found"
}
```

Desktop clients should prefer `detail` when rendering API errors. If `detail`
is a Pydantic validation array, render each `loc` + `msg` pair as an actionable
message before falling back to status text.

### Async Job

```json
{
  "jobId": "ww_proj_123",
  "status": "queued"
}
```

## Health And Settings

| Method | Path | Status | Purpose | Checklist |
|--------|------|--------|---------|-----------|
| GET | `/health` | Implemented | RuntimeProfile 기반 Worker/Python/Webwright/Playwright 검증 | A3-05, I-07 |
| GET | `/settings` | Implemented | `settings.json` 로드 (`runtime` 포함) | A3-04 |
| PUT | `/settings` | Implemented | 앱 설정 저장 | A3-04 |
| POST | `/settings/validate` | Implemented | `/health`와 동일한 RuntimeProfile 검증 | A3-05, I-07 |
| POST | `/projects/{project_id}/health` | Implemented | generated project 경로 상태 점검 | I-01 |
| POST | `/projects/{project_id}/install-dependencies` | Implemented | generated project pip + chromium (`RuntimeProfile.python`) with C9-07 readiness cache | I-02, I-07, C9-07 |

### Health Response (extended)

```json
{
  "worker": { "ok": true, "message": "Worker running" },
  "settings": { "ok": true, "path": "..." },
  "runtimeMode": { "ok": true, "mode": "bundled" },
  "python": { "ok": true, "message": "Python 3.11.x" },
  "webwrightRoot": { "ok": true, "path": "..." },
  "webwrightPython": { "ok": true, "message": "Python 3.11.x" },
  "webwrightCli": { "ok": true, "message": "webwright.run.cli ready" },
  "webwrightConfig": { "ok": true, "baseConfig": "...", "modelConfig": "..." },
  "templatePath": { "ok": true, "path": "..." },
  "playwright": { "ok": true, "message": "..." },
  "playwrightBrowser": { "ok": true, "browser": "chromium", "message": "..." },
  "mockMode": { "ok": false, "enabled": false, "message": "live Webwright ready" },
  "allOk": true
}
```

Runtime readiness is defined by [RUNTIME_SPEC.md](./RUNTIME_SPEC.md). `webwrightRoot`
or `base.yaml` presence alone must not make `webwrightCli.ok` true; the Worker
must prove the configured Python can import or execute `webwright.run.cli`.

### AppSettings

```json
{
  "runtime": {
    "mode": "custom",
    "python": "",
    "webwrightRoot": "",
    "webwrightPython": "",
    "playwrightBrowsersPath": "",
    "templatePath": ""
  },
  "webwright": {
    "executionMode": "native",
    "root": "",
    "python": "",
    "baseConfig": "base.yaml",
    "modelConfig": "model_openai.yaml",
    "outputRoot": ""
  },
  "generator": {
    "projectRoot": "",
    "defaultFramework": "playwright-pytest",
    "defaultLanguage": "python",
    "templatePath": ""
  },
  "runner": {
    "defaultBrowser": "chromium",
    "defaultEnv": "stg",
    "headless": true
  },
  "self_healing": {
    "autoApplyProjectIds": []
  },
  "integrations": {
    "testrailClone": { "baseUrl": "http://localhost:3000", "enabled": false },
    "testrail": { "baseUrl": "", "enabled": false },
    "googleSheets": { "enabled": false }
  }
}
```

`bundled` 모드에서는 `runtime.*` 경로가 installer `resources/runtime`에서 시드된다. `custom` 모드에서는 Setup/Settings에서 사용자가 지정한다.

G-01 secret persistence rule: `GET /settings` and `PUT /settings` must never
return or persist plaintext secret fields. Secret-looking keys such as
`apiKey`, `token`, `password`, `credential`, and `secret` are stripped
recursively before `settings.json` is written or returned. Non-secret provider
and model config values remain persistable.

## Projects

| Method | Path | Status | Purpose | Checklist |
|--------|------|--------|---------|-----------|
| GET | `/projects` | Implemented | 프로젝트 목록 | A5-01 |
| POST | `/projects` | Implemented | 프로젝트 생성 | A5-01 |
| GET | `/projects/{project_id}` | Implemented | 프로젝트 상세 | A5-02 |
| PATCH | `/projects/{project_id}` | Implemented | 프로젝트 메타데이터 수정 | A5-02 |
| DELETE | `/projects/{project_id}` | Implemented | 프로젝트 삭제 | A5-02 |

### CreateProject Request

```json
{
  "name": "Search Ads Automation",
  "rootPath": "C:/work/search-ads",
  "defaultEnv": "stg"
}
```

## Cases And Import

| Method | Path | Status | Purpose | Checklist |
|--------|------|--------|---------|-----------|
| GET | `/projects/{project_id}/cases` | Implemented | TC 목록 | C1-07 |
| GET | `/projects/{project_id}/cases/{case_id}` | Implemented | TC 상세 | C1-07 |
| PATCH | `/projects/{project_id}/cases/{case_id}` | Implemented | start URL, status 등 | C1-07 |
| POST | `/projects/{project_id}/cases/import/excel/preview` | Implemented | Excel preview | C1-02 |
| POST | `/projects/{project_id}/cases/import/excel` | Implemented | Excel import | C1-03 |
| POST | `/projects/{project_id}/cases/import/testrail-clone/preview` | Implemented | testrail-clone preview | C1-04 |
| POST | `/projects/{project_id}/cases/import/testrail-clone` | Implemented | testrail-clone import | C1-04 |
| POST | `/projects/{project_id}/cases/import/testrail` | Partial | TestRail import | C1-05 |
| POST | `/projects/{project_id}/cases/import/google-sheets` | Partial | Google Sheets import | C1-06 |

## Webwright Runs

| Method | Path | Status | Purpose | Checklist |
|--------|------|--------|---------|-----------|
| POST | `/projects/{project_id}/webwright-runs` | Implemented | 선택 TC Webwright run (`has_webwright_cli` 없으면 mock) | C4-04 |
| GET | `/projects/{project_id}/webwright-runs` | Implemented | Webwright run 목록 | C4-04 |
| GET | `/projects/{project_id}/webwright-runs/{run_id}` | Implemented | Webwright run 상세 | C4-04 |
| POST | `/projects/{project_id}/webwright-runs/{run_id}/retry` | Implemented | 특정 run 재시도 | C4-04 |
| POST | `/projects/{project_id}/webwright-runs/{run_id}/cancel` | Partial | DB status만 `cancelled`. subprocess kill 미구현 | C4-04 |

Live run requires the full Webwright readiness probe from [RUNTIME_SPEC.md](./RUNTIME_SPEC.md), not just `RuntimeProfile.has_webwright_cli == true`. If mock mode is used, the API/logs must make that visible.

Completed Webwright runs index `final_script.py` into ordered `RawAction` rows.
C5-05 extraction parses the complete Python AST first so multi-line
Playwright calls, `await` expressions, chained locators, simple locator
aliases, `with`/`async with` contexts, and `expect(...).to_*` assertions keep
stable `order_index`,
`source_line`, selector, value, and action type metadata. If the script cannot
be parsed as a whole, the Worker falls back to the legacy line parser; supported
simple statements are still indexed and unsupported Playwright calls remain
reviewable as `custom_code`.

### WebwrightRunRequest

```json
{
  "caseIds": ["tc_123"],
  "mode": "sequential",
  "modelConfig": "model_openai.yaml",
  "presetId": "preset_builtin_login",
  "environment": "qa",
  "startUrlOverride": "https://example.test"
}
```

## Prompt Composer

| Method | Path | Status | Purpose | Checklist |
|--------|------|--------|---------|-----------|
| GET | `/projects/{project_id}/prompt-composer` | Implemented | Read project batch prompt and per-case overrides | C2-04 |
| PUT | `/projects/{project_id}/prompt-composer` | Implemented | Replace project batch prompt and per-case overrides | C2-04 |
| GET | `/projects/{project_id}/prompt-presets` | Implemented | Read built-in and project prompt presets | C2-05 |
| PUT | `/projects/{project_id}/prompt-presets` | Implemented | Replace project prompt presets; built-ins are immutable | C2-05 |
| POST | `/projects/{project_id}/prompt-preview` | Implemented | Preview effective prompt from case, optional preset, and saved prompt context without running Webwright | C2-06 |
| GET | `/projects/{project_id}/prompt-payloads?caseId=...&runId=...` | Implemented | List immutable Webwright prompt payload snapshots by project/case/run | C2-07 |
| GET | `/projects/{project_id}/prompt-payloads/{payload_id}` | Implemented | Read one immutable prompt payload snapshot | C2-07 |

C2-04 persists editable prompt composer state only. C2-05 persists reusable
prompt preset definitions separately. C2-06 previews the effective prompt
read-only from the selected case, optional preset, and saved prompt context.
C2-07 records immutable per-run prompt payload history when Webwright runs are
created.

### PromptComposerUpdateRequest

```json
{
  "batchPrompt": "Use the signed-in admin workspace and prefer stable labels.",
  "caseOverrides": {
    "tc_123": "Open the billing tab before asserting totals."
  }
}
```

### PromptComposerResponse

```json
{
  "projectId": "proj_123",
  "batchPrompt": "Use the signed-in admin workspace and prefer stable labels.",
  "caseOverrides": {
    "tc_123": "Open the billing tab before asserting totals."
  },
  "overrides": [
    {
      "caseId": "tc_123",
      "automationKey": "billing_totals",
      "promptOverride": "Open the billing tab before asserting totals.",
      "updatedAt": "2026-06-05T00:00:00"
    }
  ]
}
```

Effective Webwright prompts remain the original TC prompt when no composer data
exists. When saved context exists, the Worker appends the project batch prompt
and the selected case override in that order. Prompt preview can additionally
insert selected preset guidance before saved batch and case context.

### PromptPresetUpdateRequest

```json
{
  "presets": [
    {
      "id": "preset_project_checkout",
      "category": "checkout",
      "name": "Checkout flow",
      "guidance": "Use deterministic cart data and assert order totals."
    }
  ]
}
```

### PromptPresetResponse

```json
{
  "projectId": "proj_123",
  "presets": [
    {
      "id": "preset_builtin_login",
      "projectId": null,
      "category": "login",
      "name": "Login-required flow",
      "guidance": "Account for authentication setup and session reuse.",
      "isBuiltin": true,
      "createdAt": "2026-06-05T00:00:00",
      "updatedAt": "2026-06-05T00:00:00"
    },
    {
      "id": "preset_project_checkout",
      "projectId": "proj_123",
      "category": "checkout",
      "name": "Checkout flow",
      "guidance": "Use deterministic cart data and assert order totals.",
      "isBuiltin": false,
      "createdAt": "2026-06-05T00:00:00",
      "updatedAt": "2026-06-05T00:00:00"
    }
  ]
}
```

Built-in presets have stable IDs and are returned with project presets in
deterministic order. `PUT /prompt-presets` replaces only project-owned presets;
built-ins and presets owned by another project are rejected. C2-05 does not
apply preset guidance to Webwright runs.

### PromptPreviewRequest

```json
{
  "caseId": "tc_123",
  "presetId": "preset_builtin_login",
  "environment": "qa",
  "startUrlOverride": "https://example.test/login"
}
```

### PromptPreviewResponse

```json
{
  "projectId": "proj_123",
  "caseId": "tc_123",
  "automationKey": "login_required_flow",
  "environment": "qa",
  "startUrl": "https://example.test/login",
  "preset": {
    "id": "preset_builtin_login",
    "projectId": null,
    "category": "login",
    "name": "Login-required flow",
    "guidance": "Account for authentication setup and session reuse.",
    "isBuiltin": true
  },
  "parts": {
    "basePrompt": "Generate a Playwright automation script...",
    "presetGuidance": "Account for authentication setup and session reuse.",
    "batchPrompt": "Use the signed-in admin workspace.",
    "casePromptOverride": "Open the billing tab before asserting totals."
  },
  "prompt": "Generate a Playwright automation script..."
}
```

Prompt preview is read-only. It must not create a `WebwrightRun`, raw action,
or C2-07 prompt payload history row. The requested case must belong to the
project, and a selected preset must be built-in or project-owned.

### PromptPayloadResponse

`GET /projects/{project_id}/prompt-payloads` returns:

```json
{
  "projectId": "proj_123",
  "payloads": [
    {
      "id": "prompt_123",
      "projectId": "proj_123",
      "caseId": "tc_123",
      "webwrightRunId": "ww_123",
      "automationKey": "login_required_flow",
      "prompt": "Generate a Playwright automation script...",
      "parts": {
        "basePrompt": "Generate a Playwright automation script...",
        "presetGuidance": "Account for authentication setup and session reuse.",
        "batchPrompt": "Use the signed-in admin workspace.",
        "casePromptOverride": "Open the billing tab before asserting totals."
      },
      "preset": {
        "id": "preset_builtin_login",
        "category": "login",
        "name": "Login-required flow",
        "guidance": "Account for authentication setup and session reuse."
      },
      "environment": "qa",
      "startUrl": "https://example.test/login",
      "modelConfig": "model_openai.yaml",
      "createdAt": "2026-06-05T00:00:00"
    }
  ]
}
```

Prompt payload history is append-only from the API perspective. One row is
recorded per `WebwrightRun`, including no-context runs where preset, batch
prompt, and case override fields are empty.

## Mapping And Review

C6-03 adds project/case-scoped reviewed raw action CRUD:

| Method | Path | Status | Purpose | Checklist |
|--------|------|--------|---------|-----------|
| POST | `/projects/{project_id}/cases/{case_id}/actions` | Implemented | create reviewed raw action on the selected case's latest run | C6-03 |
| PATCH | `/projects/{project_id}/cases/{case_id}/actions/{action_id}` | Implemented | update reviewed raw action fields with project/case ownership validation | C6-03 |
| DELETE | `/projects/{project_id}/cases/{case_id}/actions/{action_id}` | Implemented | delete selected-case raw action and repair mapping joins/legacy first action | C6-03 |

Action CRUD is scoped by both `project_id` and `case_id`. An action mutation is
accepted only when the target action belongs to a Webwright run owned by the
selected case. Foreign action IDs and ambiguous cross-case references are
rejected before any mutation.

`POST /actions` appends to the selected case's latest Webwright run unless an
explicit positive `order_index` is supplied:

```json
{
  "type": "fill",
  "selector": "page.get_by_label('Email')",
  "value": "${env.user.email}",
  "target": "reviewed email field"
}
```

`PATCH /actions/{action_id}` accepts partial updates for `type`, `target`,
`selector`, `value`, `source_line`, and `order_index`. `DELETE` removes the
action, removes any selected-case ordered mapping links to it, and keeps
`case_action_mappings.raw_action_id` aligned to the first remaining ordered
action or `null`. Mappings that lose all actions become `unmapped`, and the
case returns to `needs_review`.

C6-04 adds step-scoped reviewed assertion/wait insertion:

| Method | Path | Status | Purpose | Checklist |
|--------|------|--------|---------|-----------|
| POST | `/projects/{project_id}/cases/{case_id}/steps/{tc_step_index}/actions` | Implemented | insert reviewed assertion/wait action into one TC step mapping | C6-04 |
| PATCH | `/projects/{project_id}/cases/{case_id}/steps/{tc_step_index}/actions/{action_id}` | Implemented | update an assertion/wait action already linked to that TC step | C6-04 |

The step-scoped endpoint accepts only supported assertion/wait action types:
`assert_text`, `assert_url`, `assert_visible`, `assert_hidden`,
`assert_count`, `wait`, `wait_for_request`, and `wait_for_response`.
`insertAfterActionId` may be supplied to place the new action after an existing
action in the same TC step; otherwise the action is appended. The mutation
creates the raw action on the selected case's latest Webwright run, updates the
`case_action_mapping_actions` order atomically, and keeps `raw_action_id`
aligned to the first action. Foreign actions, unsupported types, and actions
not linked to the selected step are rejected before writes.

Mapping Review GUI must surface Mapping API validation failures from
`PUT /mappings`, `POST /normalize`, reviewed action CRUD, and step-scoped
assertion/wait mutations without clearing the selected TC or local mapping
draft. The visible message should preserve the Worker `detail` value for
duplicate step/action IDs, foreign action IDs, unsupported assertion/wait
types, missing Webwright runs, and unmapped/review-required states.

```json
{
  "type": "assert_visible",
  "selector": "page.get_by_text('Profile saved')",
  "value": "Profile saved",
  "insertAfterActionId": "act_123"
}
```

| Method | Path | Status | Purpose | Checklist |
|--------|------|--------|---------|-----------|
| GET | `/projects/{project_id}/cases/{case_id}/actions` | Implemented | 최신 Webwright run의 raw action 조회 | C6-06 |
| GET | `/projects/{project_id}/cases/{case_id}/mappings` | Implemented | TC step to action mapping 조회 | C6-06 |
| PUT | `/projects/{project_id}/cases/{case_id}/mappings` | Implemented | mapping과 action 수정 저장 | C6-06 |
| POST | `/projects/{project_id}/cases/{case_id}/normalize` | Implemented | 자동 1:1 mapping 재생성 | C6-01, C6-06 |

## Structuring

| Method | Path | Status | Purpose | Checklist |
|--------|------|--------|---------|-----------|
| POST | `/projects/{project_id}/cases/{case_id}/structure/sync` | Implemented | mapping → StructuredFlow/Step/PageObjectMethod DB persist | C7-06..C7-08 |
| GET | `/projects/{project_id}/cases/{case_id}/structure/validate` | Implemented | structure issues list | C7-09 |

### Structure validate response

```json
{
  "ok": false,
  "issues": ["mapping_needs_review:step_2", "step_count_mismatch"],
  "flowId": "sf_abc123"
}
```

## Project Generation And IDE

| Method | Path | Status | Purpose | Checklist |
|--------|------|--------|---------|-----------|
| POST | `/projects/{project_id}/generate` | Implemented | DB structured entities → generated project; returns `runtimeBootstrap` | C8-03, C8-05 |
| POST | `/projects/{project_id}/generate/selected` | Implemented | selected TC incremental regeneration; preserve unrelated generated cases | C8-09 |
| POST | `/projects/{project_id}/cases/{case_id}/retire` | Implemented | human-confirmed TC retire/delete generated artifact cleanup foundation | C8-10 |
| GET | `/projects/{project_id}/generated-files` | Implemented | generated project 파일 트리 | C11-01 |
| GET | `/projects/{project_id}/generated-files/content?path=...` | Implemented | 파일 내용 읽기 | C11-02 |
| PUT | `/projects/{project_id}/generated-files/content` | Implemented | 파일 내용 저장 | C11-02 |
| POST | `/projects/{project_id}/generated-files/create` | Implemented | 파일 생성 | C11-02 |
| DELETE | `/projects/{project_id}/generated-files?path=...` | Implemented | 파일 삭제 | C11-02 |
| POST | `/projects/{project_id}/generated-files/rename` | Implemented | 파일 이름 변경 | C11-02 |
| GET | `/projects/{project_id}/search?q=...` | Implemented | generated project 검색 | C11-03 |

### Generate response

```json
{
  "generatedProjectPath": "C:/work/project/generated",
  "runtimeBootstrap": {
    "ok": true,
    "message": "Generated runtime is ready (cached)",
    "pip": "...",
    "pipError": "",
    "playwright": "...",
    "playwrightBrowser": { "ok": true, "browser": "chromium" },
    "cache": {
      "status": "hit",
      "message": "Using cached generated runtime readiness",
      "staleFields": [],
      "stateId": "rti_123"
    }
  },
  "generationMode": "incremental",
  "selectedCaseIds": ["tc_123"],
  "affectedFiles": [
    "flows/user_login_001_flow.py",
    "mappings/cases.yaml",
    "pages/generated_page.py",
    "tests/test_user_login_001.py"
  ],
  "changedFiles": ["mappings/cases.yaml", "pages/generated_page.py"],
  "preservedFiles": ["artifacts/runs/run_001/results.json", "tests/test_other_case.py"],
  "editedFiles": [],
  "staleFiles": ["pages/generated_page.py"],
  "conflictFiles": []
}
```

Generation pipeline: `sync_structured_entities` → codegen from DB → `GeneratedFile` with `content_hash`, `source_type=structured_flow` ([STRUCTURING_SPEC.md](./STRUCTURING_SPEC.md)).

Generated output is Git-ready: the Worker writes deterministic `.gitignore`
rules, keeps `artifacts/runs/.gitkeep`, skips stale template caches/artifacts,
and preserves existing `.git`, `.gitattributes`, and `.gitmodules` metadata
during full or selected generation.

Generation also writes `config/runtime-manifest.json`. The manifest is
deterministic, tracked through generated-file metadata, guarded against
user-edited overwrites, and records generated `requirements.txt`, fixture
policy, Playwright browser/cache expectations, supported standalone/Studio
commands, and RuntimeProfile-derived defaults. Selected generation updates it
only when runtime or template inputs change.

`runtimeBootstrap.cache` reports C9-07 runtime install-state behavior:

- `miss`: no project/runtime readiness row exists, so bootstrap runs normally;
- `stored`: bootstrap succeeded and a readiness row was stored;
- `hit`: matching readiness exists, so pip/Playwright install commands were
  skipped after browser executable verification;
- `stale`: requirements, runtime manifest, generated project hash,
  RuntimeProfile, browser, browser cache, or generated project path changed, so
  bootstrap runs again;
- `disabled`: no project/session context was supplied, so no cache is used.

Failed pip installs, Playwright installs, and browser verification failures are
returned through the existing fail-fast shape and are not cached as ready.

Selected generation contract: when a request targets only selected `caseIds`,
the API must not wipe and recreate the whole generated project. It must run the
selected TC incremental regeneration flow from
[STRUCTURING_SPEC.md](./STRUCTURING_SPEC.md), merge `mappings/cases.yaml`,
return affected files, and preserve unrelated generated cases. Full
regeneration must be explicit.

`POST /generate` with `caseIds` and `POST /generate/selected` both run
incrementally. `mode=full` on `POST /generate` explicitly rebuilds the whole
generated project. Empty `caseIds`, incremental requests without selected
cases, and `mode=full` on `/generate/selected` are rejected instead of falling
back to a destructive full regeneration. Incremental generation returns:

- `affectedFiles`: selected and shared files rewritten by the request;
- `changedFiles`: affected files whose content changed or was created;
- `preservedFiles`: pre-existing files not rewritten by the request;
- `editedFiles`, `staleFiles`, and `conflictFiles`: C7-10 generated-file
  status preflight results. Source-changed edited files return a validation
  error before generated files are overwritten.

Selected cases in `needs_review` stop with HTTP 400 before generated files are
rewritten. Edited or conflicting generated files stop with HTTP 409 before any
rewrite or delete. The response `detail` contains `message`, `affectedFiles`,
`preservedFiles`, `editedFiles`, `staleFiles`, and `conflictFiles`.

### Generate Request

```json
{
  "caseIds": ["tc_123"]
}
```

Explicit full regeneration:

```json
{
  "mode": "full"
}
```

### Retire/Delete Cleanup

`POST /projects/{project_id}/cases/{case_id}/retire` requires explicit human
confirmation. Both actions are soft terminal states so TestCase, raw,
structured, execution, and artifact history remain queryable.

```json
{
  "confirmed": true,
  "action": "retire",
  "reason": "human confirmed obsolete product area"
}
```

Safe cleanup removes selected private test/flow files, marks their
`GeneratedFile` metadata `obsolete`, removes the selected mapping entry, and
rebuilds shared page/mapping files from remaining active cases. The response
returns deterministic `affectedFiles`, `removedFiles`, `updatedFiles`,
`obsoleteFiles`, `preservedSharedFiles`, `preservedFiles`, and `conflictFiles`.

If an impacted file is edited, hash-mismatched, or shared in a way cleanup
cannot prove safe, the API returns `status=conflict`, marks provable impacted
metadata as `conflict`, and leaves the TC state and generated files unchanged.
`confirmed=false` is rejected. Failure-disposition maintenance should use the
diagnosis-bound execution-result endpoint below.

## Executions

| Method | Path | Status | Purpose | Checklist |
|--------|------|--------|---------|-----------|
| POST | `/projects/{project_id}/executions` | Implemented | `runner.cli` via `RuntimeProfile.python`; auto bootstrap | C9-05 |
| GET | `/projects/{project_id}/executions` | Implemented | execution run 목록 | C9-05 |
| GET | `/projects/{project_id}/executions/{execution_id}` | Implemented | run + results | C9-04 |
| POST | `/projects/{project_id}/executions/{execution_id}/rerun-failed` | Implemented | failed cases rerun | C9-05 |
| POST | `/projects/{project_id}/executions/{execution_id}/results/{result_id}/retire` | Implemented | human-confirmed `feature_removed_retire_tc` action bound to the resolved selected TC | C12-10, C8-10 |
| POST | `/projects/{project_id}/executions/{execution_id}/cancel` | Partial | status cancel only | C9-05 |
| POST | `/projects/{project_id}/executions/{execution_id}/export/{target}` | Implemented | result export | C10-06 |

Subprocess env includes `TC_HEADLESS`, `PLAYWRIGHT_BROWSERS_PATH` when configured.

Before runner execution, dependency bootstrap is fail-fast (C9-06). If
`requirements.txt`, pip install, Playwright install, or browser verification
fails, the API records an execution failure with bootstrap logs/results instead
of launching `runner.cli`.

C9-07 adds per-project runtime install-state reuse before `runner.cli`: cache
hits skip redundant pip/Playwright install commands, while stale or missing
cache entries fall back to the same fail-fast bootstrap path.

### Export Preview And Validation

`POST /projects/{project_id}/executions/{execution_id}/export/{target}` accepts
`{"preview": true}` for testrail-clone, TestRail, Excel, and Google Sheets.
Preview responses keep the target-specific shape (`payload` for
testrail-clone, `updates` for the other targets) and include:

```json
{
  "validation": {
    "ok": true,
    "checked": 1,
    "issues": []
  }
}
```

Preview mode must not call external targets, write source files, create Excel
backups, or insert `ExportLog` rows.

Before non-preview export, the Worker compares each `results.json` row with the
persisted `ExecutionResult` row and generated `mappings/cases.yaml` row by
`automationKey`, `sourceType`, and `sourceCaseId`. Missing rows, duplicate
automation keys, or mismatched source metadata return HTTP 400 before any
target mutation. Excel target file I/O failures after validation remain visible
as target-specific failed entries, preserving the existing non-corrupting
write-back behavior.

## Artifacts And Self-Healing

| Method | Path | Status | Purpose | Checklist |
|--------|------|--------|---------|-----------|
| GET | `/projects/{project_id}/artifacts?automation_key=...` | Planned | Webwright/execution artifacts 조회 | C12-01, C12-03 |
| GET | `/projects/{project_id}/cases/{case_id}/selector-candidates` | Planned | raw action/POM selector candidates 조회 | C12-02 |
| POST | `/projects/{project_id}/executions/{execution_id}/diagnose` | Implemented | failed cases를 disposition으로 분류하고 evidence/confidence 반환 | C12-08 |
| POST | `/projects/{project_id}/executions/{execution_id}/healing-proposals` | Implemented | failed execution result -> selector healing proposal generation; project-enabled safe auto-apply | C12-05, C12-07 |
| GET | `/projects/{project_id}/healing-proposals?automation_key=...` | Implemented | proposal list by project/key | C12-05 |
| GET | `/projects/{project_id}/healing-proposals/{proposal_id}` | Implemented | proposal detail with evidence JSON | C12-05 |
| POST | `/projects/{project_id}/healing-proposals/{proposal_id}/accept` | Implemented | proposal 수락 및 evidence 보존 | C12-06 |
| POST | `/projects/{project_id}/healing-proposals/{proposal_id}/reject` | Implemented | proposal 거절, mutation 없음 | C12-06 |
| POST | `/projects/{project_id}/healing-proposals/{proposal_id}/apply` | Implemented | 수락된 selector proposal 적용, guarded selected regeneration, rerun context 반환 | C12-06 |
| POST | `/projects/{project_id}/cases/{case_id}/refresh-webwright-and-regenerate` | Implemented | selected already-structured TC Webwright refresh -> raw merge into existing structure -> incremental regeneration | C12-09, C7-12, C8-09 |

### Execution Diagnosis

`POST /projects/{project_id}/executions/{execution_id}/diagnose` is read-only.
It returns one diagnosis for each failed execution result and omits passed
results. It does not create or apply healing proposals.

```json
{
  "project_id": "proj_123",
  "execution_id": "exec_123",
  "diagnoses": [
    {
      "execution_result_id": "result_123",
      "automation_key": "user_login_001",
      "disposition": "selector_changed",
      "reason": "linked_selector_failure_evidence",
      "confidence": 0.9,
      "evidence_artifact_ids": ["art_001", "art_009"],
      "selector_candidate_ids": ["sel_001"],
      "target": {
        "status": "resolved",
        "structured_step_id": "step_123",
        "page_object_method_id": "pom_123"
      }
    }
  ]
}
```

Unresolved target links, mixed failure signals, and selector failures without
linked selector context return `unknown`.

### Diagnosis-Bound Retire/Delete

`POST /projects/{project_id}/executions/{execution_id}/results/{result_id}/retire`
requires a selected `caseId` and explicit confirmation.

```json
{
  "caseId": "tc_123",
  "confirmed": true,
  "action": "retire"
}
```

Before invoking C8-10 cleanup, the API reclassifies the failed result and
requires a resolved `feature_removed_retire_tc` diagnosis whose project,
execution, automation key, source case context, and sole target TC all match
the request. Unconfirmed, unresolved, non-feature-removed, or mismatched
requests return HTTP 400 without changing TC state or generated files.

The response includes the full diagnosis reason, confidence, evidence IDs, and
resolved target alongside the deterministic cleanup summary. Cleanup conflicts
remain visible as `status=conflict` with the diagnosis context preserved.

### Selected Raw Refresh Regeneration

`POST /projects/{project_id}/cases/{case_id}/refresh-webwright-and-regenerate`
requires an existing structured flow and reruns Webwright only for the selected
case. It preserves prior runs and raw actions, extracts the new run, merges it
into the existing reviewed structure, and calls selected incremental generation
only when the merge status is `merged`.

The response always includes `status`, `jobId`, `projectId`, `caseId`,
`automationKey`, `previousRunIds`, and a `run` result that identifies live or
mock mode. Safe merges also include `merge` and
`generation` summaries with selected, affected, changed, and preserved files.
Ambiguous or conflicting merges return `status=needs_review` and
`generation=null` without rewriting generated files. Failed Webwright runs
return `status=run_failed`. Expected incremental-generation validation failures
return `status=generation_failed` while preserving the run and merge context.

### HealingProposal

C12-05 creates proposals only. It does not mutate structured metadata,
regenerate files, or rerun tests. The create endpoint accepts an
`executionResultId`, reuses execution diagnosis, and creates a
`selector_replace` proposal only for resolved `selector_changed` failures with
linked selector candidates. Non-selector or unresolved diagnoses return
`status=not_applicable` and do not create rows. Repeated matching calls return
the existing proposal.

```json
{
  "executionResultId": "result_123"
}
```

```json
{
  "id": "heal_123",
  "automation_key": "user_login_001",
  "kind": "selector_replace",
  "old_value": "page.locator(\"#login\")",
  "new_value": "page.get_by_role(\"button\", name=\"Login\")",
  "confidence": 0.88,
  "status": "proposed",
  "evidence": [
    { "artifact_id": "art_001", "type": "screenshot" },
    { "artifact_id": "art_009", "type": "trace" }
  ]
}
```

C12-06 adds review and apply endpoints. `accept` and `reject` update only the
proposal status and preserve evidence. `apply` requires an accepted
`selector_replace` proposal, patches the targeted `PageObjectMethod` selector
and body plan, then invokes selected incremental generation through the
generated-file guard. Edited/conflict generated files return `409` with
affected/conflict file summaries before persisted selector mutation or file
rewrite. Successful apply returns proposal, mutation, generation, and rerun
next-step context; repeated apply returns the already-applied proposal without a
second mutation.

C12-07 adds guarded auto-apply to the create endpoint. Auto-apply is disabled by
default and is enabled only when `settings.self_healing.autoApplyProjectIds`
contains the project ID. Enabled auto-apply creates the same proposal row first,
then requires selector-not-found or strict-mode evidence, exactly one
high-confidence role/text/test-id candidate, compatible selector semantics where
available, a non-stale POM/step target, and clean generated-file guard results.
Eligible proposals reuse `accept` + `apply` and return `status=auto_applied`.
Unsafe cases return `status=blocked` with `autoApply.reason` and leave the
proposal reviewable without selector/body-plan or generated-file content
mutation.

## WebSocket

| Path | Status | Purpose |
|------|--------|---------|
| `/ws/logs/{job_id}` | Implemented | Webwright run, execution run stdout/stderr stream |

## Planned API Follow-ups

| Area | Item |
|------|------|
| Webwright | subprocess cancel for in-flight CLI |
| Structuring | stale/conflict API beyond validate issues list |
