# Implementation Checklist

**Last updated:** 2026-06-06
**Current phase:** Phase 5
**Architecture:** [webwright_automation_generator_architecture.md](../webwright_automation_generator_architecture.md)  
**Product workspaces:** [PRODUCT_PILLARS.md](./PRODUCT_PILLARS.md)  
**UI/UX:** [UI_UX_DIRECTION.md](./UI_UX_DIRECTION.md)  
**Structuring:** [STRUCTURING_SPEC.md](./STRUCTURING_SPEC.md)  
**Self-healing:** [SELF_HEALING_SPEC.md](./SELF_HEALING_SPEC.md)  
**DB schema:** [DB_SCHEMA.md](./DB_SCHEMA.md)

## How to use

- Wave/PR 완료 시 해당 `[ ]` → `[x]` 갱신
- 각 항목의 `§` 번호는 아키텍처 문서 절과 역매핑
- `Spec:` 표기는 보조 스펙 문서와 역매핑
- UI는 2개 최상위 작업공간, `Generate Raw`와 `Automation IDE`, 기준으로 구현
- **Depends on** — 선행 체크리스트 ID

## Progress summary

| Category | Done | Total |
|----------|------|-------|
| A. Infra | 33 | 33 |
| B. Template | 20 | 20 |
| C. Worker | 87 | 87 |
| D. GUI | 49 | 49 |
| E. E2E | 12 | 12 |
| F. Errors | 4 | 4 |
| G. Security | 3 | 3 |
| H. MVP Gates | 4 | 4 |
| I. Quality | 9 | 9 |


## Implementation audit (2026-06-02)

Scope checked: repository, spec docs under `docs/`, `npm run build`, worker `tests/test_runtime.py` and `tests/e2e/test_smoke.py`.

- **Shipped (runtime + structuring pass):** `RuntimeProfile` resolver, `settings.runtime`, unified health/validate/install, Webwright live readiness gate, DB-backed structuring (`structure/sync`, `structure/validate`), DB-backed `project_generator`, generated-template `pytest_plugins` + single pytest invocation, `ensure_generated_runtime`, Electron bundled env, `prepare-runtime.ps1` + `dist:win:full`, Setup/Settings bundled read-only paths, Runner **Install Runtime** UX. Spec: [RUNTIME_SPEC.md](./RUNTIME_SPEC.md).
- **Build gate:** `npm run build` passes; I-06, I-07 closed.
- **Spec gaps to keep open:** Webwright subprocess cancel (not only DB status).
- **Installer verification resolved (2026-06-04):** clean `dist:win:full`, silent NSIS install into a new directory, fresh Electron user profile, installed bundled live health, installed-app real Webwright raw generation, generated project, and bundled Chromium Runner completion are recorded in RUNTIME_SPEC.
- **Webwright packaging decision:** resolved by C3-08. Product/live `prepare-runtime` now defaults to vendored `third_party/webwright` with license/notice/version metadata; explicit external `WEBWRIGHT_SOURCE` + `WEBWRIGHT_SOURCE_VERSION` or pinned `WEBWRIGHT_PIP_PACKAGE` remains supported; mock staging requires explicit opt-in.

## Runtime/Generated Project planning correction (2026-06-03)

Scope checked: RuntimeProfile, Webwright adapter, generated runtime bootstrap, generated-template pytest fixtures, project_generator, structuring service, Windows runtime staging docs.

- **Resolved:** Webwright live-run readiness now rejects placeholder `base.yaml` roots without an importable `webwright.run.cli` (C3-07), and live bundled runtime staging now uses vendored Webwright by default while still allowing explicit external source/package overrides (C3-08).
- **Resolved:** installer staging, in-app bootstrap, and bundled Chromium validation now prove Python + Playwright browser assets before raw generation or generated execution (C9-06, C9-07, I-07, I-08, E-09, E-10).
- **Resolved:** generated-template now documents and implements explicit pytest fixture/browser policy, including `conftest.py` plugin registration, `TC_HEADLESS`, and `PLAYWRIGHT_BROWSERS_PATH` (B3-04, B2-08).
- **Resolved:** C7-11 now compiles ordered multi-action mappings into deterministic PageObjectMethod body plans covering assertions, waits, select/check/upload, value templates, source IDs, and explicit review flags.
- **Resolved:** C8-07 now persists complete `GeneratedFileOrigin` links and replaces stale origin sets on regeneration; C7-10 detects edited/stale/conflict generated-file state; C8-06 enforces deterministic full/selected regeneration preflight before rewrites/deletes; C8-04 makes generated output Git-ready while preserving existing Git metadata; C8-08 writes a deterministic generated-project runtime manifest from template and RuntimeProfile defaults; C9-07 caches successful generated runtime readiness per project/runtime fingerprint.
- **Resolved:** C12-06 applies accepted selector proposals through guarded selected regeneration with conflict rollback and rerun context; C12-07 adds project-enabled auto-apply guardrails for safe selector proposals.
- **Resolved:** C2-04 persists project-scoped batch prompt and per-case overrides in the Worker and wires them into Webwright prompt generation without changing no-context runs. C2-05 persists built-in and project prompt presets separately without applying them to run prompts yet. C2-06 adds a read-only prompt preview API that combines base prompt, optional preset guidance, and saved batch/case context without creating run/history rows. C2-07 records immutable per-run Webwright prompt payload snapshots for audit/history.

---

## A. 프로젝트 기반 및 인프라 (Phase 0)

### A1. Monorepo / DevEnv

- [x] **A1-01** 루트 monorepo 구조 생성 — §4.1 | Phase 0 | Layer: Infra (baseline scaffold verified)
- [x] **A1-02** desktop: Electron + React + TypeScript + Tailwind — §5.1 | Phase 0 | Layer: Infra | Depends: A1-01 (baseline scaffold verified; dev launch confirmed)
- [x] **A1-03** worker: FastAPI + Uvicorn + Pydantic + SQLModel — §5.2 | Phase 0 | Layer: Infra | Depends: A1-01 (baseline scaffold verified; root and /health respond 200)
- [x] **A1-04** 통합 dev 스크립트 — §4.1 | Phase 0 | Layer: Infra | Depends: A1-02, A1-03 (baseline scaffold verified; dev, dev:worker, dev:desktop confirmed)
- [x] **A1-05** 루트 README, `.gitignore`, Python/Node 버전 고정 — §15 | Phase 0 | Layer: Infra | Depends: A1-01 (baseline scaffold verified; README, gitignore, .nvmrc, .python-version)

### A2. SQLite / Data Layer — §6

- [x] **A2-01** `Project` 모델 + migration — §6.1 | Phase 0 | Layer: Worker | Depends: A1-03 (baseline scaffold verified; init_db creates project table; POST/GET /projects persist)
- [x] **A2-02** `TestCase` 모델 — §6.2 | Phase 0 | Layer: Worker | Depends: A2-01 (baseline scaffold verified; testcase table + Excel import/list)
- [x] **A2-03** `WebwrightRun` 모델 — §6.3 | Phase 0 | Layer: Worker | Depends: A2-01 (baseline scaffold verified; SQLModel table, init_db create_all, and Webwright run create/list flow confirmed)
- [x] **A2-04** `RawAction` 모델 — §6.4 | Phase 0 | Layer: Worker | Depends: A2-03 (baseline scaffold verified; SQLModel table, extraction persistence, and actions list flow confirmed)
- [x] **A2-05** `CaseActionMapping` 모델 — §6.5 | Phase 0 | Layer: Worker | Depends: A2-02, A2-04 (baseline scaffold verified; SQLModel table, auto-map persistence, and mappings list flow confirmed)
- [x] **A2-06** `ExecutionRun` / `ExecutionResult` 모델 — §6.6, §6.7 | Phase 0 | Layer: Worker | Depends: A2-01 (baseline scaffold verified; SQLModel tables, execution create/list/detail, and result persistence confirmed)
- [x] **A2-07** DB 초기화 및 프로젝트별 데이터 격리 — §5.3 | Phase 0 | Layer: Worker | Depends: A2-06 (baseline scaffold verified; configured data-dir create_all and project-scoped case/run/execution isolation confirmed)
- [x] **A2-08** `CaseActionMappingAction` join 모델 — Spec: DB_SCHEMA | Phase 1 | Layer: Worker | Depends: A2-05 (baseline join model verified; `case_action_mapping_actions` stores ordered multi-action links while preserving current mapping API behavior)
- [x] **A2-09** `StructuredFlow` / `StructuredStep` 모델 — Spec: STRUCTURING_SPEC, DB_SCHEMA | Phase 1 | Layer: Worker | Depends: A2-05 (baseline structured flow/step models verified; `structured_flows` and `structured_steps` persist ordered steps linked back to mappings)
- [x] **A2-10** `PageObject` / `PageObjectMethod` 모델 — Spec: STRUCTURING_SPEC, DB_SCHEMA | Phase 1 | Layer: Worker | Depends: A2-09 (baseline page object/method models verified; `page_objects` and `page_object_methods` persist typed method plans linked back to mappings)
- [x] **A2-11** `GeneratedFileOrigin`, `content_hash`, `status` 모델 — Spec: DB_SCHEMA | Phase 1 | Layer: Worker | Depends: A2-10 (schema/model baseline verified; runtime persistence of multiple origin links is tracked separately by C8-07)
- [x] **A2-12** schema version / migration baseline — Spec: DB_SCHEMA | Phase 1 | Layer: Worker | Depends: A2-11 (baseline schema version marker verified; `init_db` records `schema_versions` baseline while preserving SQLModel `create_all`)
- [x] **A2-13** `ArtifactAsset` 모델 — Spec: SELF_HEALING_SPEC, DB_SCHEMA | Phase 1 | Layer: Worker | Depends: A2-03, A2-06 (baseline artifact asset model verified; `artifact_assets` stores source-linked artifact path/hash/metadata without DB blobs)
- [x] **A2-14** `SelectorCandidate` 모델 — Spec: SELF_HEALING_SPEC, DB_SCHEMA | Phase 1 | Layer: Worker | Depends: A2-04, A2-10 (baseline selector candidate model verified; `selector_candidates` stores raw action, optional POM method, artifact evidence, selector value, confidence, and metadata)
- [x] **A2-15** `HealingProposal` 모델 — Spec: SELF_HEALING_SPEC, DB_SCHEMA | Phase 2 | Layer: Worker | Depends: A2-13, A2-14 (baseline healing proposal model verified; `healing_proposals` stores target links, proposal values, confidence/status, evidence JSON, and timestamps)

