# Implementation Checklist

**Last updated:** 2026-05-31  
**Current phase:** Phase 0  
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
| A. Infra | 25 | 33 |
| B. Template | 0 | 18 |
| C. Worker | 0 | 74 |
| D. GUI | 29 | 47 |
| E. E2E | 0 | 8 |
| F. Errors | 0 | 4 |
| G. Security | 0 | 3 |
| H. MVP Gates | 0 | 4 |
| I. Quality | 0 | 5 |

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
- [ ] **A2-08** `CaseActionMappingAction` join 모델 — Spec: DB_SCHEMA | Phase 1 | Layer: Worker | Depends: A2-05
- [ ] **A2-09** `StructuredFlow` / `StructuredStep` 모델 — Spec: DATA_MODEL_SPEC, DB_SCHEMA | Phase 1 | Layer: Worker | Depends: A2-05
- [ ] **A2-10** `PageObject` / `PageObjectMethod` 모델 — Spec: DATA_MODEL_SPEC, DB_SCHEMA | Phase 1 | Layer: Worker | Depends: A2-09
- [ ] **A2-11** `GeneratedFileOrigin`, `content_hash`, `status` 모델 — Spec: DB_SCHEMA | Phase 1 | Layer: Worker | Depends: A2-10
- [ ] **A2-12** schema version / migration baseline — Spec: DB_SCHEMA | Phase 1 | Layer: Worker | Depends: A2-11
- [ ] **A2-13** `ArtifactAsset` 모델 — Spec: SELF_HEALING_SPEC, DB_SCHEMA | Phase 1 | Layer: Worker | Depends: A2-03, A2-06
- [ ] **A2-14** `SelectorCandidate` 모델 — Spec: SELF_HEALING_SPEC, DB_SCHEMA | Phase 1 | Layer: Worker | Depends: A2-04, A2-10
- [ ] **A2-15** `HealingProposal` 모델 — Spec: SELF_HEALING_SPEC, DB_SCHEMA | Phase 2 | Layer: Worker | Depends: A2-13, A2-14

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

- [ ] **B1-01** 디렉터리 구조 — §9.2 | Phase 1 | Layer: Template
- [ ] **B1-02** requirements.txt, pytest.ini, README — §9.2 | Phase 1 | Layer: Template | Depends: B1-01
- [ ] **B1-03** config env files + automation.yaml — §9.2 | Phase 1 | Layer: Template | Depends: B1-01
- [ ] **B1-04** mappings/cases.yaml 스키마 — §9.3 | Phase 1 | Layer: Template | Depends: B1-01

### B2. Runner CLI — §9.4

- [ ] **B2-01** runner/cli.py — run — §9.4 | Phase 1 | Layer: Template | Depends: B1-01
- [ ] **B2-02** runner/cli.py — list-cases — §9.4 | Phase 1 | Layer: Template | Depends: B2-01
- [ ] **B2-03** runner/cli.py — rerun-failed — §9.4 | Phase 1 | Layer: Template | Depends: B2-01
- [ ] **B2-04** runner/cli.py — export — §9.4 | Phase 4 | Layer: Template | Depends: B2-01
- [ ] **B2-05** mapping_loader.py, pytest_runner.py — §9.4 | Phase 1 | Layer: Template | Depends: B2-01
- [ ] **B2-06** result_parser.py, result_writer.py — §5.13 | Phase 1 | Layer: Template | Depends: B2-05
- [ ] **B2-07** CLI 단독 실행 E2E 검증 — §3.5 | Phase 1 | Layer: E2E | Depends: B2-06

### B3. Page / Flow / Test 샘플 — §5.10

- [ ] **B3-01** pages/base_page.py — §5.10 | Phase 1 | Layer: Template | Depends: B1-01
- [ ] **B3-02** fixtures/browser_fixture.py, env_fixture.py — §9.2 | Phase 1 | Layer: Template | Depends: B1-01
- [ ] **B3-03** 샘플 flow + test 1세트 — §5.10 | Phase 1 | Layer: Template | Depends: B3-01, B3-02

