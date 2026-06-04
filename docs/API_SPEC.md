# API Spec

Last aligned: 2026-06-04

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
| POST | `/projects/{project_id}/install-dependencies` | Implemented | generated project pip + chromium (`RuntimeProfile.python`) | I-02, I-07 |

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
  "integrations": {
    "testrailClone": { "baseUrl": "http://localhost:3000", "enabled": false },
    "testrail": { "baseUrl": "", "enabled": false },
    "googleSheets": { "enabled": false }
  }
}
```

`bundled` 모드에서는 `runtime.*` 경로가 installer `resources/runtime`에서 시드된다. `custom` 모드에서는 Setup/Settings에서 사용자가 지정한다.

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

### WebwrightRunRequest

```json
{
  "caseIds": ["tc_123"],
  "mode": "sequential",
  "modelConfig": "model_openai.yaml",
  "startUrlOverride": "https://example.test"
}
```

## Mapping And Review

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
| POST | `/projects/{project_id}/generate/selected` | Planned | selected TC incremental regeneration; preserve unrelated generated cases | C8-09 |
| POST | `/projects/{project_id}/cases/{case_id}/retire` | Planned | human-confirmed TC retire/delete plus generated artifact cleanup | C8-10, C12-10 |
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
    "pip": "...",
    "pipError": "",
    "playwright": "...",
    "playwrightBrowser": { "ok": true, "browser": "chromium" }
  }
}
```

Generation pipeline: `sync_structured_entities` → codegen from DB → `GeneratedFile` with `content_hash`, `source_type=structured_flow` ([STRUCTURING_SPEC.md](./STRUCTURING_SPEC.md)).

Selected generation contract: when a request targets only selected `caseIds`,
the API must not wipe and recreate the whole generated project. It must run the
selected TC incremental regeneration flow from
[STRUCTURING_SPEC.md](./STRUCTURING_SPEC.md), merge `mappings/cases.yaml`,
return affected files, and preserve unrelated generated cases. Full
regeneration must be explicit.

### Generate Request

```json
{
  "caseIds": ["tc_123"]
}
```

## Executions

| Method | Path | Status | Purpose | Checklist |
|--------|------|--------|---------|-----------|
| POST | `/projects/{project_id}/executions` | Implemented | `runner.cli` via `RuntimeProfile.python`; auto bootstrap | C9-05 |
| GET | `/projects/{project_id}/executions` | Implemented | execution run 목록 | C9-05 |
| GET | `/projects/{project_id}/executions/{execution_id}` | Implemented | run + results | C9-04 |
| POST | `/projects/{project_id}/executions/{execution_id}/rerun-failed` | Implemented | failed cases rerun | C9-05 |
| POST | `/projects/{project_id}/executions/{execution_id}/cancel` | Partial | status cancel only | C9-05 |
| POST | `/projects/{project_id}/executions/{execution_id}/export/{target}` | Implemented | result export | C10-06 |

Subprocess env includes `TC_HEADLESS`, `PLAYWRIGHT_BROWSERS_PATH` when configured.

Before runner execution, dependency bootstrap is fail-fast (C9-06). If
`requirements.txt`, pip install, Playwright install, or browser verification
fails, the API records an execution failure with bootstrap logs/results instead
of launching `runner.cli`.

## Artifacts And Self-Healing

| Method | Path | Status | Purpose | Checklist |
|--------|------|--------|---------|-----------|
| GET | `/projects/{project_id}/artifacts?automation_key=...` | Planned | Webwright/execution artifacts 조회 | C12-01, C12-03 |
| GET | `/projects/{project_id}/cases/{case_id}/selector-candidates` | Planned | raw action/POM selector candidates 조회 | C12-02 |
| POST | `/projects/{project_id}/executions/{execution_id}/diagnose` | Implemented | failed cases를 disposition으로 분류하고 evidence/confidence 반환 | C12-08 |
| POST | `/projects/{project_id}/executions/{execution_id}/healing-proposals` | Planned | 실패 실행 기반 healing proposal 생성 | C12-05 |
| GET | `/projects/{project_id}/healing-proposals?automation_key=...` | Planned | proposal 목록 조회 | C12-05 |
| POST | `/projects/{project_id}/healing-proposals/{proposal_id}/accept` | Planned | proposal 수락 및 structured metadata 패치 | C12-06 |
| POST | `/projects/{project_id}/healing-proposals/{proposal_id}/reject` | Planned | proposal 거절 | C12-06 |
| POST | `/projects/{project_id}/healing-proposals/{proposal_id}/apply` | Planned | 수락된 proposal 적용, regenerate 준비 | C12-06 |
| POST | `/projects/{project_id}/cases/{case_id}/refresh-webwright-and-regenerate` | Planned | selected already-structured TC Webwright refresh → raw merge into existing structure → incremental regeneration | C12-09, C7-12, C8-09 |

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

### HealingProposal

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

## WebSocket

| Path | Status | Purpose |
|------|--------|---------|
| `/ws/logs/{job_id}` | Implemented | Webwright run, execution run stdout/stderr stream |

## Planned API Follow-ups

| Area | Item |
|------|------|
| Webwright | subprocess cancel for in-flight CLI |
| Structuring | stale/conflict API beyond validate issues list |
| Healing | C12-05..C12-07 and C12-09..C12-10 proposal lifecycle, selected raw refresh, and TC retire cleanup |
| Prompt | C2-04..C2-07 batch prompt / preset / audit APIs |