### A3. Settings / Credential — §8

- [x] **A3-01** `settings.json` 스키마 — §8.1 | Phase 0 | Layer: Worker | Depends: A1-03 (baseline scaffold verified; AppSettings defaults create persisted settings.json and validate Webwright/generator/runner/integration sections)
- [x] **A3-02** executionMode 설정 UI + 저장 — §8.1 | Phase 0 | Layer: GUI | Depends: A3-01 (baseline scaffold verified; Settings UI exposes Native/WSL mode and save/reload persists through Worker settings API)
- [x] **A3-03** Electron keytar 연동 — §8.2 | Phase 0 | Layer: GUI | Depends: A1-02 (baseline scaffold verified; keytar-backed main IPC, preload helpers, renderer types, and wizard API key storage confirmed)
- [x] **A3-04** Settings CRUD API — §8 | Phase 0 | Layer: Worker | Depends: A3-01 (baseline scaffold verified; GET/PUT /settings validate AppSettings and persist settings.json)
- [x] **A3-05** Health check API — §8 | Phase 0 | Layer: Worker | Depends: A3-04 (baseline scaffold verified; /health and /settings/validate cover worker/settings/python/template/Webwright readiness)
- [x] **A3-06** Setup Wizard 7단계 — §10.1 | Phase 0 | Layer: GUI | Depends: A3-05, A4-02 (baseline scaffold verified; 7-step setup flow saves settings and runs health validation)

### A4. Electron ↔ Worker 통신 — §5.1, §5.2

- [x] **A4-01** Worker subprocess 자동 기동 — §5.2 | Phase 0 | Layer: GUI | Depends: A1-02, A1-03 (baseline scaffold verified; Electron-only dev reaches worker /)
- [x] **A4-02** HTTP API 클라이언트 (TanStack Query) — §5.2 | Phase 0 | Layer: GUI | Depends: A4-01 (baseline scaffold verified; initApiBase + DashboardPage useQuery projects)
- [x] **A4-03** WebSocket/SSE 로그 스트림 — §5.2 | Phase 0 | Layer: Worker, GUI | Depends: A4-01 (baseline scaffold verified; /ws/logs/{job_id}, buffered broadcast, and renderer connectLogStream confirmed)
- [x] **A4-04** CORS / localhost 바인딩 — §5.2 | Phase 0 | Layer: Worker | Depends: A1-03 (baseline scaffold verified; 127.0.0.1 bind + CORS allows localhost:5173)
- [x] **A4-05** Worker graceful shutdown — §5.2 | Phase 0 | Layer: GUI | Depends: A4-01 (baseline scaffold verified; Electron lifecycle stops worker subprocess with SIGTERM and fallback cleanup)

### A5. Project API — §7.1

- [x] **A5-01** `GET/POST /projects` — §7.1 | Phase 0 | Layer: Worker | Depends: A2-01 (baseline scaffold verified; list/create return §6.1 project fields)
- [x] **A5-02** `GET/PATCH/DELETE /projects/{id}` — §7.1 | Phase 0 | Layer: Worker | Depends: A5-01 (baseline scaffold verified; get, patch, delete, and missing-project 404 responses confirmed)

---

## B. Generated Automation Project 템플릿 (Phase 1 선행)

### B1. 디렉터리 / 설정 — §9.2

- [x] **B1-01** 디렉터리 구조 — §9.2 | Phase 1 | Layer: Template
- [x] **B1-02** requirements.txt, pytest.ini, README — §9.2 | Phase 1 | Layer: Template | Depends: B1-01
- [x] **B1-03** config env files + automation.yaml — §9.2 | Phase 1 | Layer: Template | Depends: B1-01
- [x] **B1-04** mappings/cases.yaml 스키마 — §9.3 | Phase 1 | Layer: Template | Depends: B1-01

### B2. Runner CLI — §9.4

- [x] **B2-01** runner/cli.py — run — §9.4 | Phase 1 | Layer: Template | Depends: B1-01
- [x] **B2-02** runner/cli.py — list-cases — §9.4 | Phase 1 | Layer: Template | Depends: B2-01
- [x] **B2-03** runner/cli.py — rerun-failed — §9.4 | Phase 1 | Layer: Template | Depends: B2-01
- [x] **B2-04** runner/cli.py — export — §9.4 | Phase 4 | Layer: Template | Depends: B2-01
- [x] **B2-05** mapping_loader.py, pytest_runner.py — §9.4 | Phase 1 | Layer: Template | Depends: B2-01
- [x] **B2-06** result_parser.py, result_writer.py — §5.13 | Phase 1 | Layer: Template | Depends: B2-05
- [x] **B2-07** CLI 단독 실행 E2E 검증 — §3.5 | Phase 1 | Layer: E2E | Depends: B2-06 (baseline standalone CLI E2E verified; `npm run e2e:cli-standalone` covers list-cases, run, rerun-failed, and excel export against a temporary generated project)
- [x] **B2-08** pytest runner artifact contract hardening — Spec: GENERATED_PROJECT_SPEC | Phase 2 | Layer: Template | Depends: B2-05, B3-04 (verified: runner now writes stdout/stderr logs, records pytest command/returnCode/log paths in `results.json`, maps deterministic screenshot/trace/video artifact paths, preserves env/headed/browser/base-url artifact env, and `python -m pytest tests/test_generated_template_fixture_policy.py tests/e2e/test_cli_standalone.py tests/test_generated_runtime.py tests/test_runtime.py tests/e2e/test_smoke.py -q` passed)

### B3. Page / Flow / Test 샘플 — §5.10

- [x] **B3-01** pages/base_page.py — §5.10 | Phase 1 | Layer: Template | Depends: B1-01
- [x] **B3-02** fixtures/browser_fixture.py, env_fixture.py — §9.2 | Phase 1 | Layer: Template | Depends: B1-01
- [x] **B3-03** 샘플 flow + test 1세트 — §5.10 | Phase 1 | Layer: Template | Depends: B3-01, B3-02
- [x] **B3-04** generated pytest fixture/browser policy — Spec: GENERATED_PROJECT_SPEC | Phase 2 | Layer: Template | Depends: B3-02 (verified: generated-template fixtures now provide env config, base_url, artifact_dir, headless/browser/context args, storage_state, viewport, trace/screenshot/video policy, runner env propagation, `conftest.py` pytest plugin registration, `TC_HEADLESS`, and `PLAYWRIGHT_BROWSERS_PATH` contract, and `python -m pytest tests/test_generated_template_fixture_policy.py tests/test_generated_runtime.py tests/test_runtime.py tests/e2e/test_smoke.py -q` passed)

### B4. Result Export Adapters — §5.14

- [x] **B4-01** testrail_clone_uploader.py — §5.14 | Phase 3 | Layer: Template | Depends: B2-06
- [x] **B4-02** testrail_uploader.py — §5.14 | Phase 4 | Layer: Template | Depends: B2-06
- [x] **B4-03** excel_writer.py — §5.14 | Phase 4 | Layer: Template | Depends: B2-06
- [x] **B4-04** google_sheets_writer.py — §5.14 | Phase 4 | Layer: Template | Depends: B2-06