### B4. Result Export Adapters — §5.14

- [ ] **B4-01** testrail_clone_uploader.py — §5.14 | Phase 3 | Layer: Template | Depends: B2-06
- [ ] **B4-02** testrail_uploader.py — §5.14 | Phase 4 | Layer: Template | Depends: B2-06
- [ ] **B4-03** excel_writer.py — §5.14 | Phase 4 | Layer: Template | Depends: B2-06
- [ ] **B4-04** google_sheets_writer.py — §5.14 | Phase 4 | Layer: Template | Depends: B2-06

---

## C. Worker 서비스 (FastAPI)

### C1. Case Import Service — §5.5

- [ ] **C1-01** normalized TC Pydantic 모델 — §5.5 | Phase 1 | Layer: Worker | Depends: A2-02
- [ ] **C1-02** Excel preview API — §7.2 | Phase 1 | Layer: Worker | Depends: C1-01
- [ ] **C1-03** Excel import API — §7.2 | Phase 1 | Layer: Worker | Depends: C1-02
- [ ] **C1-04** testrail-clone import adapter — §5.5 | Phase 3 | Layer: Worker | Depends: C1-01
- [ ] **C1-05** TestRail import adapter — §5.5 | Phase 4 | Layer: Worker | Depends: C1-01
- [ ] **C1-06** Google Sheets import adapter — §5.5 | Phase 4 | Layer: Worker | Depends: C1-01
- [ ] **C1-07** GET/PATCH /cases — §7.2 | Phase 1 | Layer: Worker | Depends: C1-01

### C2. Prompt Builder — §5.6

- [ ] **C2-01** TC → task prompt 템플릿 — §5.6 | Phase 1 | Layer: Worker | Depends: C1-01
- [ ] **C2-02** startUrl, preconditions, steps 조합 — §5.6 | Phase 1 | Layer: Worker | Depends: C2-01
- [ ] **C2-03** TC 의도 보존 검증 — §5.6 | Phase 1 | Layer: E2E | Depends: C2-02
- [ ] **C2-04** batch-level shared prompt + per-case override 모델 — Spec: PRODUCT_PILLARS | Phase 1 | Layer: Worker | Depends: C2-02
- [ ] **C2-05** prompt preset 모델(login/search/CRUD/assertion-heavy 등) — Spec: PRODUCT_PILLARS | Phase 1 | Layer: Worker | Depends: C2-04
- [ ] **C2-06** prompt preview API — Spec: API_SPEC, PRODUCT_PILLARS | Phase 1 | Layer: Worker | Depends: C2-05
- [ ] **C2-07** Webwright prompt payload 저장/추적 — Spec: PRODUCT_PILLARS, DATA_MODEL_SPEC | Phase 1 | Layer: Worker | Depends: C2-06

### C3. Webwright CLI Adapter — §5.4

- [ ] **C3-01** Webwright 경로 검증 — §5.4 | Phase 1 | Layer: Worker | Depends: A3-01
- [ ] **C3-02** native subprocess 실행 — §5.4 | Phase 1 | Layer: Worker | Depends: C3-01
- [ ] **C3-03** WSL subprocess 실행 — §5.4 | Phase 1 | Layer: Worker | Depends: C3-01
- [ ] **C3-04** API key 환경변수 주입 — §5.4, §13 | Phase 1 | Layer: Worker | Depends: C3-02
- [ ] **C3-05** artifact 수집 — §5.7 | Phase 1 | Layer: Worker | Depends: C3-02
- [ ] **C3-06** error classification — §12.1 | Phase 5 | Layer: Worker | Depends: C3-05

### C4. Webwright Run Service — §5.7

