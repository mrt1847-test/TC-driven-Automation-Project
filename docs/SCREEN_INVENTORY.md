# Screen Inventory

Last aligned: 2026-06-02

이 문서는 Electron + React GUI 화면의 책임, 주요 상태, 연결 API, 체크리스트 항목을 정리한다. GUI는 자동화 로직을 소유하지 않고 Local Worker와 generated automation project를 오케스트레이션한다.

**제품 정보구조의 기준:** [PRODUCT_PILLARS.md](./PRODUCT_PILLARS.md). 사용자-facing 앱은 **Generate Raw**와 **Automation IDE** 두 workspace로 조직한다. flat tab 목록이 아니다.

UI/UX 방향: [UI_UX_DIRECTION.md](./UI_UX_DIRECTION.md). Cursor 같은 IDE형 작업공간을 참고하되, 중심 객체는 코드 파일이 아니라 TC와 `automation_key`다.

## Workspace Inventory

| Workspace | Purpose | Main surfaces (PRODUCT_PILLARS) | Checklist |
|-----------|---------|----------------------------------|-----------|
| **Generate Raw** | TC import → LLM/prompt → Webwright raw code/action/artifact | Dashboard, Source Import, Cases, LLM/API Key, Prompt Composer, Webwright Runs, Raw Artifacts | D3, D4 |
| **Automation IDE** | structure → edit → run → results → export | Mapping Review, Normalized Flow, POM Plan, Structure Validation, File Tree, Editor, Runner, Results, Export | D5, D6, D7*, D8* |
| **Supporting** | first-run setup, global config | Setup Wizard, Settings | D2, D9 |

\* Runner, Results, Export는 Automation IDE **내부 패널**이다. peer top-level product area가 아니다.

Setup and Settings are supporting surfaces outside the two product workspaces.

## Navigation Shell

Visible navigation groups routes by workspace. Internal React routes may stay granular; user-facing IA follows PRODUCT_PILLARS.

### Generate Raw — visible nav

| Route | Page | Component | Checklist | Notes |
|-------|------|-----------|-----------|-------|
| `/` | Project Dashboard | `DashboardPage` | D1-04 | workspace entry + project switch |
| `/import` | TC Import | `ImportPage` | D3-01, D3-02 | source connector + preview |
| `/cases` | TC List | `CasesPage` | D3-03 | TC-centric hub |
| `/prompt` | Prompt Composer | planned | D4-05, D4-06 | batch/per-case prompt, presets, preview |
| `/llm-settings` | LLM/API Key Setup | planned or Settings embed | D4-04, D2-03 | keytar-backed secrets |
| `/webwright` | Webwright Runs | `WebwrightPage` | D4-01, D4-02 | run queue, retry, cancel, logs |
| `/artifacts` | Raw Artifacts | planned or Webwright tab | D4-03 | script, trajectory, screenshots |

Current baseline shell (`D1-01`) groups Import/Cases/Webwright under Generate Raw. Prompt Composer and Raw Artifacts routes are planned refinements aligned with PRODUCT_PILLARS nav.

### Automation IDE — visible nav

| Route | Page | Component | Checklist | Notes |
|-------|------|-----------|-----------|-------|
| `/mapping` | Mapping & Review | `MappingPage` | D5-01–D5-03 | TC step ↔ raw action |
| `/structure/flow` | Normalized Flow | planned | D5-04 | StructuredFlow editor |
| `/structure/page-objects` | Page Object Plan | planned | D5-05 | POM method planner |
| `/structure/validation` | Structure Validation | planned | D5-06 | stale/conflict panel |
| `/ide` | Project IDE | `IdePage` | D6-01–D6-08 | file tree, editor, embedded run/export |
| `/runner` | Runner Panel | `RunnerPage` | D7-01, D7-02 | **embedded panel**, not peer workspace |
| `/results` | Results Panel | `ResultsPage` | D8-01, D8-02 | **embedded panel** |
| `/export` | Export Panel | `ExportPage` | D8-03 | **embedded panel** |

Current baseline maps Mapping, IDE, Runner, Results, Export under Automation IDE workspace switcher.

### Supporting — global

| Route | Page | Component | Checklist |
|-------|------|-----------|-----------|
| `/settings` | Settings | `SettingsPage` | D9-01 |
| setup gate | Setup Wizard | `SetupWizard` | D2-01–D2-07 |