---

## C. Worker 서비스 (FastAPI)

### C1. Case Import Service — §5.5

- [x] **C1-01** normalized TC Pydantic 모델 — §5.5 | Phase 1 | Layer: Worker | Depends: A2-02
- [x] **C1-02** Excel preview API — §7.2 | Phase 1 | Layer: Worker | Depends: C1-01
- [x] **C1-03** Excel import API — §7.2 | Phase 1 | Layer: Worker | Depends: C1-02
- [x] **C1-04** testrail-clone import adapter — §5.5 | Phase 3 | Layer: Worker | Depends: C1-01
- [x] **C1-05** TestRail import adapter — §5.5 | Phase 4 | Layer: Worker | Depends: C1-01
- [x] **C1-06** Google Sheets import adapter — §5.5 | Phase 4 | Layer: Worker | Depends: C1-01
- [x] **C1-07** GET/PATCH /cases — §7.2 | Phase 1 | Layer: Worker | Depends: C1-01

### C2. Prompt Builder — §5.6

- [x] **C2-01** TC → task prompt 템플릿 — §5.6 | Phase 1 | Layer: Worker | Depends: C1-01
- [x] **C2-02** startUrl, preconditions, steps 조합 — §5.6 | Phase 1 | Layer: Worker | Depends: C2-01
- [x] **C2-03** TC 의도 보존 검증 — §5.6 | Phase 1 | Layer: E2E | Depends: C2-02
- [x] **C2-04** batch-level shared prompt + per-case override 모델 — Spec: PRODUCT_PILLARS | Phase 1 | Layer: Worker | Depends: C2-02 (verified 2026-06-05: Worker stores project batch prompt and per-case overrides, rejects cross-project cases, appends effective context to Webwright prompts, and preserves no-context prompt behavior; `python -m pytest tests/test_prompt_context.py tests/test_webwright_adapter.py -q` passed)
- [x] **C2-05** prompt preset 모델(login/search/CRUD/assertion-heavy 등) — Spec: PRODUCT_PILLARS | Phase 1 | Layer: Worker | Depends: C2-04 (verified 2026-06-05: Worker persists stable built-in prompt presets plus project-scoped custom presets, exposes deterministic GET/PUT round-trip APIs, rejects cross-project/built-in collisions, and leaves existing prompt composition unaffected; `python -m pytest tests/test_prompt_presets.py tests/test_prompt_context.py tests/test_webwright_adapter.py -q` passed)
- [x] **C2-06** prompt preview API — Spec: API_SPEC, PRODUCT_PILLARS | Phase 1 | Layer: Worker | Depends: C2-05 (verified 2026-06-05: Worker previews the effective prompt for a project case, combining base TC prompt, optional built-in/project preset guidance, saved batch prompt, and per-case override in deterministic order; rejects foreign cases/presets without run/history mutation; `python -m pytest tests/test_prompt_preview.py tests/test_prompt_presets.py tests/test_prompt_context.py tests/test_webwright_adapter.py -q` passed)
- [x] **C2-07** Webwright prompt payload 저장/추적 — Spec: PRODUCT_PILLARS, DB_SCHEMA | Phase 1 | Layer: Worker | Depends: C2-06 (verified 2026-06-05: Webwright run creation records one immutable prompt payload row with final/base prompt, selected preset snapshot, batch/case context, environment, start URL, and effective model config; list/read APIs filter by project/case/run and preserve project isolation; `python -m pytest tests/test_prompt_payloads.py tests/test_prompt_preview.py tests/test_prompt_presets.py tests/test_prompt_context.py tests/test_webwright_adapter.py -q` passed)

### C3. Webwright CLI Adapter — §5.4

- [x] **C3-01** Webwright 경로 검증 — §5.4 | Phase 1 | Layer: Worker | Depends: A3-01
- [x] **C3-02** native subprocess 실행 — §5.4 | Phase 1 | Layer: Worker | Depends: C3-01
- [x] **C3-03** WSL subprocess 실행 — §5.4 | Phase 1 | Layer: Worker | Depends: C3-01
- [x] **C3-04** API key 환경변수 주입 — §5.4, §13 | Phase 1 | Layer: Worker | Depends: C3-02
- [x] **C3-05** artifact 수집 — §5.7 | Phase 1 | Layer: Worker | Depends: C3-02
- [x] **C3-06** error classification — §12.1 | Phase 5 | Layer: Worker | Depends: C3-05
- [x] **C3-07** live Webwright CLI readiness probe — Spec: RUNTIME_SPEC | Phase 1 | Layer: Worker | Depends: C3-01 (verified: health/run gate now uses root/python/config/CLI import readiness; placeholder `base.yaml` alone falls back to explicit mock mode; `python -m pytest tests/test_runtime.py tests/e2e/test_smoke.py -q` passed from `apps/worker`)
- [x] **C3-08** Webwright package source/version freeze — Spec: RUNTIME_SPEC | Phase 1 | Layer: Infra | Depends: C3-07 (verified: product/live `prepare-runtime` defaults to vendored `third_party/webwright` with MIT license/notice/version metadata; explicit external source/package override remains supported; `-WebwrightMode mock -ValidateOnly` passes; unpinned `-WebwrightPipPackage webwright -ValidateOnly` fails)

### C4. Webwright Run Service — §5.7

- [x] **C4-01** 1 TC = 1 Run — §5.7 | Phase 1 | Layer: Worker | Depends: C3-02
- [x] **C4-02** 상태 모델 — §5.7 | Phase 1 | Layer: Worker | Depends: A2-03
- [x] **C4-03** artifact 디렉터리 + metadata.json — §5.7 | Phase 1 | Layer: Worker | Depends: C4-01
- [x] **C4-04** API create/list/get/cancel/retry — §7.3 | Phase 1 | Layer: Worker | Depends: C4-03
- [x] **C4-05** Action Extraction 자동 트리거 — §11.2 | Phase 1 | Layer: Worker | Depends: C4-04, C5-04

### C5. Action Extraction Service — §5.8

- [x] **C5-01** 라인 기반 Playwright API 추출 — §5.8 | Phase 1 | Layer: Worker | Depends: C3-05
- [x] **C5-02** trajectory.json 보조 — §5.8 | Phase 1 | Layer: Worker | Depends: C5-01
- [x] **C5-03** action type enum 17종 — §5.8 | Phase 1 | Layer: Worker | Depends: C5-01 (verified 2026-06-04: line-based extraction covers the 17 core action types plus `set_input_files`/`drag_to`, preserves ordered selector/value/source metadata, supports sync/async wait contexts, and retains unsupported Playwright/expect calls as `custom_code`)
- [x] **C5-04** RawAction DB 저장 — §5.8 | Phase 1 | Layer: Worker | Depends: A2-04, C5-01
- [x] **C5-05** Python AST 고도화 — §5.8 | Phase 5 | Layer: Worker | Depends: C5-01 (verified 2026-06-05: action extraction now parses complete Python ASTs for multi-line, async/await, chained locator, simple locator alias, context-manager, and `expect(...).to_*` assertion shapes, preserves deterministic `RawAction` order/source/selector/value metadata, keeps unsupported Playwright calls as `custom_code`, and falls back to the legacy line parser for syntactically invalid scripts; `python -m pytest tests/test_action_extraction.py tests/test_webwright_adapter.py tests/test_raw_refresh_regeneration.py -q` passed)

### C6. Mapping & Review Service — §5.9