- [ ] **C4-01** 1 TC = 1 Run — §5.7 | Phase 1 | Layer: Worker | Depends: C3-02
- [ ] **C4-02** 상태 모델 — §5.7 | Phase 1 | Layer: Worker | Depends: A2-03
- [ ] **C4-03** artifact 디렉터리 + metadata.json — §5.7 | Phase 1 | Layer: Worker | Depends: C4-01
- [ ] **C4-04** API create/list/get/cancel/retry — §7.3 | Phase 1 | Layer: Worker | Depends: C4-03
- [ ] **C4-05** Action Extraction 자동 트리거 — §11.2 | Phase 1 | Layer: Worker | Depends: C4-04, C5-04

### C5. Action Extraction Service — §5.8

- [ ] **C5-01** 라인 기반 Playwright API 추출 — §5.8 | Phase 1 | Layer: Worker | Depends: C3-05
- [ ] **C5-02** trajectory.json 보조 — §5.8 | Phase 1 | Layer: Worker | Depends: C5-01
- [ ] **C5-03** action type enum 17종 — §5.8 | Phase 1 | Layer: Worker | Depends: C5-01
- [ ] **C5-04** RawAction DB 저장 — §5.8 | Phase 1 | Layer: Worker | Depends: A2-04, C5-01
- [ ] **C5-05** Python AST 고도화 — §5.8 | Phase 5 | Layer: Worker | Depends: C5-01

### C6. Mapping & Review Service — §5.9

- [ ] **C6-01** TC step ↔ action 자동 1:1 매핑 — §5.9 | Phase 1 | Layer: Worker | Depends: C5-04
- [ ] **C6-02** needs_review 상태 — §5.9 | Phase 1 | Layer: Worker | Depends: C6-01
- [ ] **C6-03** action CRUD — §5.9 | Phase 1 | Layer: Worker | Depends: C6-01
- [ ] **C6-04** assertion/wait 추가 — §5.9 | Phase 1 | Layer: Worker | Depends: C6-03
- [ ] **C6-05** normalized step / POM method 이름 — §5.9 | Phase 1 | Layer: Worker | Depends: C6-03
- [ ] **C6-06** Mapping API — §7.4 | Phase 1 | Layer: Worker | Depends: C6-01
- [ ] **C6-07** TC step ↔ multiple raw actions join 저장 — Spec: DB_SCHEMA, STRUCTURING_SPEC | Phase 1 | Layer: Worker | Depends: A2-08, C6-06

### C7. Structuring Service — §5.10

- [ ] **C7-01** Reviewed action → Normalized Flow — §5.10 | Phase 1 | Layer: Worker | Depends: C6-06
- [ ] **C7-02** Page Object method 생성 — §5.10 | Phase 1 | Layer: Worker | Depends: C7-01
- [ ] **C7-03** Flow function 생성 — §5.10 | Phase 1 | Layer: Worker | Depends: C7-02
- [ ] **C7-04** Test function 생성 — §5.10 | Phase 1 | Layer: Worker | Depends: C7-03
- [ ] **C7-05** coding convention 적용 — §5.10 | Phase 1 | Layer: Worker | Depends: C7-04
- [ ] **C7-06** `StructuredFlow` DB persistence — Spec: STRUCTURING_SPEC, DB_SCHEMA | Phase 1 | Layer: Worker | Depends: A2-09, C7-01
- [ ] **C7-07** `StructuredStep` DB persistence — Spec: STRUCTURING_SPEC, DB_SCHEMA | Phase 1 | Layer: Worker | Depends: C7-06
- [ ] **C7-08** `PageObjectMethod` plan persistence — Spec: STRUCTURING_SPEC, DB_SCHEMA | Phase 1 | Layer: Worker | Depends: A2-10, C7-07
- [ ] **C7-09** structure validation API — Spec: STRUCTURING_SPEC, API_SPEC | Phase 1 | Layer: Worker | Depends: C7-08
- [ ] **C7-10** stale/conflict detection for regeneration — Spec: STRUCTURING_SPEC, DB_SCHEMA | Phase 2 | Layer: Worker | Depends: C7-09

### C8. Project Generator Service — §5.11

