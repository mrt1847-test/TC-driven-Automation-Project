# API Spec

Last aligned: 2026-06-13

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

## Local Worker Trust Boundary

The localhost Worker is not a browser-public API. G-06 requires a per-session
trust boundary for privileged HTTP and WebSocket calls:

- CORS must not use wildcard origins. The Worker allows only configured Electron
  renderer/dev origins from `TC_STUDIO_ALLOWED_ORIGINS`, or the built-in local
  defaults: `http://127.0.0.1:5173`, `http://localhost:5173`,
  `http://127.0.0.1:8765`, `http://localhost:8765`, `file://`, and `null`.
- `POST`, `PUT`, `PATCH`, and `DELETE` requests must include
  `X-TC-Studio-Worker-Token` matching `TC_STUDIO_WORKER_TOKEN`. Missing or
  invalid tokens return `401` before route body side effects. Disallowed
  `Origin` values return `403` before route body side effects.
- Intentionally read-only endpoints such as `GET /health`, `GET /settings`,
  status reads, and generated-file reads remain usable without the token unless
  a future spec explicitly tightens them.
- Electron main generates an unguessable token for each app session, passes it
  to the Worker environment, and exposes it through preload only for the API
  client to attach. Direct CLI/test flows set `TC_STUDIO_WORKER_TOKEN`
  explicitly.

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
| GET | `/settings/connector-credentials` | Implemented | TestRail/Google Sheets secure credential account metadata; no plaintext secrets | G-04 |
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

G-04 connector credential rule: connector settings may persist non-secret
configuration such as TestRail `baseUrl`/`username` and Google Sheets
`spreadsheetId`/`serviceAccountEmail`, but TestRail tokens and Google Sheets
OAuth/service-account secrets must be stored through the desktop secure
credential path. `GET /settings/connector-credentials` returns only account
metadata for that path:

```json
{
  "service": "tc-studio",
  "storage": "osCredentialStore",
  "secretsReturned": false,
  "connectors": {
    "testrail": {
      "credentials": [{ "kind": "apiToken", "account": "connector:testrail:apiToken" }]
    },
    "googleSheets": {
      "credentials": [{ "kind": "serviceAccountJson", "account": "connector:googleSheets:serviceAccountJson" }]
    }
  }
}
```

Renderer code uses those `service`/`account` values with the Electron
credential IPC. The IPC returns presence only to the renderer; plaintext
credential values remain available only inside the main process path that will
mediate real connector calls.

D9-04 Settings GUI rule: the desktop Settings surface exposes the current
project's self-healing auto-apply state as a structured toggle backed by
`self_healing.autoApplyProjectIds`. Saving the form sends the same full
`PUT /settings` payload used by advanced JSON editing, preserving unrelated
settings and canonicalizing legacy `auto_apply_project_ids` into
`autoApplyProjectIds`.

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
| POST | `/projects/{project_id}/cases/import/testrail/preview` | Implemented | Authenticated TestRail API v2 preview | C1-08 |
| POST | `/projects/{project_id}/cases/import/testrail` | Implemented | Authenticated TestRail API v2 import | C1-08 |
| POST | `/projects/{project_id}/cases/import/google-sheets/preview` | Implemented | Authenticated Google Sheets preview | C1-09 |
| POST | `/projects/{project_id}/cases/import/google-sheets` | Implemented | Authenticated Google Sheets import | C1-09 |

### TestRail Import

C1-08 replaces the placeholder TestRail import with API v2 `get_cases`.
Requests use non-secret settings (`integrations.testrail.baseUrl` and
`integrations.testrail.username`) plus a one-time `apiToken` supplied by the
desktop main process from the G-04 secure credential account
`connector:testrail:apiToken`. Worker request bodies may include `apiToken`,
but the value is not persisted or returned. Desktop renderer code must call the
Electron-mediated TestRail import IPC so plaintext tokens remain in the main
process boundary.

```json
{
  "project_id": 12,
  "suite_id": 3,
  "baseUrl": "https://example.testrail.io",
  "username": "qa@example.com",
  "apiToken": "<one-time secret>"
}
```

