# API Spec

Last aligned: 2026-05-31

Base URL in development: `http://127.0.0.1:8765`

이 문서는 Local Worker(FastAPI)가 Electron GUI와 generated automation project를 연결하기 위해 제공하는 HTTP/WebSocket 계약을 정리한다. GUI 호출은 [PRODUCT_PILLARS.md](./PRODUCT_PILLARS.md)의 workspace별 surface와 대응한다.

## Principles

- API는 로컬 전용이다. 기본 바인딩은 `127.0.0.1`이다.
- GUI는 자동화 로직을 직접 수행하지 않고 Worker API를 호출한다.
- 모든 프로젝트 종속 리소스는 가능하면 `/projects/{project_id}/...` 아래에 둔다.
- 장기 작업은 즉시 `jobId`를 반환하고 로그는 `/ws/logs/{job_id}`로 스트리밍한다.
- `automation_key`는 TC, raw action, structured test, execution result를 잇는 핵심 키다.

## API By Product Workspace

| Workspace | API groups | Primary GUI surfaces |
|-----------|------------|----------------------|
| **Generate Raw** | Projects, Cases/Import, Webwright Runs, Prompt (C2), Settings/Health | Dashboard, Import, Cases, Prompt, Webwright, Artifacts |
| **Automation IDE** | Mapping, Generation, IDE files, Executions, Export, Healing | Mapping, Structure, IDE, Runner/Results/Export panels |
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
| GET | `/health` | Implemented | Worker, Python, Webwright, Playwright 등 로컬 상태 점검 | A3-05 |
| GET | `/settings` | Implemented | `settings.json` 로드 | A3-04 |
| PUT | `/settings` | Implemented | 앱 설정 저장 | A3-04 |
| POST | `/settings/validate` | Partial | 설정 유효성 검증. 현재 health check와 동일한 성격 | A3-05 |
| POST | `/projects/{project_id}/health` | Implemented | generated project 경로 상태 점검 | I-01 |
| POST | `/projects/{project_id}/install-dependencies` | Partial | generated project 의존성 설치 | I-02 |

### AppSettings