- [ ] **C8-01** template 기반 파일 생성 — §5.11 | Phase 1 | Layer: Worker | Depends: C7-05, B1-01
- [ ] **C8-02** generated file metadata DB — §5.11 | Phase 1 | Layer: Worker | Depends: C8-01
- [ ] **C8-03** Generation API — §7.5 | Phase 1 | Layer: Worker | Depends: C8-01
- [ ] **C8-04** Git repo 가능 출력 — §5.11 | Phase 1 | Layer: Worker | Depends: C8-01
- [ ] **C8-05** generated file origin/hash/status tracking — Spec: DB_SCHEMA | Phase 1 | Layer: Worker | Depends: A2-11, C8-02
- [ ] **C8-06** deterministic regeneration + conflict guard — Spec: STRUCTURING_SPEC | Phase 2 | Layer: Worker | Depends: C8-05, C7-10

### C9. Project Runner Service — §5.13

- [ ] **C9-01** runner.cli subprocess 호출 — §5.13 | Phase 1 | Layer: Worker | Depends: B2-01
- [ ] **C9-02** env/browser/headless/target 전달 — §5.13 | Phase 1 | Layer: Worker | Depends: C9-01
- [ ] **C9-03** stdout/stderr WebSocket — §5.13 | Phase 1 | Layer: Worker | Depends: A4-03, C9-01
- [ ] **C9-04** results.json 파싱 — §5.13 | Phase 1 | Layer: Worker | Depends: C9-01, A2-06
- [ ] **C9-05** Runner API — §7.6 | Phase 1 | Layer: Worker | Depends: C9-04

### C10. Result Export Service — §5.14

- [ ] **C10-01** testrail-clone bulk upload — §5.14 | Phase 3 | Layer: Worker | Depends: C9-04
- [ ] **C10-02** TestRail result update — §5.14 | Phase 4 | Layer: Worker | Depends: C9-04
- [ ] **C10-03** Excel write-back — §5.14 | Phase 4 | Layer: Worker | Depends: C9-04
- [ ] **C10-04** Google Sheets update — §5.14 | Phase 4 | Layer: Worker | Depends: C9-04
- [ ] **C10-05** export preview + 이중 검증 — §17.3 | Phase 4 | Layer: Worker | Depends: C10-01
- [ ] **C10-06** Export API — §7.7 | Phase 3-4 | Layer: Worker | Depends: C10-01

### C11. Project IDE Service — §5.12

- [ ] **C11-01** 파일 트리 API — §7.5 | Phase 2 | Layer: Worker | Depends: C8-03
- [ ] **C11-02** 파일 CRUD API — §7.5 | Phase 2 | Layer: Worker | Depends: C11-01
- [ ] **C11-03** automationKey/selector 검색 — §5.12 | Phase 2 | Layer: Worker | Depends: C11-01

### C12. Artifact-backed Self-Healing Service — Spec: SELF_HEALING_SPEC

- [ ] **C12-01** Webwright logs/screenshots/trajectory artifact indexing — Spec: SELF_HEALING_SPEC | Phase 1 | Layer: Worker | Depends: C3-05, A2-13
- [ ] **C12-02** raw action selector candidate extraction — Spec: SELF_HEALING_SPEC | Phase 1 | Layer: Worker | Depends: C5-04, A2-14
- [ ] **C12-03** execution failure artifact indexing — Spec: SELF_HEALING_SPEC | Phase 2 | Layer: Worker | Depends: C9-04, A2-13
- [ ] **C12-04** failure → structured step/POM method link resolver — Spec: SELF_HEALING_SPEC | Phase 2 | Layer: Worker | Depends: C7-08, C12-03
- [ ] **C12-05** healing proposal generation API — Spec: SELF_HEALING_SPEC, API_SPEC | Phase 2 | Layer: Worker | Depends: A2-15, C12-04
- [ ] **C12-06** accepted proposal apply/regenerate/rerun flow — Spec: SELF_HEALING_SPEC | Phase 2 | Layer: Worker | Depends: C12-05, C8-06, C9-05
- [ ] **C12-07** safe auto-apply guardrails — Spec: SELF_HEALING_SPEC | Phase 3 | Layer: Worker | Depends: C12-06

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
- [x] **D1-05** selected TC/workspace handoff state — Spec: PRODUCT_PILLARS | Phase 1 | Layer: GUI | Depends: D1-02, D3-03 (baseline selected TC handoff verified; TC list/Webwright set shared case state and Mapping/Layout read it)
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
- [ ] **D3-04** source connector preview/config UI — Spec: PRODUCT_PILLARS, SCREEN_INVENTORY | Phase 3-4 | Layer: GUI | Depends: C1-04

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
- [ ] **D5-05** Page Object method planner — Spec: STRUCTURING_SPEC, SCREEN_INVENTORY | Phase 1 | Layer: GUI | Depends: C7-08
- [ ] **D5-06** structure validation/stale/conflict panel — Spec: STRUCTURING_SPEC | Phase 2 | Layer: GUI | Depends: C7-09
- [ ] **D5-07** selector candidate/evidence viewer — Spec: SELF_HEALING_SPEC | Phase 2 | Layer: GUI | Depends: C12-02