`mock: true` remains available for local/dev tests without external TestRail
credentials. API responses normalize TestRail cases into the same
`NormalizedTestCase` shape used by Excel and testrail-clone, including
`source_type: "testrail"`, TestRail case `source_id`, `source_location.api_endpoint`,
preconditions, separated steps, expected result, priority, start URL, and a
stable automation key from TestRail custom automation fields or generated from
the case identity. TestRail API and auth errors are returned as safe HTTP
details with token values masked.

### Google Sheets Import

C1-09 replaces the placeholder Google Sheets import with Google Sheets API v4
`spreadsheets.values.get`. Requests use non-secret settings such as
`integrations.googleSheets.spreadsheetId` plus a one-time credential JSON
supplied by the desktop main process from the G-04 secure credential account
`connector:googleSheets:serviceAccountJson`. Worker request bodies may include
`credentialJson`, but the value is not persisted or returned. Desktop renderer
code must call the Electron-mediated Google Sheets import IPC so plaintext
credential JSON remains in the main process boundary.

```json
{
  "spreadsheet_id": "1abc...",
  "sheet_name": "Cases",
  "credentialJson": "{...one-time OAuth token or service account JSON...}",
  "column_mapping": {
    "case_id": "Case ID",
    "title": "Title",
    "precondition": "Precondition",
    "step": "Step",
    "expected": "Expected Result",
    "priority": "Priority",
    "automation_key": "Automation Key",
    "start_url": "Start URL"
  }
}
```

Credential JSON may be an OAuth/access-token payload or a service-account JSON
with `client_email` and `private_key`; service-account credentials are exchanged
for a read-only Sheets access token. `mock: true` remains available for
local/dev tests without external Google credentials. Sheet rows normalize into
the same `NormalizedTestCase` shape as Excel import, including
`source_type: "google_sheets"`, row-derived `source_id`,
`source_location.sheet_name`, `source_location.row_index`,
`source_location.api_endpoint`, preconditions, mapped steps, expected result,
priority, start URL, and explicit or generated automation key. Google API and
auth errors are returned as safe HTTP details with credential values masked.

## Webwright Runs

| Method | Path | Status | Purpose | Checklist |
|--------|------|--------|---------|-----------|
| POST | `/projects/{project_id}/webwright-runs` | Implemented | 선택 TC Webwright run (`has_webwright_cli` 없으면 mock) | C4-04 |
| GET | `/projects/{project_id}/webwright-runs` | Implemented | Webwright run 목록 | C4-04 |
| GET | `/projects/{project_id}/webwright-runs/{run_id}` | Implemented | Webwright run 상세 | C4-04 |
| POST | `/projects/{project_id}/webwright-runs/{run_id}/retry` | Implemented | 특정 run 재시도 | C4-04 |
| POST | `/projects/{project_id}/webwright-runs/{run_id}/cancel` | Implemented | Mark run/case `cancelled`, terminate the active Webwright subprocess when present, and preserve cancellation during artifact harvest | C3-09, C4-04 |

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
| GET | `/projects/{project_id}/prompt-composer` | Implemented | Read project batch prompt, selected preset, and per-case overrides | C2-04, D4-07 |
| PUT | `/projects/{project_id}/prompt-composer` | Implemented | Replace project batch prompt, selected preset, and per-case overrides | C2-04, D4-07 |
| GET | `/projects/{project_id}/prompt-presets` | Implemented | Read built-in and project prompt presets | C2-05 |
| PUT | `/projects/{project_id}/prompt-presets` | Implemented | Replace project prompt presets; built-ins are immutable | C2-05 |
| POST | `/projects/{project_id}/prompt-preview` | Implemented | Preview effective prompt from case, optional preset, and saved prompt context without running Webwright | C2-06 |
| GET | `/projects/{project_id}/prompt-payloads?caseId=...&runId=...` | Implemented | List immutable Webwright prompt payload snapshots by project/case/run | C2-07 |
| GET | `/projects/{project_id}/prompt-payloads/{payload_id}` | Implemented | Read one immutable prompt payload snapshot | C2-07 |

C2-04 persists editable prompt composer state only, including the GUI's selected
preset ID for continuity. C2-05 persists reusable prompt preset definitions
separately. C2-06 previews the effective prompt read-only from the selected
case, optional preset, and saved prompt context. C2-07 records immutable per-run
prompt payload history when Webwright runs are created. D4-07 wires the Generate
Raw GUI to these Worker APIs instead of settings-only prompt state.

### PromptComposerUpdateRequest