### Workspace route grouping (target IA)

```text
Generate Raw
  /
  /import
  /cases
  /prompt
  /llm-settings
  /webwright
  /artifacts

Automation IDE
  /mapping
  /structure/flow
  /structure/page-objects
  /structure/validation
  /ide
  /runner      # panel inside IDE workspace
  /results     # panel inside IDE workspace
  /export      # panel inside IDE workspace

Supporting
  setup gate
  /settings
```

## Handoff Surfaces

PRODUCT_PILLARS handoff contract를 GUI에서 지원한다.

| Direction | Trigger | GUI behavior | Checklist |
|-----------|---------|--------------|-----------|
| W1 → W2 | TC ready (stable `automation_key`, Webwright run + raw actions) | Open Mapping in Automation IDE with selected TC | D1-05, D3-03 |
| W2 → W1 | missing raw action, prompt issue, Webwright rerun needed | Jump to Generate Raw → Webwright with TC context; preserve selection | D1-06, D4-02 |
| W2 internal (structure → runner) | approved structure / generated files | Run from IDE/Runner panel without leaving workspace | D6-07, D7-01 |
| W2 internal (runner → structure) | failed result linked to mapping/POM | Jump to Mapping, Flow, or generated file from result row | D8-01, D8-02, D6-08 |

## Global UI Contracts

- App startup asks Electron main for Worker base URL through preload.
- Project selection is global state.
- Setup completion is global state.
- Long-running jobs surface `jobId` and stream logs from `/ws/logs/{job_id}`.
- File/directory picking and OS path opening go through Electron preload APIs.
- API keys are stored through OS credential store, not rendered back into settings JSON.
- Core screens should share an IDE-like shell: workspace activity bar, primary work area, optional right context panel, and bottom logs/terminal.
- Case selection should carry through Generate Raw and Automation IDE where possible.

## Setup Wizard

Checklist: D2-01-D2-07

### Purpose

Prepare the local environment before the main app opens. **One-time onboarding gate** — not the only place to change these values.