### D6. Automation IDE: Project Editing — §10.6 — Workspace: Automation IDE

- [ ] **D6-01** 파일 트리 — §10.6 | Phase 2 | Layer: GUI | Depends: C11-01
- [ ] **D6-02** Monaco Editor — §10.6 | Phase 2 | Layer: GUI | Depends: C11-02
- [ ] **D6-03** Context Panel — §10.6 | Phase 2 | Layer: GUI | Depends: D6-01
- [ ] **D6-04** xterm.js 터미널 — §10.6 | Phase 2 | Layer: GUI | Depends: C9-03
- [ ] **D6-05** Run Current/Linked TC — §10.6 | Phase 2 | Layer: GUI | Depends: C9-05
- [ ] **D6-06** trace/screenshot viewer — §10.6 | Phase 2 | Layer: GUI | Depends: D6-05
- [ ] **D6-07** runner/results/export panels embedded in Automation IDE — Spec: PRODUCT_PILLARS | Phase 2 | Layer: GUI | Depends: D6-05, D8-01
- [ ] **D6-08** failure diagnosis + healing proposal panel — Spec: SELF_HEALING_SPEC | Phase 2 | Layer: GUI | Depends: C12-05, D6-06

### D7. Automation IDE — Runner Panel (embedded) — §10.7

- [ ] **D7-01** 실행 옵션 UI — §10.7 | Phase 1 | Layer: GUI | Depends: C9-05
- [ ] **D7-02** 실시간 로그 — §10.7 | Phase 1 | Layer: GUI | Depends: A4-03

### D8. Automation IDE — Results & Export (embedded) — §10.8

- [ ] **D8-01** summary + case table — §10.8 | Phase 1 | Layer: GUI | Depends: C9-04
- [ ] **D8-02** artifact 링크 — §10.8 | Phase 1 | Layer: GUI | Depends: D8-01
- [ ] **D8-03** Result Export + preview — §10.8 | Phase 3-4 | Layer: GUI | Depends: C10-06
- [ ] **D8-04** accept/reject healing proposal + rerun failed UI — Spec: SELF_HEALING_SPEC | Phase 2 | Layer: GUI | Depends: D6-08, C12-06

### D9. Settings — §10 — Workspace: supporting

Persistent settings surface after Setup Wizard. Same fields as D2 must remain editable here (not one-time only).

- [x] **D9-01** integrations/webwright/LLM/runner UI — §10 | Phase 0 | Layer: GUI | Depends: A3-04 (baseline settings sections verified; structured webwright/LLM, generator, runner, integrations fields plus advanced JSON editor and PUT save)
- [x] **D9-02** post-setup re-edit (D2 field parity: Webwright root, Python, API provider/key, project root, execution mode) + `/settings/validate` — §10.1, Spec: SCREEN_INVENTORY | Phase 0 | Layer: GUI | Depends: D2-07, D9-01, A3-05 (baseline D2 field parity verified; structured re-edit fields, keytar save on Save, and Validate Settings via /settings/validate)
- [x] **D9-03** Settings에서 Setup Wizard 재실행 (선택, `setupComplete` 유지) — §10.1 | Phase 0 | Layer: GUI | Depends: D9-02, A3-06 (baseline wizard re-run verified; Settings action opens rerun mode, Finish/Cancel return to main shell without resetting setupComplete)