- [x] **C6-01** TC step ↔ action 자동 1:1 매핑 — §5.9 | Phase 1 | Layer: Worker | Depends: C5-04
- [x] **C6-02** needs_review 상태 — §5.9 | Phase 1 | Layer: Worker | Depends: C6-01
- [x] **C6-03** action CRUD — §5.9 | Phase 1 | Layer: Worker | Depends: C6-01 (verified 2026-06-05: project/case-scoped action create/update/delete APIs create reviewed actions on the selected case's latest run, reject foreign action mutations before partial writes, preserve ordered mapping joins and legacy first-action compatibility on delete, and feed updated action selectors/values into structure sync body plans; `python -m pytest tests/test_action_crud.py tests/test_raw_refresh_merge.py tests/test_structuring_planner.py -q` passed)
- [x] **C6-04** assertion/wait 추가 — §5.9 | Phase 1 | Layer: Worker | Depends: C6-03 (verified 2026-06-05: step-scoped review APIs insert and update supported assertion/wait actions on the selected case, place them in ordered mapping joins with `insertAfterActionId`, reject unsupported/foreign/unlinked mutations before partial writes, and preserve explicit assertion/wait entries in structure sync body plans; `python -m pytest tests/test_assertion_wait_actions.py tests/test_action_crud.py tests/test_raw_refresh_merge.py tests/test_structuring_planner.py -q` passed)
- [x] **C6-05** normalized step / POM method 이름 — §5.9 | Phase 1 | Layer: Worker | Depends: C6-03
- [x] **C6-06** Mapping API — §7.4 | Phase 1 | Layer: Worker | Depends: C6-01
- [x] **C6-07** TC step ↔ multiple raw actions join 저장 — Spec: DB_SCHEMA, STRUCTURING_SPEC | Phase 1 | Layer: Worker | Depends: A2-08, C6-06 (verified 2026-06-04: Mapping GET/PUT round-trips ordered `action_ids`, atomically replaces/removes join rows, aligns legacy `raw_action_id`, and rejects invalid/foreign action IDs before mutation; focused mapping tests passed)

### C7. Structuring Service — §5.10

- [x] **C7-01** Reviewed action → Normalized Flow — §5.10 | Phase 1 | Layer: Worker | Depends: C6-06
- [x] **C7-02** Page Object method 생성 — §5.10 | Phase 1 | Layer: Worker | Depends: C7-01
- [x] **C7-03** Flow function 생성 — §5.10 | Phase 1 | Layer: Worker | Depends: C7-02
- [x] **C7-04** Test function 생성 — §5.10 | Phase 1 | Layer: Worker | Depends: C7-03
- [x] **C7-05** coding convention 적용 — §5.10 | Phase 1 | Layer: Worker | Depends: C7-04
- [x] **C7-06** `StructuredFlow` DB persistence — Spec: STRUCTURING_SPEC, DB_SCHEMA | Phase 1 | Layer: Worker | Depends: A2-09, C7-01 (runtime+structuring pass: structured flow persisted via `structuring_service.sync_structured_entities`)
- [x] **C7-07** `StructuredStep` DB persistence — Spec: STRUCTURING_SPEC, DB_SCHEMA | Phase 1 | Layer: Worker | Depends: C7-06 (runtime+structuring pass: ordered structured steps persisted from reviewed mappings)
- [x] **C7-08** `PageObjectMethod` plan persistence — Spec: STRUCTURING_SPEC, DB_SCHEMA | Phase 1 | Layer: Worker | Depends: A2-10, C7-07 (runtime+structuring pass: method plans/body json persisted and linked to steps)
- [x] **C7-09** structure validation API — Spec: STRUCTURING_SPEC, API_SPEC | Phase 1 | Layer: Worker | Depends: C7-08 (runtime+structuring pass: `/projects/{project_id}/cases/{case_id}/structure/validate`)
- [x] **C7-10** stale/conflict detection for regeneration — Spec: STRUCTURING_SPEC, DB_SCHEMA | Phase 2 | Layer: Worker | Depends: C7-09 (verified 2026-06-05: generated-file status refresh compares stored `content_hash` with current on-disk hashes, marks edited files, preflights planned incremental content to mark stale or conflict, blocks source-changed edited files before overwrite, and surfaces generated-file issues through structure validation and generated-file metadata; focused and related generation/maintenance tests passed)
- [x] **C7-11** structured method body planner coverage — Spec: STRUCTURING_SPEC | Phase 2 | Layer: Worker | Depends: C5-03, C6-07, C7-08 (verified 2026-06-04: structuring compiles ordered multi-run/multi-action mappings into deterministic traceable body plans, preserves assertion/wait/select/check/upload selectors and value templates, refreshes existing POM plans, and forces review for unsupported/missing actions and hard waits; focused and related tests passed)
- [x] **C7-12** selected raw refresh merge into existing structure — Spec: STRUCTURING_SPEC, SELF_HEALING_SPEC | Phase 2 | Layer: Worker | Depends: C7-11, C8-07 (verified 2026-06-05: selected Webwright reruns conservatively match equivalent replacement actions, preserve reviewed mapping/flow/step/POM identities, names, order, and unrelated cases, remap raw-action links and refresh safe body plans in place, and mark count/order/ambiguity/shared-method conflicts as `needs_review`; focused and related structuring/traceability tests passed)

### C8. Project Generator Service — §5.11

- [x] **C8-01** template 기반 파일 생성 — §5.11 | Phase 1 | Layer: Worker | Depends: C7-05, B1-01
- [x] **C8-02** generated file metadata DB — §5.11 | Phase 1 | Layer: Worker | Depends: C8-01
- [x] **C8-03** Generation API — §7.5 | Phase 1 | Layer: Worker | Depends: C8-01
- [x] **C8-04** Git repo 가능 출력 — §5.11 | Phase 1 | Layer: Worker | Depends: C8-01 (verified 2026-06-05: generation writes deterministic Git-ready `.gitignore`, keeps `artifacts/runs/.gitkeep`, excludes template caches/stale artifacts, and preserves existing `.git`, `.gitattributes`, and `.gitmodules` metadata across full and selected generation; `python -m pytest tests/test_regeneration_guard.py tests/test_incremental_generation.py tests/test_generated_file_origins.py tests/test_generated_file_status.py tests/test_retire_cleanup.py -q` passed)
- [x] **C8-05** generated file origin/hash/status tracking — Spec: DB_SCHEMA | Phase 1 | Layer: Worker | Depends: A2-11, C8-02 (runtime+structuring pass: source_type/source_id/content_hash/status written on generation)
- [x] **C8-06** deterministic regeneration + conflict guard — Spec: STRUCTURING_SPEC | Phase 2 | Layer: Worker | Depends: C8-05, C7-10 (verified 2026-06-05: full and selected generation preflight tracked files before rewrite/delete, use C7-10 edited/stale/conflict state to stop with deterministic 409 conflict summaries, preserve files before any blocked write/delete, and report byte-stable unchanged full regeneration; focused and related generation/maintenance tests passed)
- [x] **C8-07** `GeneratedFileOrigin` link persistence — Spec: STRUCTURING_SPEC, DB_SCHEMA | Phase 2 | Layer: Worker | Depends: C8-05, C7-11 (verified 2026-06-05: generation upserts one metadata row per project/path after writing files, persists complete case/flow/step/POM/page/mapping/raw/run origin links, aggregates shared-file origins, and replaces stale origins and duplicate metadata rows; focused and related traceability tests passed)
- [x] **C8-08** generated-project runtime manifest — Spec: GENERATED_PROJECT_SPEC, RUNTIME_SPEC | Phase 2 | Layer: Worker | Depends: C8-03, B3-04 (verified 2026-06-05: generation writes deterministic `config/runtime-manifest.json` with requirements, Python/runtime defaults, Playwright browser/cache expectations, fixture policy, and standalone/Studio commands; tracks the manifest as generated metadata, keeps selected regeneration stable unless runtime inputs change, and blocks edited manifests before overwrite; `python -m pytest tests/test_regeneration_guard.py tests/test_generated_file_origins.py tests/test_incremental_generation.py -q` passed)
- [x] **C8-09** selected TC incremental regeneration — Spec: STRUCTURING_SPEC, API_SPEC | Phase 2 | Layer: Worker | Depends: C8-06, C8-07, C7-12 (verified 2026-06-05: selected `caseIds` default to incremental generation, reuse merged structured flows, rewrite selected tests/flows plus origin-linked shared page/mapping files, merge `cases.yaml`, replace origins only for rewritten files, preserve unrelated generated/runtime/artifact files and metadata, stop on `needs_review`, and return deterministic affected/changed/preserved summaries; focused Worker/API, origin, and structuring tests passed)
- [x] **C8-10** TC retire/delete generated artifact cleanup — Spec: STRUCTURING_SPEC, API_SPEC | Phase 2 | Layer: Worker | Depends: C8-07, C8-09 (verified 2026-06-05: explicit human-confirmed soft retire/delete preflights impacted file status/hash/origins, removes selected private test/flow files, marks metadata obsolete while preserving audit origins, rebuilds shared page/mapping files from active cases, preserves shared methods and unrelated content/history, and stops without cleanup on edited or unproven shared conflicts; focused and related generation/origin tests passed)

### C9. Project Runner Service — §5.13

- [x] **C9-01** runner.cli subprocess 호출 — §5.13 | Phase 1 | Layer: Worker | Depends: B2-01
- [x] **C9-02** env/browser/headless/target 전달 — §5.13 | Phase 1 | Layer: Worker | Depends: C9-01
- [x] **C9-03** stdout/stderr WebSocket — §5.13 | Phase 1 | Layer: Worker | Depends: A4-03, C9-01
- [x] **C9-04** results.json 파싱 — §5.13 | Phase 1 | Layer: Worker | Depends: C9-01, A2-06
- [x] **C9-05** Runner API — §7.6 | Phase 1 | Layer: Worker | Depends: C9-04
- [x] **C9-06** generated runtime bootstrap fail-fast — Spec: RUNTIME_SPEC, GENERATED_PROJECT_SPEC | Phase 1 | Layer: Worker | Depends: C9-01, B1-02 (verified: bootstrap failure now stops before `runner.cli`, writes stdout/stderr/results artifacts, returns actionable bootstrap status/logs, and `python -m pytest tests/test_generated_runtime.py tests/test_runtime.py tests/e2e/test_smoke.py -q` passed)
- [x] **C9-07** per-project runtime install state/cache — Spec: RUNTIME_SPEC | Phase 2 | Layer: Worker | Depends: C9-06 (verified 2026-06-05: generated runtime bootstrap stores successful per-project readiness by generated project path/hash, requirements hash, runtime manifest hash, RuntimeProfile hash, Python path, browser, and browser cache; cache hits skip redundant pip/Playwright install commands while still verifying the browser executable; stale requirements/runtime/profile/browser inputs rerun bootstrap; failed installs are not cached as ready; `python -m pytest tests/test_generated_runtime_cache.py tests/test_generated_runtime.py -q` passed)

### C10. Result Export Service — §5.14

- [x] **C10-01** testrail-clone bulk upload — §5.14 | Phase 3 | Layer: Worker | Depends: C9-04
- [x] **C10-02** TestRail result update — §5.14 | Phase 4 | Layer: Worker | Depends: C9-04
- [x] **C10-03** Excel write-back — §5.14 | Phase 4 | Layer: Worker | Depends: C9-04
- [x] **C10-04** Google Sheets update — §5.14 | Phase 4 | Layer: Worker | Depends: C9-04
- [x] **C10-05** export preview + 이중 검증 — §17.3 | Phase 4 | Layer: Worker | Depends: C10-01 (verified 2026-06-05: preview returns deterministic target payloads plus validation without external/file/ExportLog mutation; non-preview export rejects missing, duplicate, or mismatched results/ExecutionResult/mappings identity rows before target mutation; `python -m pytest tests/test_result_export_validation.py tests/e2e/test_export.py -q` passed)
- [x] **C10-06** Export API — §7.7 | Phase 3-4 | Layer: Worker | Depends: C10-01

### C11. Project IDE Service — §5.12

- [x] **C11-01** 파일 트리 API — §7.5 | Phase 2 | Layer: Worker | Depends: C8-03
- [x] **C11-02** 파일 CRUD API — §7.5 | Phase 2 | Layer: Worker | Depends: C11-01
- [x] **C11-03** automationKey/selector 검색 — §5.12 | Phase 2 | Layer: Worker | Depends: C11-01

### C12. Artifact-backed Self-Healing Service — Spec: SELF_HEALING_SPEC

- [x] **C12-01** Webwright logs/screenshots/trajectory artifact indexing — Spec: SELF_HEALING_SPEC | Phase 1 | Layer: Worker | Depends: C3-05, A2-13 (baseline Webwright artifact indexing verified; final script, trajectory, logs, metadata, and screenshots are indexed as `ArtifactAsset` rows)
- [x] **C12-02** raw action selector candidate extraction — Spec: SELF_HEALING_SPEC | Phase 1 | Layer: Worker | Depends: C5-04, A2-14 (baseline raw-action selector candidate extraction verified; role/text/test-id/css/xpath candidates persist from `RawAction.selector` with artifact evidence links)
- [x] **C12-03** execution failure artifact indexing — Spec: SELF_HEALING_SPEC | Phase 2 | Layer: Worker | Depends: C9-04, A2-13 (baseline execution failure artifact indexing verified; failed execution results and run logs/results are indexed as `ArtifactAsset` rows)
- [x] **C12-04** failure → structured step/POM method link resolver — Spec: SELF_HEALING_SPEC | Phase 2 | Layer: Worker | Depends: C7-08, C12-03 (verified 2026-06-04: read-only resolver follows the latest generated-file/origin links through flow/step/POM, returns mapping/raw-action/artifact evidence IDs, and covers deterministic resolved/missing/ambiguous outcomes)
- [x] **C12-05** healing proposal generation API — Spec: SELF_HEALING_SPEC, API_SPEC | Phase 2 | Layer: Worker | Depends: A2-15, C12-04 (verified 2026-06-05: execution-scoped proposal API reuses resolved selector_changed diagnosis, persists selector_replace proposals with target result/POM/step links, old/new selector values, confidence, and evidence JSON, returns existing rows on duplicate requests, exposes list/detail APIs, and leaves non-selector or unresolved diagnoses proposal-free; focused and related diagnosis/selector/model tests passed)
- [x] **C12-06** accepted proposal apply/regenerate/rerun flow — Spec: SELF_HEALING_SPEC, API_SPEC | Phase 2 | Layer: Worker | Depends: C12-05, C8-06, C9-05 (verified 2026-06-05: accept/reject endpoints preserve proposal evidence and enforce safe idempotent status transitions; accepted selector_replace apply patches the targeted POM selector/body plan, invokes guarded selected incremental generation, returns proposal/mutation/generation/rerun context, rejects non-accepted/rejected proposals, and blocks edited/conflict generated files before persisted mutation or rewrite; focused and related proposal/generation guard tests plus npm build passed)
- [x] **C12-07** safe auto-apply guardrails — Spec: SELF_HEALING_SPEC | Phase 3 | Layer: Worker | Depends: C12-06 (verified 2026-06-05: selector proposal creation remains review-only by default, project-enabled auto-apply requires selector-not-found/strict evidence, exactly one high-confidence candidate, semantic and stale-target guards, and reuses the accepted apply/regeneration path; low-confidence, ambiguous, stale, or conflict-blocked cases return concrete blocked reasons without selector/file mutation; focused and related diagnosis/target/model tests passed)
- [x] **C12-08** failure disposition classifier — Spec: SELF_HEALING_SPEC, API_SPEC | Phase 2 | Layer: Worker | Depends: C12-04, C12-03 (verified 2026-06-04: read-only execution diagnosis endpoint classifies each failed result as `selector_changed`, `raw_refresh_required`, `feature_removed_retire_tc`, or conservative `unknown`, returning reason/confidence/evidence/target context without applying maintenance actions)
- [x] **C12-09** selected TC Webwright refresh regeneration flow — Spec: SELF_HEALING_SPEC, WORKFLOW_SPEC, API_SPEC | Phase 2 | Layer: Worker | Depends: C4-04, C7-12, C8-09 (verified 2026-06-05: the selected-case maintenance API returns traceable run/merge/generation outcomes, preserves prior raw evidence and unrelated structured/generated cases, incrementally regenerates only after a safe raw merge, and stops without generated-file rewrites on review-required changes; focused and related raw refresh/generation tests passed)
- [x] **C12-10** TC retire recommendation and cleanup flow — Spec: SELF_HEALING_SPEC, STRUCTURING_SPEC, API_SPEC | Phase 2 | Layer: Worker | Depends: C12-08, C8-10 (verified 2026-06-05: a diagnosis-bound execution-result endpoint requires explicit confirmation, reclassifies the failed result, verifies resolved project/execution/automation-key/source/sole-TC identity before invoking C8-10, rejects unresolved/non-feature/mismatched/unconfirmed requests without mutation, and returns diagnosis reason/confidence/evidence with deterministic cleanup details; focused disposition/cleanup/diagnosis tests passed)

---

## D. GUI 작업공간 (Electron + React)

Product workspace alignment: [PRODUCT_PILLARS.md](./PRODUCT_PILLARS.md). GUI checklist items belong to **Generate Raw**, **Automation IDE**, or **supporting** shell—not a flat tab list.

| Workspace | Checklist sections | Primary surfaces |
|-----------|-------------------|------------------|
| **Generate Raw** | D3, D4 | Import, Cases, Prompt/LLM, Webwright, Raw Artifacts |
| **Automation IDE** | D5, D6, D7*, D8* | Mapping, Structure, IDE, Runner/Results/Export panels |
| **Supporting** | D1, D2, D9 | 2-workspace shell, Setup Wizard (first run), Settings (post-setup re-edit) |

\* D7/D8 are **embedded panels** inside Automation IDE, not peer product workspaces.

### D1. 공통 / Shell — Workspace: supporting + cross-workspace

- [x] **D1-01** 2-workspace shell (`Generate Raw`, `Automation IDE`) — Spec: PRODUCT_PILLARS, UI_UX_DIRECTION | Phase 0-1 | Layer: GUI | Depends: A1-02 (baseline shell verified; workspace switcher + grouped nav)
- [x] **D1-02** Zustand 전역 상태 — §5.1 | Phase 0 | Layer: GUI | Depends: A1-02 (baseline scaffold verified; setup flag, persisted current project, and capped log buffer shared through store)
- [x] **D1-03** Cursor-like layout/activity bar/context/log panels — Spec: UI_UX_DIRECTION | Phase 0 | Layer: GUI | Depends: D1-01 (baseline shell panels verified; activity bar, secondary nav, context panel, and bottom logs frame)
- [x] **D1-04** Project Dashboard — §10.2 | Phase 0 | Layer: GUI | Depends: A5-01 (baseline dashboard verified; project list/create/select, summary counts, quick links, and recent executions)
- [x] **D1-05** selected TC/workspace handoff state — Spec: PRODUCT_PILLARS | Phase 1 | Layer: GUI | Depends: D1-02, D3-03 (baseline TC/workspace handoff verified; persisted selectedCase in Zustand/localStorage, project switch clears stale selection, Cases/Webwright/Mapping/Runner/Layout read shared handoff state across workspaces)
- [x] **D1-06** Generate Raw rerun handoff (W2→W1) — Spec: PRODUCT_PILLARS, WORKFLOW_SPEC | Phase 1 | Layer: GUI | Depends: D1-05, D4-02 (baseline rerun handoff preserves selected TC from Mapping/IDE into Generate Raw)

### D2. Setup Wizard — §10.1 — Workspace: supporting

First-run onboarding only. Values persist to `settings.json` / keytar; **post-setup re-edit is D9-02**, not a second wizard run unless user chooses D9-03.

- [x] **D2-01** Webwright Root 선택 — §10.1 | Phase 0 | Layer: GUI | Depends: A3-06 (baseline root selection verified; directory picker and settings persistence on step advance)
- [x] **D2-02** Python venv 선택 — §10.1 | Phase 0 | Layer: GUI | Depends: D2-01 (baseline Python selection verified; path input/directory picker and settings persistence on step advance)
- [x] **D2-03** API Provider + Key — §10.1 | Phase 0 | Layer: GUI | Depends: A3-03 (baseline provider/key storage verified; provider persists to settings and key saves through keytar IPC on step advance)
- [x] **D2-04** Playwright browser 확인 — §10.1 | Phase 0 | Layer: GUI | Depends: A3-05 (baseline browser check verified; settings validation reports Playwright package/browser readiness and wizard renders browser status)
- [x] **D2-05** Smoke Test — §10.1 | Phase 0 | Layer: GUI | Depends: D2-04 (baseline smoke test verified; validation path runs from wizard and renders pass/fail summary)
- [x] **D2-06** 프로젝트 경로 설정 — §10.1 | Phase 0 | Layer: GUI | Depends: D2-05 (baseline project path verified; directory picker, text input, and settings persistence on step advance)
- [x] **D2-07** Wizard 완료 + 저장 — §10.1 | Phase 0 | Layer: GUI | Depends: D2-06 (baseline wizard finish verified; Finish saves settings, persists setupComplete, and opens main shell)

### D3. TC Import / List — §10.3 — Workspace: Generate Raw

- [x] **D3-01** source type 선택 — §10.3 | Phase 1 | Layer: GUI | Depends: C1-02 (baseline source type selector verified; Excel, testrail-clone, TestRail, Google Sheets drive distinct import panels)
- [x] **D3-02** Excel import UI — §10.3 | Phase 1 | Layer: GUI | Depends: C1-03 (baseline Excel import UI verified; file picker, sheet name, column mapping, preview table, import summary, and cases query invalidation)
- [x] **D3-03** TC List — §10.3 | Phase 1 | Layer: GUI | Depends: C1-07 (baseline TC list verified; searchable/filterable table, case detail panel, and start URL/status quick edit)
- [x] **D3-04** source connector preview/config UI — Spec: PRODUCT_PILLARS, SCREEN_INVENTORY | Phase 3-4 | Layer: GUI | Depends: C1-04 (baseline source connector UI verified; testrail-clone/TestRail/Google Sheets config panels, integration status from Settings, and connector preview tables wired to Worker import APIs)

### D4. Webwright Generate — §10.4 — Workspace: Generate Raw

- [x] **D4-01** TC별 status 테이블 — §10.4 | Phase 1 | Layer: GUI | Depends: C4-04 (baseline TC status table verified; cases and latest Webwright runs render per-TC lifecycle status)
- [x] **D4-02** Run/Stop/Retry — §10.4 | Phase 1 | Layer: GUI | Depends: D4-01 (baseline run controls verified; selected/individual run, stop/cancel, retry, log stream, and query refresh wired)
- [x] **D4-03** raw script/log/folder — §10.4 | Phase 1 | Layer: GUI | Depends: D4-01 (baseline raw artifact links verified; folder, final script, trajectory, stdout, and stderr open from latest run data)
- [x] **D4-04** LLM provider/API key 입력 + 검증 UI — Spec: PRODUCT_PILLARS, UI_UX_DIRECTION | Phase 1 | Layer: GUI | Depends: A3-03, A3-05 (baseline Generate Raw LLM provider/key panel verified; provider saves to settings, key saves through keytar, and key presence check runs before raw generation)
- [x] **D4-05** prompt composer(batch shared + per-case override) — Spec: PRODUCT_PILLARS | Phase 1 | Layer: GUI | Depends: C2-04 (baseline Generate Raw prompt composer verified; batch prompt and selected-case override persist through settings)
- [x] **D4-06** prompt preset selector + prompt preview — Spec: PRODUCT_PILLARS, API_SPEC | Phase 1 | Layer: GUI | Depends: C2-06 (baseline local preset selector and prompt preview verified; preview combines selected TC, preset guidance, batch prompt, and case override)

### D5. Automation IDE: Mapping & Structure — §10.5 — Workspace: Automation IDE

- [x] **D5-01** 3-pane layout — §10.5 | Phase 1 | Layer: GUI | Depends: C6-06 (baseline Automation IDE 3-pane layout verified; TC context, raw actions, and normalized mapping panes preserve selected TC context)
- [x] **D5-02** raw code/screenshot/logs — §10.5 | Phase 1 | Layer: GUI | Depends: D5-01 (baseline raw evidence links verified in Mapping & Structure; latest run exposes folder, script, trajectory, stdout, stderr, and screenshot folder access)
- [x] **D5-03** mapping 편집 UX — §10.5 | Phase 1 | Layer: GUI | Depends: D5-01 (baseline mapping edit UX verified; per-step raw action, normalized step name, and status edits save through the existing mappings API)
- [x] **D5-04** normalized flow editor — Spec: STRUCTURING_SPEC, SCREEN_INVENTORY | Phase 1 | Layer: GUI | Depends: C7-06 (baseline flow editor verified; ordered normalized steps are editable from current mapping data and save through existing mappings API)
- [x] **D5-05** Page Object method planner — Spec: STRUCTURING_SPEC, SCREEN_INVENTORY | Phase 1 | Layer: GUI | Depends: C7-08 (baseline Page Object method planner verified; per-step POM method names are editable and saved through existing mappings API)
- [x] **D5-06** structure validation/stale/conflict panel — Spec: STRUCTURING_SPEC | Phase 2 | Layer: GUI | Depends: C7-09 (verified 2026-06-06: Mapping draft validation plus Automation IDE generation conflict UX now parse Worker 409 edited/stale/conflict summaries, show recovery guidance, support preview/apply selected regeneration, and surface conflicts from guarded maintenance actions; `npm run build` passed)
- [x] **D5-07** selector candidate/evidence viewer — Spec: SELF_HEALING_SPEC | Phase 2 | Layer: GUI | Depends: C12-02 (baseline selector evidence viewer verified; Mapping pane derives selector candidates from raw actions and links artifact evidence from latest Webwright run)

### D6. Automation IDE: Project Editing — §10.6 — Workspace: Automation IDE

- [x] **D6-01** 파일 트리 — §10.6 | Phase 2 | Layer: GUI | Depends: C11-01 (baseline generated file tree verified; generated-files API renders nested folders/files with expansion and selected file state)
- [x] **D6-02** Monaco Editor — §10.6 | Phase 2 | Layer: GUI | Depends: C11-02 (baseline Monaco editor verified; language mode, loading state, dirty/saved state, and save affordance are visible and wired to generated file content APIs)
- [x] **D6-03** Context Panel — §10.6 | Phase 2 | Layer: GUI | Depends: D6-01 (baseline Project IDE context panel verified; project, selected TC, selected file, editor state, and search results stay tied to current IDE selection)
- [x] **D6-04** xterm.js 터미널 — §10.6 | Phase 2 | Layer: GUI | Depends: C9-03 (baseline Project IDE terminal verified; xterm instance persists and appends new log store entries without recreating on each log update)
- [x] **D6-05** Run Current/Linked TC — §10.6 | Phase 2 | Layer: GUI | Depends: C9-05 (baseline IDE run controls verified; linked TC and all-run actions call existing execution API and stream logs to terminal)
- [x] **D6-06** trace/screenshot viewer — §10.6 | Phase 2 | Layer: GUI | Depends: D6-05 (baseline Project IDE artifact affordances verified; latest execution detail exposes results.json, selected-TC screenshot, and trace links via existing open-path behavior)
- [x] **D6-07** runner/results/export panels embedded in Automation IDE — Spec: PRODUCT_PILLARS | Phase 2 | Layer: GUI | Depends: D6-05, D8-01 (baseline Automation IDE panels verified; Project IDE embeds runner options, execution results, and export preview/export controls using existing APIs)
- [x] **D6-08** failure diagnosis + healing proposal panel — Spec: SELF_HEALING_SPEC | Phase 2 | Layer: GUI | Depends: C12-05, D6-06 (baseline read-only diagnosis panel verified; Automation IDE surfaces failed execution rows, error text, screenshot/trace evidence links, and local proposal guidance without new healing APIs)
- [x] **D6-09** failure disposition action panel — Spec: SELF_HEALING_SPEC, WORKFLOW_SPEC | Phase 2 | Layer: GUI | Depends: C12-08, D6-08 (verified 2026-06-06: Automation IDE diagnosis now consumes Worker disposition results, shows evidence/confidence/target context, wires selector proposal create/accept-apply/reject, selected raw refresh/regenerate, diagnosis-bound retire/delete with explicit confirmation, and manual-only unknown handling to existing APIs; `npm run build` and `python -m pytest tests/test_healing_proposals.py tests/test_retire_disposition.py tests/test_raw_refresh_regeneration.py -q` passed)
- [x] **D6-10** selected TC regeneration/retire diff review UI — Spec: STRUCTURING_SPEC, SELF_HEALING_SPEC | Phase 2 | Layer: GUI | Depends: C8-09, C8-10, C12-09, C12-10 (verified 2026-06-02: Worker preview endpoints for selected regeneration, raw refresh regeneration, and diagnosis-bound retire cleanup; Automation IDE diagnosis panel shows MaintenanceImpactReview with affected/preserved/changed/removed/conflict summaries before apply; `npm run build` and retire preview pytest passed)

### D7. Automation IDE — Runner Panel (embedded) — §10.7

- [x] **D7-01** 실행 옵션 UI — §10.7 | Phase 1 | Layer: GUI | Depends: C9-05 (baseline runner option UI verified; Runner page and embedded IDE runner expose env, browser, headed/headless, target mode, case IDs, automation key, and result target using the existing execution request shape)
- [x] **D7-02** 실시간 로그 — §10.7 | Phase 1 | Layer: GUI | Depends: A4-03 (baseline live runner logs verified; WebSocket stream feeds shared log store with auto-scroll panel in Runner and shell log dock on IDE/Webwright routes)

### D8. Automation IDE — Results & Export (embedded) — §10.8

- [x] **D8-01** summary + case table — §10.8 | Phase 1 | Layer: GUI | Depends: C9-04
- [x] **D8-02** artifact 링크 — §10.8 | Phase 1 | Layer: GUI | Depends: D8-01
- [x] **D8-03** Result Export + preview — §10.8 | Phase 3-4 | Layer: GUI | Depends: C10-06
- [x] **D8-04** accept/reject healing proposal + rerun failed UI — Spec: SELF_HEALING_SPEC | Phase 2 | Layer: GUI | Depends: D6-08, C12-06 (baseline healing accept/reject verified; Diagnosis panel records proposal decisions and reruns failed cases via /rerun-failed with log stream)

### D9. Settings — §10 — Workspace: supporting

Persistent settings surface after Setup Wizard. Same fields as D2 must remain editable here (not one-time only).

- [x] **D9-01** integrations/webwright/LLM/runner UI — §10 | Phase 0 | Layer: GUI | Depends: A3-04 (baseline settings sections verified; structured webwright/LLM, generator, runner, integrations fields plus advanced JSON editor and PUT save)
- [x] **D9-02** post-setup re-edit (D2 field parity: Webwright root, Python, API provider/key, project root, execution mode) + `/settings/validate` — §10.1, Spec: SCREEN_INVENTORY | Phase 0 | Layer: GUI | Depends: D2-07, D9-01, A3-05 (baseline D2 field parity verified; structured re-edit fields, keytar save on Save, and Validate Settings via /settings/validate)
- [x] **D9-03** Settings에서 Setup Wizard 재실행 (선택, `setupComplete` 유지) — §10.1 | Phase 0 | Layer: GUI | Depends: D9-02, A3-06 (baseline wizard re-run verified; Settings action opens rerun mode, Finish/Cancel return to main shell without resetting setupComplete)

---

## E. 실행 시퀀스 E2E — §11

- [x] **E-01** TC Import E2E — §11.1 | Phase 1 | Layer: E2E | Depends: D3-02 (baseline TC import E2E verified; pytest covers Excel preview/import/list handoff plus TestRail and testrail-clone connector preview paths; live script at scripts/e2e_tc_import.py)
- [x] **E-02** Generate Raw workspace E2E — §11.2 | Phase 1 | Layer: E2E | Depends: D4-02, D4-04, D4-06 (baseline Generate Raw E2E verified; pytest covers TC selection, Webwright run queue/completion, raw actions/mappings/artifacts, buffered log stream, and retry handoff; live script at scripts/e2e_generate_raw.py)
- [x] **E-03** Automation IDE structure E2E — §11.3 | Phase 1 | Layer: E2E | Depends: D5-03, D5-05 (baseline Automation IDE structure E2E verified; pytest covers Generate Raw handoff into selected TC actions/mappings, editable normalized flow names, Page Object method planning, action update save, and reload persistence; live script at scripts/e2e_structure.py)
- [x] **E-04** Project Generation E2E — §11.4 | Phase 1 | Layer: E2E | Depends: C8-03 (baseline Project Generation E2E verified; pytest covers reviewed mappings to generated project path, mappings/pages/flows/tests/fixtures/runner files, generated content traceable by automation_key, case generated status, and GeneratedFile metadata; live script at scripts/e2e_generation.py)
- [x] **E-05** Automation IDE runner E2E — §11.5 | Phase 1 | Layer: E2E | Depends: D6-07, D7-02 (baseline Automation IDE runner E2E verified; pytest covers generated project execution request, runner options, buffered log stream, execution status/result_path, result summary, and ExecutionResult rows traceable by automation_key; live script at scripts/e2e_runner.py)
- [x] **E-06** Result Export E2E — §11.6 | Phase 3-4 | Layer: E2E | Depends: D8-03 (baseline Result Export E2E verified; pytest covers execution results to Excel preview updates, local Excel write-back using a temp workbook, and ExportLog persistence without external services; live script at scripts/e2e_export.py)
- [x] **E-07** Reverse handoff rerun E2E (Automation IDE → Generate Raw) — Spec: PRODUCT_PILLARS, WORKFLOW_SPEC | Phase 1 | Layer: E2E | Depends: D1-06, E-02 (baseline reverse handoff rerun E2E verified; pytest covers selected TC/project context, Automation IDE mapping gap, Generate Raw retry via existing Webwright API, second Webwright run, refreshed raw actions/mappings visible back in Mapping, and retry log stream; live script at scripts/e2e_reverse_handoff.py)
- [x] **E-08** Self-healing proposal E2E — Spec: SELF_HEALING_SPEC | Phase 2 | Layer: E2E | Depends: D8-04, C12-06 (baseline self-healing proposal E2E verified; pytest covers failed execution/result context, local proposal accept/reject state, rerun-failed action, rerun log stream, and persisted rerun result rows without persistent C12 healing APIs; live script at scripts/e2e_self_healing.py)
- [x] **E-09** live Webwright runtime E2E — Spec: RUNTIME_SPEC | Phase 1 | Layer: E2E | Depends: C3-07, C3-08 (verified 2026-06-03: `python -m pytest tests\e2e\test_live_webwright_runtime.py -q` passed with real Webwright source/venv, OpenAI `gpt-5-mini`, Git Bash shell readiness, no mock mode, harvested nested `final_script.py`, RawAction rows, and indexed artifacts; source is now vendored under `third_party/webwright`)
- [x] **E-10** generated pytest/browser contract E2E — Spec: GENERATED_PROJECT_SPEC | Phase 2 | Layer: E2E | Depends: B2-08, B3-04, C9-06 (verified 2026-06-03: `python -m pytest tests\e2e\test_generated_browser_contract.py -q` passed with Worker `run_project` -> `runner.cli` -> pytest-playwright local Chromium, exercising `page`/`context`/`base_url`/env/artifact fixtures, preserving pytest stdout/stderr, mapping `[chromium]` screenshot/trace artifacts into results and DB rows; `python -m pytest tests\test_generated_template_fixture_policy.py tests\e2e\test_cli_standalone.py tests\test_generated_runtime.py -q` also passed)
- [x] **E-11** selected TC Webwright refresh incremental regeneration E2E — Spec: WORKFLOW_SPEC, STRUCTURING_SPEC, SELF_HEALING_SPEC | Phase 2 | Layer: E2E | Depends: C7-12, C12-09, C8-09, D6-09 (verified 2026-06-06: `python -m pytest tests/e2e/test_raw_refresh_regeneration.py -q` passed with three structured/generated cases, refresh preview plus selected `refresh-webwright-and-regenerate`, safe raw merge, incremental regeneration, preserved peer tests/flows/artifacts, and updated selected-case origins only)
- [x] **E-12** feature-removed TC retire cleanup E2E — Spec: WORKFLOW_SPEC, STRUCTURING_SPEC, SELF_HEALING_SPEC | Phase 2 | Layer: E2E | Depends: C12-10, C8-10, D6-10 (verified 2026-06-06: `python -m pytest tests/e2e/test_retire_cleanup.py -q` passed with three structured/generated cases, execution diagnosis `feature_removed_retire_tc`, retire preview plus confirmed diagnosis-bound retire, selected artifact cleanup, and preserved peer tests/flows/artifacts/history)

---

## F. 오류 처리 — §12

- [x] **F-01** Webwright 실행 오류 UX — §12.1 | Phase 5 | Layer: GUI | Depends: C3-06 (verified 2026-06-06: Generate Raw Webwright Runs and Mapping artifact evidence now map Worker `error_message` categories to actionable titles, recovery steps, retry/run-folder/stderr actions, and preserve run/log/history behavior; `npm run build` passed)
- [x] **F-02** Mapping 오류 UX — §12.2 | Phase 1 | Layer: GUI | Depends: C6-02 (verified 2026-06-05: Desktop API client now preserves FastAPI/Pydantic `detail` messages, Mapping Review surfaces Auto Map/save failures inline without clearing local draft or selected TC, and Mapping action CRUD/assertion-wait client calls share the same error extraction; `npm run build` and `python -m pytest tests/test_action_crud.py tests/test_assertion_wait_actions.py -q` passed)
- [x] **F-03** Execution 오류 UX — §12.3 | Phase 5 | Layer: GUI | Depends: I-01 (verified 2026-06-06: Automation IDE Runner/Results now classify bootstrap and test failures into actionable guidance with Health Check, Install Dependencies, rerun-failed, diagnosis, retry, and run-folder/log links while preserving execution history and terminal streaming; `npm run build` passed)
- [x] **F-04** Export 오류 UX — §12.4 | Phase 4 | Layer: GUI | Depends: C10-06 (verified 2026-06-06: Automation IDE Export panel now maps preview validation issues, API export failures, and Excel partial write-back errors to actionable guidance with per-item details, retry preview/export, Settings/mapping/results links, and preserved local results.json; `npm run build` passed)

---

## G. 보안 — §13

- [x] **G-01** API key 평문 저장 금지 — §13.1 | Phase 0 | Layer: Infra | Depends: A3-03 (verified 2026-06-05: Worker settings save/load and `/settings` responses strip secret-looking keys such as apiKey/token/password recursively while preserving provider/model config; Electron credential checks return presence only to the renderer and keep model discovery secret use in main process; `python -m pytest tests/test_settings_security.py tests/test_runtime.py tests/test_generated_runtime.py tests/test_generated_runtime_cache.py -q` and `npm run build` passed)
- [x] **G-02** 로그 마스킹 — §13.2 | Phase 5 | Layer: Worker | Depends: A4-03 (verified 2026-06-06: Worker `mask_secrets` now redacts provider keys, bearer tokens, password assignments, session cookies, and secret env values; WebSocket log buffers mask centrally; execution/export persisted messages use the same redaction; generated-template `secret_redaction` patterns aligned; `python -m pytest tests/test_log_masking.py tests/test_generated_runtime.py tests/e2e/test_cli_standalone.py -q` passed)
- [x] **G-03** generated project secret 분리 — §13.3 | Phase 1 | Layer: Template | Depends: B1-03 (verified 2026-06-05: generated-template runner redacts secret env values before writing stdout/stderr/results artifacts, Worker runner/bootstrap artifacts apply the same value-based masking, template copy skips `.env*` and local secret override config files, generated `.gitignore` ignores secret overrides, and runtime manifests exclude API key values/names; `python -m pytest tests/test_generated_runtime.py tests/test_generated_template_fixture_policy.py tests/test_regeneration_guard.py tests/e2e/test_cli_standalone.py -q` and `npm run build` passed)

---

## H. MVP 마일스톤 게이트 — §14, §19

- [x] **H-01** MVP 1 Gate: Excel TC → Generate Raw → Automation IDE run — §14.1 | Phase 1 | Layer: E2E | Depends: E-01..E-05 (baseline MVP 1 gate verified; pytest stitches Excel preview/import, Generate Raw run/actions/mappings/logs, reviewed structure, project generation, generated files, Automation IDE runner execution, result summary, and automation_key traceability; live script at scripts/e2e_mvp1_gate.py)
- [x] **H-02** MVP 2 Gate: Automation IDE edit/regenerate/debug — §14.2 | Phase 2 | Layer: E2E | Depends: D6-07 (baseline MVP 2 gate verified; pytest covers generated file edit/save, IDE search context, regenerate overwrite baseline, traceable failed runner result, and local diagnosis proposal; live script at scripts/e2e_mvp2_gate.py)
- [x] **H-03** MVP 3 Gate — §14.3 | Phase 3 | Layer: E2E | Depends: C10-01, C1-04 (baseline MVP 3 gate verified; pytest covers fake testrail-clone HTTP preview/import, automationKey/source case mapping, generated execution results, export preview payload, bulk upload POST, and ExportLog source ID traceability; live script at scripts/e2e_mvp3_gate.py)
- [x] **H-04** MVP 4 Gate — §14.4 | Phase 4 | Layer: E2E | Depends: C10-02..C10-04 (baseline MVP 4 gate verified; pytest covers TestRail, Google Sheets, and Excel export preview/write-back payloads, source case ID mapping, ExportLog traceability, Excel column creation, and visible non-corrupting Excel export failure; live script at scripts/e2e_mvp4_gate.py)

---

## I. 품질·운영 — §17

- [x] **I-01** Project Health Check — §17.4 | Phase 5 | Layer: Worker | Depends: C9-01
- [x] **I-02** Install Dependencies 버튼 — §12.3 | Phase 5 | Layer: GUI | Depends: I-01
- [x] **I-03** Smoke test — §10.1 | Phase 0 | Layer: E2E | Depends: D2-05, D9-02 (baseline smoke test verified; pytest covers root/health/settings/settings-validate, persisted Setup Wizard/Settings parity fields, clean data-dir settings bootstrap, project health pass/fail paths, and live script at scripts/e2e_smoke.py)
- [x] **I-04** CI standalone contract — §3.5 | Phase 5 | Layer: Docs | Depends: B2-07 (baseline CI standalone commands and artifact contract are consolidated into GENERATED_PROJECT_SPEC; B2-07 standalone CLI E2E remains the verification gate)
- [x] **I-05** Electron Windows installer — §15 | Phase 5 | Layer: Infra | Depends: A1-02 (baseline Windows installer path verified; desktop package exposes pack:win/dist:win scripts via electron-builder@26.0.12, output under apps/desktop/release, and runtime packaging contract lives in RUNTIME_SPEC; npm run build verified)
- [x] **I-06** Desktop renderer build passes (`npm run build`) — Audit 2026-06-02 | Phase 0 | Layer: Quality | Depends: D7-01 (desktop renderer build verified; `npm run build` passes)
- [x] **I-07** Runtime Profile + prepare-runtime installer bundle — Spec: RUNTIME_SPEC, GENERATED_PROJECT_SPEC | Phase 5 | Layer: Infra | Depends: I-05 (runtime pass: runtime profile resolver, bundled python env wiring, prepare-runtime.ps1, and dist:win:full path)
- [x] **I-08** clean Windows `dist:win:full` validation — Spec: RUNTIME_SPEC | Phase 5 | Layer: Quality | Depends: I-07, C3-08, E-09, E-10 (verified 2026-06-04: clean full rebuild, real bundled runtime/notices, silent NSIS install into a new directory, fresh Electron profile, installed live `/health allOk=true`, real non-mock Webwright final script plus RawAction indexing, generated project, and bundled Chromium Runner `1 passed`)
- [x] **I-09** runtime/docs encoding and checklist ID cleanup — Spec: RUNTIME_SPEC | Phase 5 | Layer: Docs | Depends: I-07 (verified 2026-06-06: Korean spec docs under `docs/` contain no mojibake on UTF-8 readback; duplicate misplaced `B1-02` row removed from section I and folded into `B3-04`; progress summary aligned to D 49/49, E 12/12, I 9/9; stale runtime planning gaps marked resolved)