After `setupComplete`, the same configuration must remain editable in [Settings](#settings) (D9-02). Optional full wizard re-run: D9-03.

### Runtime mode (bundled vs custom)

| Mode | Setup behavior | Spec |
|------|----------------|------|
| `bundled` | Paths seeded from `resources/runtime`; fields read-only in wizard | [RUNTIME_SPEC.md](./RUNTIME_SPEC.md) |
| `custom` | User picks Webwright root, Python, optional browser cache | [RUNTIME_SPEC.md](./RUNTIME_SPEC.md) |

Electron sets `TC_STUDIO_RUNTIME_MODE`, `TC_STUDIO_RESOURCES`, `TC_STUDIO_PYTHON`, `TC_STUDIO_PLAYWRIGHT_BROWSERS_PATH` on worker spawn when packaged.

### Required Steps

| Step | User Input | Worker/Electron dependency | Done when |
|------|------------|----------------------------|-----------|
| Webwright Root | directory path (custom only) | Electron `selectDirectory` | path is stored in settings or bundled seed |
| Python venv | interpreter or venv path (custom only) | Electron `selectDirectory` or text input | health can locate Python |
| API Provider | provider option | settings | provider is persisted |
| API Key | secret value | Electron keytar | secret is stored outside settings |
| Playwright Browser Check | action button | `/health` or `/settings/validate` | browser readiness shown |
| Project Path | directory path | Electron `selectDirectory` | project root is persisted |
| Finish | complete button | app store/settings | main shell opens |

### Out Of Scope

- Full OAuth login.
- Remote SaaS account management.
- Editing generated code.
- Locking Setup values after first run (post-setup edit belongs in Settings).

### Field parity with Settings (D9-02)

| Setup Wizard step (D2) | Settings re-edit (D9-02) |
|------------------------|--------------------------|
| Webwright Root (D2-01) | Webwright root path + browse |
| Python (D2-02) | Python / venv path |
| API Provider + Key (D2-03) | Provider selector + keytar secret update |
| Playwright / Smoke (D2-04, D2-05) | Health check + smoke via `/settings/validate` |
| Project Path (D2-06) | Generator default project root |

## Project Dashboard

Checklist: D1-04

### Purpose

Give the user one place to create/select a local automation project and see current automation progress.

### Required Content

- Project list and create project action.
- Current project summary.
- Counts for imported, generated, needs review, passed, failed.
- Quick links to import, Webwright generation, mapping, runner, results.

### APIs

- `GET /projects`
- `POST /projects`
- `GET /projects/{project_id}`
- `GET /projects/{project_id}/cases`
- `GET /projects/{project_id}/executions`

## TC Import

Checklist: D3-01, D3-02

### Purpose

Import manual TC from Excel first, then later TestRail, testrail-clone, and Google Sheets.

### Required Content

- Source type selection: Excel, testrail-clone, TestRail, Google Sheets.
- Excel file picker.
- Sheet name input.
- Column mapping table.
- Preview table before import.
- Import result summary.

### APIs

- `POST /projects/{project_id}/cases/import/excel/preview`
- `POST /projects/{project_id}/cases/import/excel`
- `POST /projects/{project_id}/cases/import/testrail-clone`
- `POST /projects/{project_id}/cases/import/testrail`
- `POST /projects/{project_id}/cases/import/google-sheets`

## TC List

Checklist: D3-03

### Purpose

Show imported TC as the center of the product workflow.

### Required Content

- Table of title, `automation_key`, source, status, priority, start URL.
- Search/filter by status and source.
- Case detail panel with preconditions, steps, expected result.
- Start URL/status quick edit.

### APIs

- `GET /projects/{project_id}/cases`
- `GET /projects/{project_id}/cases/{case_id}`
- `PATCH /projects/{project_id}/cases/{case_id}`

## Webwright Generate

Checklist: D4-01, D4-02, D4-03

### Purpose

Run Webwright for selected TC using configured LLM/API credentials and prompt context, then collect raw script, trajectory, artifacts, actions, and mapping seed.

### Required Content

- TC status table.
- LLM provider/model config selector.
- API key entry/validation surface backed by OS credential store.
- Prompt composer combining TC content with user-added context.
- Prompt preset selector for common automation patterns.
- Prompt preview before run.
- Run selected, stop/cancel, retry actions.
- Model config/start URL override options.
- Real-time log panel.
- Raw script and artifact folder links.

### APIs

- `POST /projects/{project_id}/webwright-runs`
- `GET /projects/{project_id}/webwright-runs`
- `GET /projects/{project_id}/webwright-runs/{run_id}`
- `POST /projects/{project_id}/webwright-runs/{run_id}/retry`
- `POST /projects/{project_id}/webwright-runs/{run_id}/cancel`
- `GET /settings`
- `PUT /settings`
- `POST /settings/validate`
- `WS /ws/logs/{job_id}`

## Automation IDE - Mapping & Review

Checklist: D5-01, D5-02, D5-03

### Purpose

Let the user review the link between TC steps and raw browser actions before structured code is generated.

### Required Layout

```text
Left: TC step list
Center: extracted raw actions
Right: normalized mapping / POM method metadata
Bottom: raw code, screenshot, logs
```

### Required Interactions

- Select a TC and view actions.
- Map one TC step to one or more actions.
- Add assertion/wait actions.
- Rename normalized step and POM method.
- Mark mapping as `mapped` or `needs_review`.
- Save mappings.

### APIs

- `GET /projects/{project_id}/cases/{case_id}/actions`
- `GET /projects/{project_id}/cases/{case_id}/mappings`
- `PUT /projects/{project_id}/cases/{case_id}/mappings`
- `POST /projects/{project_id}/cases/{case_id}/normalize`

## Automation IDE - Project Workspace

Checklist: D6-01-D6-06

### Purpose

Structure raw actions, inspect generated automation structure, edit generated files, run/debug automation, and export results without turning the app into a full general-purpose IDE.

### Required Layout

```text
Left: generated file tree
Center: code editor
Right: TC context / mapping / last result
Bottom: terminal or runner log
```

### Required Interactions

- Generate project from reviewed mappings.
- Browse generated files.
- Open/edit/save files.
- Create, rename, delete files.
- Search by `automation_key`, selector, or filename.
- Open trace/screenshot artifacts where available.
- Run all, selected, current file, current TC, or failed cases from the same workspace.
- Inspect execution results and export preview without leaving the project context.
- Inspect failure diagnosis and self-healing proposals backed by Webwright/runner artifacts.

### APIs

- `POST /projects/{project_id}/generate`
- `GET /projects/{project_id}/generated-files`
- `GET /projects/{project_id}/generated-files/content`
- `PUT /projects/{project_id}/generated-files/content`
- `POST /projects/{project_id}/generated-files/create`
- `DELETE /projects/{project_id}/generated-files`
- `POST /projects/{project_id}/generated-files/rename`
- `GET /projects/{project_id}/search`
- `POST /projects/{project_id}/executions`
- `GET /projects/{project_id}/executions`
- `GET /projects/{project_id}/executions/{execution_id}`

## Automation IDE - Runner Panel

Checklist: D7-01, D7-02

### Purpose

Run the generated automation project from inside the Automation IDE workspace using the same runner contract that CI can use without GUI.

### Required Content

- Environment selector.
- Browser selector.
- Headed/headless option.
- Target selector: all, case IDs, automation key, failed.
- Run, cancel, rerun failed.
- **Install Runtime** — calls `POST /projects/{project_id}/install-dependencies` (pip + chromium) before first run when health reports missing deps.
- Live stdout/stderr log.

### APIs

- `POST /projects/{project_id}/install-dependencies`
- `POST /projects/{project_id}/executions`
- `POST /projects/{project_id}/executions/{execution_id}/cancel`
- `POST /projects/{project_id}/executions/{execution_id}/rerun-failed`
- `WS /ws/logs/{job_id}`

## Automation IDE - Execution Results Panel

Checklist: D8-01, D8-02

### Purpose

Show execution status and per-case results with artifact links inside the Automation IDE workspace.

### Required Content

- Summary counts: passed, failed, skipped, duration.
- Case result table.
- Error message/details.
- Screenshot/trace/artifact links.
- Jump back to case, mapping, or IDE.
- Failure diagnosis panel when a result can be linked to a structured step or POM method.
- Healing proposal panel with evidence, selector candidates, accept/reject, and rerun actions.

### APIs

- `GET /projects/{project_id}/executions`
- `GET /projects/{project_id}/executions/{execution_id}`
- `POST /projects/{project_id}/executions/{execution_id}/healing-proposals`
- `GET /projects/{project_id}/healing-proposals`
- `POST /projects/{project_id}/healing-proposals/{proposal_id}/accept`
- `POST /projects/{project_id}/healing-proposals/{proposal_id}/reject`

## Automation IDE - Result Export Panel

Checklist: D8-03

### Purpose

Preview and write execution results back to the original TC management target from the Automation IDE workspace.

### Required Content

- Target selector: testrail-clone, TestRail, Excel, Google Sheets.
- Preview mode by default.
- Diff or summary before write-back.
- Export result status.

### APIs

- `POST /projects/{project_id}/executions/{execution_id}/export/testrail-clone`
- `POST /projects/{project_id}/executions/{execution_id}/export/testrail`
- `POST /projects/{project_id}/executions/{execution_id}/export/excel`
- `POST /projects/{project_id}/executions/{execution_id}/export/google-sheets`

## Settings

Checklist: D9-01, D9-02, D9-03

### Purpose

Configure Webwright, generator, runner, and integrations **at any time after Setup Wizard**, without storing secrets in plain text. Setup Wizard (D2) is first-run onboarding; Settings is the durable edit surface.

### Required Content

- **D9-01:** integrations, runner defaults, template paths, execution mode (baseline may include raw JSON editor).
- **D9-02:** form-level re-edit of all D2 fields (see Setup Wizard field parity table), Save via `PUT /settings`, re-validate via `/settings/validate` or `/health`.
- **D9-03 (optional):** action to re-open Setup Wizard from Settings while keeping `setupComplete` true.

Shared fields (D9-02 parity with D2):

- Webwright root, Python path, execution mode.
- API provider + secret entry buttons that write to keytar (never echo stored secrets into settings JSON).
- Base/model config names.
- Generated project root/template path.
- Default browser/env/headless.
- Integration base URLs and enabled flags.

### APIs

- `GET /settings`
- `PUT /settings`
- `POST /settings/validate`
- `GET /health`