---

## E. 실행 시퀀스 E2E — §11

- [ ] **E-01** TC Import E2E — §11.1 | Phase 1 | Layer: E2E | Depends: D3-02
- [ ] **E-02** Generate Raw workspace E2E — §11.2 | Phase 1 | Layer: E2E | Depends: D4-02, D4-04, D4-06
- [ ] **E-03** Automation IDE structure E2E — §11.3 | Phase 1 | Layer: E2E | Depends: D5-03, D5-05
- [ ] **E-04** Project Generation E2E — §11.4 | Phase 1 | Layer: E2E | Depends: C8-03
- [ ] **E-05** Automation IDE runner E2E — §11.5 | Phase 1 | Layer: E2E | Depends: D6-07, D7-02
- [ ] **E-06** Result Export E2E — §11.6 | Phase 3-4 | Layer: E2E | Depends: D8-03
- [ ] **E-07** Reverse handoff rerun E2E (Automation IDE → Generate Raw) — Spec: PRODUCT_PILLARS, WORKFLOW_SPEC | Phase 1 | Layer: E2E | Depends: D1-06, E-02
- [ ] **E-08** Self-healing proposal E2E — Spec: SELF_HEALING_SPEC | Phase 2 | Layer: E2E | Depends: D8-04, C12-06

---

## F. 오류 처리 — §12

- [ ] **F-01** Webwright 실행 오류 UX — §12.1 | Phase 5 | Layer: GUI | Depends: C3-06
- [ ] **F-02** Mapping 오류 UX — §12.2 | Phase 1 | Layer: GUI | Depends: C6-02
- [ ] **F-03** Execution 오류 UX — §12.3 | Phase 5 | Layer: GUI | Depends: I-01
- [ ] **F-04** Export 오류 UX — §12.4 | Phase 4 | Layer: GUI | Depends: C10-06

---

## G. 보안 — §13

- [ ] **G-01** API key 평문 저장 금지 — §13.1 | Phase 0 | Layer: Infra | Depends: A3-03
- [ ] **G-02** 로그 마스킹 — §13.2 | Phase 5 | Layer: Worker | Depends: A4-03
- [ ] **G-03** generated project secret 분리 — §13.3 | Phase 1 | Layer: Template | Depends: B1-03

---

## H. MVP 마일스톤 게이트 — §14, §19

- [ ] **H-01** MVP 1 Gate: Excel TC → Generate Raw → Automation IDE run — §14.1 | Phase 1 | Layer: E2E | Depends: E-01..E-05
- [ ] **H-02** MVP 2 Gate: Automation IDE edit/regenerate/debug — §14.2 | Phase 2 | Layer: E2E | Depends: D6-07
- [ ] **H-03** MVP 3 Gate — §14.3 | Phase 3 | Layer: E2E | Depends: C10-01, C1-04
- [ ] **H-04** MVP 4 Gate — §14.4 | Phase 4 | Layer: E2E | Depends: C10-02..C10-04

---

## I. 품질·운영 — §17

- [ ] **I-01** Project Health Check — §17.4 | Phase 5 | Layer: Worker | Depends: C9-01
- [ ] **I-02** Install Dependencies 버튼 — §12.3 | Phase 5 | Layer: GUI | Depends: I-01
- [ ] **I-03** Smoke test — §10.1 | Phase 0 | Layer: E2E | Depends: D2-05, D9-02
- [ ] **I-04** CI standalone 가이드 — §3.5 | Phase 5 | Layer: Docs | Depends: B2-07
- [ ] **I-05** Electron Windows installer — §15 | Phase 5 | Layer: Infra | Depends: A1-02