```json
{
  "batchPrompt": "Use the signed-in admin workspace and prefer stable labels.",
  "selectedPresetId": "preset_builtin_login",
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
  "selectedPresetId": "preset_builtin_login",
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
insert selected preset guidance before saved batch and case context. The
composer's `selectedPresetId` is UI state for persistence; preview and run
requests still pass the desired `presetId` explicitly.

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
apply preset guidance by itself; preview and Webwright run requests apply
guidance when they include a `presetId`.

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
| GET | `/projects/{project_id}/cases/{case_id}/structure/validate` | Implemented | structure issues list consumed by Mapping Review | C7-09, D5-08 |

### Structure validate response

```json
{
  "ok": false,
  "issues": ["mapping_needs_review:step_2", "step_count_mismatch"],
  "flowId": "sf_abc123"
}
```

D5-08 wires Mapping Review to this endpoint for the selected case. The GUI
keeps its local draft validation as an immediate preflight, then merges Worker
validation issues from the saved structured flow, mappings, and generated-file
status. Mapping Review must preserve unsaved draft edits when the validation
request fails and surface stale/edited/conflict generated-file issues with the
same blocking severity used by generation conflict panels.

## Project Generation And IDE

| Method | Path | Status | Purpose | Checklist |
|--------|------|--------|---------|-----------|
| POST | `/projects/{project_id}/generate` | Implemented | DB structured entities → generated project; returns `runtimeBootstrap` | C8-03, C8-05 |
| POST | `/projects/{project_id}/generate/selected` | Implemented | selected TC incremental regeneration; preserve unrelated generated cases | C8-09 |
| POST | `/projects/{project_id}/cases/{case_id}/retire` | Implemented | human-confirmed TC retire/delete generated artifact cleanup foundation | C8-10 |
| GET | `/projects/{project_id}/generated-files` | Implemented | generated project 파일 트리 | C11-01 |
| GET | `/projects/{project_id}/generated-files/status` | Implemented | project-level generated-file edited/stale/conflict summary | C7-10, C7-13 |
| GET | `/projects/{project_id}/generated-files/content?path=...` | Implemented | 파일 내용 읽기 | C11-02 |
| PUT | `/projects/{project_id}/generated-files/content` | Implemented | 파일 내용 저장 | C11-02 |
| POST | `/projects/{project_id}/generated-files/create` | Implemented | 파일 생성 | C11-02 |
| DELETE | `/projects/{project_id}/generated-files?path=...` | Implemented | 파일 삭제 | C11-02 |
| POST | `/projects/{project_id}/generated-files/rename` | Implemented | 파일 이름 변경 | C11-02 |
| GET | `/projects/{project_id}/search?q=...` | Implemented | generated project 검색 | C11-03 |

C11-05 path containment rule: every generated-file read, write, create,
delete, rename, tree, and search operation resolves the generated project root
and requested path with `Path.resolve()` and requires the target to be
`relative_to(root)`. Requests must use relative paths only. Absolute paths,
drive-qualified paths, UNC paths, `..` traversal, root sibling-prefix tricks,
and symlink/junction escapes are rejected before filesystem side effects.
Mutating APIs return HTTP 400 for unsafe paths and HTTP 404 for missing
projects.

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

### GeneratedFileStatusResponse

`GET /projects/{project_id}/generated-files/status` returns a project-level
summary of tracked generated-file state without walking through each case's
`structure/validate` endpoint. It reuses the generated-file hash/status refresh
logic to detect local edits, preserves already-known source-change
`stale`/`conflict` states, and commits any status transitions.

The response is ordered by severity (`conflict`, `edited`, `stale`, `obsolete`,
then `generated`) and then by path. Each file includes its tracked path,
automation key, primary source, resolved origins when available, hashes,
edit/source-change flags, and guidance for GUI panels.

```json
{
  "projectId": "proj_123",
  "generatedProjectPath": "C:/work/project/generated",
  "ok": false,
  "counts": {
    "total": 4,
    "generated": 1,
    "edited": 1,
    "stale": 1,
    "conflict": 1,
    "obsolete": 0
  },
  "editedFiles": ["tests/test_login.py"],
  "staleFiles": ["pages/generated_page.py"],
  "conflictFiles": ["mappings/cases.yaml"],
  "obsoleteFiles": [],
  "files": [
    {
      "id": "gf_123",
      "path": "mappings/cases.yaml",
      "relativePath": "mappings/cases.yaml",
      "status": "conflict",
      "automationKey": null,
      "sourceType": "structured_flow",
      "sourceId": "flow_123",
      "source": {
        "type": "structured_flow",
        "id": "flow_123",
        "automationKey": "login_required_flow",
        "testCaseId": "tc_123"
      },
      "origins": [
        {
          "type": "test_case",
          "id": "tc_123",
          "automationKey": "login_required_flow",
          "title": "Login required flow"
        }
      ],
      "contentHash": "sha256...",
      "currentHash": "sha256...",
      "onDiskChanged": true,
      "sourceChanged": true,
      "plannedDeletion": false,
      "exists": true,
      "guidance": {
        "severity": "error",
        "blocksGeneration": true,
        "action": "resolve_conflict"
      }
    }
  ]
}
```

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
| POST | `/projects/{project_id}/executions/{execution_id}/cancel` | Implemented | Mark execution `cancelled`, terminate the active `runner.cli` subprocess when present, and preserve cancellation during artifact harvest | C9-05, C9-08 |
| POST | `/projects/{project_id}/executions/{execution_id}/export/{target}` | Implemented | result export | C10-06 |

Subprocess env includes `TC_HEADLESS`, `PLAYWRIGHT_BROWSERS_PATH` when configured.

Before runner execution, dependency bootstrap is fail-fast (C9-06). If
`requirements.txt`, pip install, Playwright install, or browser verification
fails, the API records an execution failure with bootstrap logs/results instead
of launching `runner.cli`.

C9-07 adds per-project runtime install-state reuse before `runner.cli`: cache
hits skip redundant pip/Playwright install commands, while stale or missing
cache entries fall back to the same fail-fast bootstrap path.

C9-08 tracks active normal execution and `rerun-failed` subprocesses by
`ExecutionRun.id` and returned `jobId`. Cancelling an in-flight execution sends
a graceful terminate with kill fallback, writes masked cancellation diagnostics
to stdout/stderr logs and a cancelled `results.json`, preserves final
`ExecutionRun.status=cancelled`, and does not persist stale `ExecutionResult`
rows from partial runner output. Cancelled run log/metadata artifacts remain
indexed for review.

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

### TestRail Result Export

C10-07 replaces the TestRail local-mock write-back with API v2
`add_result_for_case/{run_id}/{case_id}` when `integrations.testrail.enabled`
is true. Non-secret settings provide `baseUrl`, `username`, and a result
`runId`/`resultRunId`; the desktop main process supplies a one-time `apiToken`
from the G-04 secure credential account `connector:testrail:apiToken`.

```json
{
  "preview": false,
  "config": {
    "apiToken": "<one-time secret>",
    "runId": "42"
  }
}
```

Preview mode never calls TestRail and may include `targetPayload` showing the
resolved TestRail run/case IDs and request body. Non-preview export validates
the generated mapping and `ExecutionResult` identities before any mutation,
then posts each result with status mapping (`passed` -> 1, `failed` -> 5,
blocked/skipped/cancelled -> 2 by default), automation key/comment context, and
elapsed duration. Per-row mapping metadata may override the destination through
`resultTargets.testrail.runId` and `resultTargets.testrail.caseId`; otherwise
the configured run ID and result `sourceCaseId` are used. API failures insert a
failed `ExportLog` with masked details and return a safe HTTP 400. When the
TestRail integration is disabled or `config.mock` is true, the existing
`local-mock` success flow remains available for local/dev tests.

### Google Sheets Result Export

C10-08 replaces the Google Sheets local-mock write-back with authenticated
Google Sheets API v4 `spreadsheets.values.batchUpdate` calls when
`integrations.googleSheets.enabled` is true. Non-secret settings provide
`spreadsheetId`, optional `sheetName`/`resultSheetName`, optional `headerRow`,
and optional result column header names. The desktop main process supplies a
one-time credential JSON from the G-04 secure credential account
`connector:googleSheets:serviceAccountJson`.

```json
{
  "preview": false,
  "config": {
    "credentialJson": "<one-time secret>"
  }
}
```

Preview mode never calls Google Sheets and may include `targetPayload` showing
the resolved spreadsheet, sheet, row, and header/value payload. Non-preview
export validates generated mapping and `ExecutionResult` identities before any
mutation, then reads the configured header row, creates missing result headers
(`Automation Result`, `Automation Run ID`, `Automation Executed At`,
`Automation Comment` by default), and updates only those result cells for each
mapped row. Per-row mapping metadata may override the destination through
`resultTargets.googleSheets.spreadsheetId`, `sheet`/`sheetName`, and `row`;
Google Sheets sourced cases generated by C10-08 include that target from their
source location. API failures insert a failed `ExportLog` with masked details
and return a safe HTTP 400. When the Google Sheets integration is disabled or
`config.mock` is true, the existing `local-mock` success flow remains available
for local/dev tests.

## Artifacts And Self-Healing

| Method | Path | Status | Purpose | Checklist |
|--------|------|--------|---------|-----------|
| GET | `/projects/{project_id}/artifacts?automation_key=...` | Implemented | Project-scoped Webwright/execution artifact evidence read API | C12-01, C12-03, C12-11 |
| GET | `/projects/{project_id}/cases/{case_id}/selector-candidates` | Implemented | Project-scoped persisted raw-action/PageObjectMethod selector candidate read API | C12-02, C12-12 |
| POST | `/projects/{project_id}/executions/{execution_id}/diagnose` | Implemented | classify failed cases into dispositions with evidence/confidence | C12-08 |
| POST | `/projects/{project_id}/executions/{execution_id}/healing-proposals` | Implemented | failed execution result -> selector healing proposal generation; project-enabled safe auto-apply | C12-05, C12-07 |
| GET | `/projects/{project_id}/healing-proposals?automation_key=...` | Implemented | proposal list by project/key | C12-05 |
| GET | `/projects/{project_id}/healing-proposals/{proposal_id}` | Implemented | proposal detail with evidence JSON | C12-05 |
| POST | `/projects/{project_id}/healing-proposals/{proposal_id}/accept` | Implemented | accept proposal and preserve evidence | C12-06 |
| POST | `/projects/{project_id}/healing-proposals/{proposal_id}/reject` | Implemented | reject proposal without mutation | C12-06 |
| POST | `/projects/{project_id}/healing-proposals/{proposal_id}/apply` | Implemented | apply accepted selector proposal with guarded selected regeneration and rerun context | C12-06 |
| POST | `/projects/{project_id}/cases/{case_id}/refresh-webwright-and-regenerate` | Implemented | selected already-structured TC Webwright refresh -> raw merge into existing structure -> incremental regeneration | C12-09, C7-12, C8-09 |

### ArtifactResponse

`GET /projects/{project_id}/artifacts` returns indexed artifact metadata without
reading file bytes. The endpoint is project-scoped and supports both camelCase
and snake_case query aliases for:

- `automationKey` / `automation_key`
- `sourceType` / `source_type`
- `sourceId` / `source_id`
- `artifactType` / `artifact_type`
- `runId` / `run_id`
- `webwrightRunId` / `webwright_run_id`
- `executionId` / `execution_id`

`executionId` returns both execution-run artifacts and artifacts attached to
results from that execution. `filePath` is populated only when the indexed path
is inside the related Webwright output directory or execution result directory,
or matches a known source artifact path; otherwise the row remains visible with
`pathAvailable: false` and `filePath: null`.

```json
{
  "projectId": "proj_123",
  "artifacts": [
    {
      "id": "art_123",
      "projectId": "proj_123",
      "automationKey": "login_required_flow",
      "sourceType": "execution_result",
      "sourceId": "result_123",
      "artifactType": "trace",
      "kind": "trace",
      "title": "trace.zip",
      "filePath": "C:/tc-studio/runs/exec_123/trace.zip",
      "pathAvailable": true,
      "fileName": "trace.zip",
      "relativePath": "trace.zip",
      "contentHash": "sha256:...",
      "metadata": {
        "file_name": "trace.zip",
        "relative_path": "trace.zip",
        "size_bytes": 1234
      },
      "createdAt": "2026-06-12T00:00:00"
    }
  ]
}
```

### SelectorCandidatesResponse

`GET /projects/{project_id}/cases/{case_id}/selector-candidates` is read-only.
It validates that the selected case belongs to the project, then returns only
persisted `SelectorCandidate` rows linked to that selected case. Candidate
scope includes raw actions from Webwright runs for the case and PageObject
methods linked through selected-case mappings or structured steps. PageObject
methods must also belong to project-owned PageObjects.

The flat `candidates` list includes stable candidate IDs, selector type/value,
confidence, parsed metadata, raw-action context when linked, PageObjectMethod
context when linked, and source artifact metadata when the artifact belongs to
the project. `sourceArtifact.filePath` follows the same safe-path rules as
`ArtifactResponse`; unsafe absolute paths are omitted with `pathAvailable:
false`.

`groups.rawActions` and `groups.pageObjectMethods` provide review-panel
grouping without duplicating candidate payloads.

```json
{
  "projectId": "proj_123",
  "caseId": "tc_123",
  "automationKey": "login_required_flow",
  "candidateCount": 2,
  "rawActionIds": ["act_001"],
  "pageObjectMethodIds": ["pom_001"],
  "candidates": [
    {
      "id": "sel_001",
      "selectorType": "role",
      "selectorValue": "button[name='Log in']",
      "type": "role",
      "value": "button[name='Log in']",
      "confidence": 0.91,
      "sourceArtifactId": "art_001",
      "metadata": {"source": "trajectory"},
      "createdAt": "2026-06-13T00:00:00",
      "rawAction": {
        "id": "act_001",
        "webwrightRunId": "ww_001",
        "webwrightRunStatus": "completed",
        "automationKey": "login_required_flow",
        "orderIndex": 1,
        "type": "click",
        "target": "Log in",
        "selector": "page.locator('#login')",
        "value": null,
        "sourceLine": 12
      },
      "pageObjectMethod": {
        "id": "pom_001",
        "name": "login_required_flow__step_1_log_in",
        "methodType": "click",
        "selector": "page.locator('#login')",
        "sourceMappingId": "map_001",
        "status": "approved",
        "pageObjectId": "po_001",
        "pageObjectName": "LoginPage",
        "mapping": {"id": "map_001", "tcStepIndex": 1},
        "structuredSteps": [{"id": "step_001", "orderIndex": 1}],
        "tcStepIndexes": [1]
      },
      "sourceArtifact": {
        "id": "art_001",
        "sourceType": "webwright_run",
        "sourceId": "ww_001",
        "artifactType": "trajectory",
        "pathAvailable": true
      }
    }
  ],
  "groups": {
    "rawActions": [
      {
        "rawAction": {"id": "act_001", "orderIndex": 1, "type": "click"},
        "candidateIds": ["sel_001"],
        "candidateCount": 1
      }
    ],
    "pageObjectMethods": [
      {
        "pageObjectMethod": {"id": "pom_001", "name": "login_required_flow__step_1_log_in"},
        "candidateIds": ["sel_001"],
        "candidateCount": 1
      }
    ]
  }
}
```

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
`selector_replace` proposal for resolved `selector_changed` failures with
linked selector candidates. Non-selector or unresolved diagnoses return
`status=not_applicable` unless an extended C12-13 proposal can be safely built.
Repeated matching calls return the existing proposal.

```json
{
  "executionResultId": "result_123",
  "kind": "wait_adjust",
  "proposal": {
    "bodyPlanIndex": 1,
    "timeoutMs": 15000,
    "confidence": 0.83
  }
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

C12-13 extends `kind` beyond `selector_replace` to `wait_adjust`,
`assertion_update`, and `pom_method_patch`. For those kinds the create request
may pass `kind` plus a structured `proposal` object, or Worker may use
artifact metadata hints (`healing_proposal`, `healingProposal`, or `proposal`)
and conservative wait/assertion error inference. Extended proposals store
compact JSON patch payloads in `old_value`/`new_value` and evidence metadata in
`evidence`. `accept`/`reject` are shared with selector proposals. `apply`
requires `accepted`, checks the resolved POM/step target, patches the targeted
wait/assertion/body-plan method state, runs selected incremental generation,
and rolls back DB changes if the generated-file guard reports a conflict.
Auto-apply remains selector-only.

## WebSocket

| Path | Status | Purpose |
|------|--------|---------|
| `/ws/logs/{job_id}?token=...` | Implemented | Webwright run, execution run stdout/stderr stream; token and allowed Origin required |

## Planned API Follow-ups

| Area | Item |
|------|------|