```json
{
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
| GET | `/projects/{project_id}/cases` | Implemented | TC 목록 조회 | C1-07 |
| GET | `/projects/{project_id}/cases/{case_id}` | Implemented | normalized TC 상세 조회 | C1-07 |
| PATCH | `/projects/{project_id}/cases/{case_id}` | Partial | TC 상태, start URL 등 일부 수정 | C1-07 |
| POST | `/projects/{project_id}/cases/import/excel/preview` | Implemented | Excel 미리보기와 컬럼 매핑 확인 | C1-02 |
| POST | `/projects/{project_id}/cases/import/excel` | Implemented | Excel TC import | C1-03 |
| POST | `/projects/{project_id}/cases/import/testrail-clone` | Partial | testrail-clone TC import | C1-04 |
| POST | `/projects/{project_id}/cases/import/testrail` | Partial | TestRail TC import | C1-05 |
| POST | `/projects/{project_id}/cases/import/google-sheets` | Partial | Google Sheets TC import | C1-06 |

### NormalizedTestCase

```json
{
  "id": "tc_123",
  "source_type": "excel",
  "source_id": "CASE-001",
  "title": "User can login",
  "preconditions": ["User exists"],
  "steps": [
    { "index": 1, "action": "Open login page", "expected": "Login page is shown" }
  ],
  "expected_result": "User lands on dashboard",
  "automation_key": "user_login_001",
  "tags": ["smoke"],
  "priority": "P1",
  "start_url": "https://example.test/login",
  "status": "imported"
}
```

### Excel Preview/Import Request

```json
{
  "file_path": "C:/cases/sample_cases.xlsx",
  "sheet_name": "Cases",
  "column_mapping": {
    "case_id": "Case ID",
    "title": "Title",
    "precondition": "Precondition",
    "step": "Step",
    "expected": "Expected Result",
    "priority": "Priority",
    "automation_key": "Automation Key",
    "start_url": "Start URL"
  },
  "selected_rows": [2, 3, 4]
}
```

## Webwright Runs

| Method | Path | Status | Purpose | Checklist |
|--------|------|--------|---------|-----------|
| POST | `/projects/{project_id}/webwright-runs` | Implemented | 선택 TC에 대해 Webwright run 생성 | C4-04 |
| GET | `/projects/{project_id}/webwright-runs` | Implemented | Webwright run 목록 | C4-04 |
| GET | `/projects/{project_id}/webwright-runs/{run_id}` | Implemented | Webwright run 상세 | C4-04 |
| POST | `/projects/{project_id}/webwright-runs/{run_id}/retry` | Implemented | 특정 run 재시도 | C4-04 |
| POST | `/projects/{project_id}/webwright-runs/{run_id}/cancel` | Partial | 상태를 `cancelled`로 변경. 실제 subprocess cancel은 고도화 필요 | C4-04 |

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

### MappingUpdateRequest

```json
{
  "actions": [
    {
      "id": "act_123",
      "type": "click",
      "target": "Login button",
      "selector": "button[type=submit]",
      "value": null,
      "source_line": 18,
      "order_index": 1
    }
  ],
  "mappings": [
    {
      "tc_step_index": 1,
      "action_ids": ["act_123"],
      "normalized_step_name": "submit_login",
      "pom_method_name": "click_login_button",
      "status": "mapped"
    }
  ]
}
```

## Project Generation And IDE

| Method | Path | Status | Purpose | Checklist |
|--------|------|--------|---------|-----------|
| POST | `/projects/{project_id}/generate` | Implemented | reviewed mapping 기반 generated project 생성 | C8-03 |
| GET | `/projects/{project_id}/generated-files` | Implemented | generated project 파일 트리 | C11-01 |
| GET | `/projects/{project_id}/generated-files/content?path=...` | Implemented | 파일 내용 읽기 | C11-02 |
| PUT | `/projects/{project_id}/generated-files/content` | Implemented | 파일 내용 저장 | C11-02 |
| POST | `/projects/{project_id}/generated-files/create` | Implemented | 파일 생성 | C11-02 |
| DELETE | `/projects/{project_id}/generated-files?path=...` | Implemented | 파일 삭제 | C11-02 |
| POST | `/projects/{project_id}/generated-files/rename` | Implemented | 파일 이름 변경 | C11-02 |
| GET | `/projects/{project_id}/search?q=...` | Implemented | generated project 검색 | C11-03 |

## Artifacts And Self-Healing

| Method | Path | Status | Purpose | Checklist |
|--------|------|--------|---------|-----------|
| GET | `/projects/{project_id}/artifacts?automation_key=...` | Planned | Webwright/execution artifacts 조회 | C12-01, C12-03 |
| GET | `/projects/{project_id}/cases/{case_id}/selector-candidates` | Planned | raw action/POM selector candidates 조회 | C12-02 |
| POST | `/projects/{project_id}/executions/{execution_id}/healing-proposals` | Planned | 실패 실행 기반 healing proposal 생성 | C12-05 |
| GET | `/projects/{project_id}/healing-proposals?automation_key=...` | Planned | proposal 목록 조회 | C12-05 |
| POST | `/projects/{project_id}/healing-proposals/{proposal_id}/accept` | Planned | proposal 수락 및 structured metadata 패치 | C12-06 |
| POST | `/projects/{project_id}/healing-proposals/{proposal_id}/reject` | Planned | proposal 거절 | C12-06 |
| POST | `/projects/{project_id}/healing-proposals/{proposal_id}/apply` | Planned | 수락된 proposal 적용, regenerate 준비 | C12-06 |

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

### Generate Request

```json
{
  "caseIds": ["tc_123"]
}
```

### File Update Request

```json
{
  "path": "tests/test_user_login_001.py",
  "content": "def test_user_login(page):\n    ..."
}
```

## Executions

| Method | Path | Status | Purpose | Checklist |
|--------|------|--------|---------|-----------|
| POST | `/projects/{project_id}/executions` | Implemented | generated project runner 실행 | C9-05 |
| GET | `/projects/{project_id}/executions` | Implemented | 실행 목록 | C9-05 |
| GET | `/projects/{project_id}/executions/{execution_id}` | Implemented | 실행 상세, results, summary | C9-04, C9-05 |
| POST | `/projects/{project_id}/executions/{execution_id}/rerun-failed` | Implemented | 실패 케이스 재실행 | C9-05 |
| POST | `/projects/{project_id}/executions/{execution_id}/cancel` | Partial | 상태를 `cancelled`로 변경. 실제 subprocess cancel은 고도화 필요 | C9-05 |

### ExecutionRequest

```json
{
  "env": "stg",
  "browser": "chromium",
  "headed": false,
  "target_type": "all",
  "automation_key": "user_login_001",
  "case_ids": ["tc_123"],
  "result_target": "local"
}
```

## Result Export

| Method | Path | Status | Purpose | Checklist |
|--------|------|--------|---------|-----------|
| POST | `/projects/{project_id}/executions/{execution_id}/export/testrail-clone` | Partial | testrail-clone 결과 반영 또는 preview | C10-01, C10-06 |
| POST | `/projects/{project_id}/executions/{execution_id}/export/testrail` | Partial | TestRail 결과 반영 또는 preview | C10-02 |
| POST | `/projects/{project_id}/executions/{execution_id}/export/excel` | Partial | Excel write-back 또는 preview | C10-03 |
| POST | `/projects/{project_id}/executions/{execution_id}/export/google-sheets` | Partial | Google Sheets write-back 또는 preview | C10-04 |

### ExportRequest

```json
{
  "preview": true,
  "config": {
    "targetRunId": "run_123"
  }
}
```

## Logs

| Type | Path | Status | Purpose | Checklist |
|------|------|--------|---------|-----------|
| WebSocket | `/ws/logs/{job_id}` | Implemented | Webwright/generation/execution 로그 스트림 | A4-03, C9-03 |

## Gaps To Track

- Request/response 모델이 일부 `dict` 기반이다. PR 범위가 닿을 때 Pydantic 모델로 고정한다.
- 일부 import/export integration은 mock 또는 thin adapter 수준일 수 있다.
- cancel endpoint는 상태 변경 이상의 실제 프로세스 종료까지 확장해야 한다.
- API key/token은 HTTP payload가 아니라 Electron keytar/OS credential store를 통해 관리한다.
