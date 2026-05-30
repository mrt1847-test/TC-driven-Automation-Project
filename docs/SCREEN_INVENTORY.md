# Screen Inventory

Last aligned: 2026-05-30

이 문서는 Electron + React GUI 화면의 책임, 주요 상태, 연결 API, 체크리스트 항목을 정리한다. GUI는 자동화 로직을 소유하지 않고 Local Worker와 generated automation project를 오케스트레이션한다.

UI/UX 방향은 [UI_UX_DIRECTION.md](./UI_UX_DIRECTION.md)를 따른다. 전체 화면은 Cursor 같은 IDE형 작업공간을 참고하되, 중심 객체는 코드 파일이 아니라 TC와 `automation_key`다.

Top-level product structure follows [PRODUCT_PILLARS.md](./PRODUCT_PILLARS.md). The user-facing app should be organized into two large workspaces, not a flat list of unrelated tabs.

## Workspace Inventory

| Workspace | Purpose | Contained surfaces | Primary checklist |
|-----------|---------|--------------------|-------------------|
| Generate Raw | TC를 불러오고 LLM/Webwright 설정과 prompt를 구성해 raw code/action/artifact 생성 | Dashboard, Source Import, Cases, LLM/API Key Setup, Prompt Composer, Webwright Generate, Raw Artifacts | D1, D2, D3, D4 |
| Automation IDE | raw code를 구조화하고 생성된 자동화 프로젝트를 편집·수정·실행·결과·export | Mapping Review, Normalized Flow, Page Object Plan, File Tree, Editor, Runner, Results, Export | D5, D6, D7, D8, C6, C7 |

Setup and Settings are supporting surfaces outside the two product workspaces.

## Navigation Shell

These routes/components may exist internally, but the visible navigation should group them by workspace.

| Route | Page | Component | Primary checklist |
|-------|------|-----------|-------------------|
| `/` | Project Dashboard | `DashboardPage` | D1-04 |
| `/import` | TC Import | `ImportPage` | D3-01, D3-02 |
| `/cases` | TC List | `CasesPage` | D3-03 |
| `/webwright` | Webwright Generate | `WebwrightPage` | D4-01, D4-02, D4-03 |
| `/mapping` | Mapping & Review | `MappingPage` | D5-01, D5-02, D5-03 |
| `/ide` | Project IDE | `IdePage` | D6-01-D6-06 |
| `/runner` | Runner Panel | `RunnerPage` | D7-01, D7-02 |
| `/results` | Results Panel | `ResultsPage` | D8-01, D8-02 |
| `/export` | Export Panel | `ExportPage` | D8-03 |
| `/settings` | Settings | `SettingsPage` | D9-01 |
| setup gate | Setup Wizard | `SetupWizard` | D2-01-D2-07 |

### Workspace Route Grouping

```text
Generate Raw
  /
  /import
  /cases
  future: /prompt
  future: /llm-settings
  /webwright

Automation IDE
  /mapping
  future: /structure/flow
  future: /structure/page-objects
  future: /structure/validation
  /ide
  /runner
  /results
  /export
```

Runner, Results, and Export are panels inside the Automation IDE workspace. They can keep routes for implementation convenience, but they should not be presented as peer top-level product areas.

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

Prepare the local environment before the main app opens.

### Required Steps

| Step | User Input | Worker/Electron dependency | Done when |
|------|------------|----------------------------|-----------|
| Webwright Root | directory path | Electron `selectDirectory` | path is stored in settings |
| Python venv | interpreter or venv path | Electron `selectDirectory` or text input | health can locate Python |
| API Provider | provider option | settings | provider is persisted |
| API Key | secret value | Electron keytar | secret is stored outside settings |
| Playwright Browser Check | action button | `/health` or `/settings/validate` | browser readiness shown |
| Project Path | directory path | Electron `selectDirectory` | project root is persisted |
| Finish | complete button | app store/settings | main shell opens |

### Out Of Scope

- Full OAuth login.
- Remote SaaS account management.
- Editing generated code.

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
- Live stdout/stderr log.

### APIs

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

Checklist: D9-01

### Purpose

Configure Webwright, generator, runner, and integrations without storing secrets in plain text.

### Required Content

- Webwright root, Python path, execution mode.
- Base/model config names.
- Generated project root/template path.
- Default browser/env/headless.
- Integration base URLs and enabled flags.
- Secret entry buttons that write to keytar.

### APIs

- `GET /settings`
- `PUT /settings`
- `POST /settings/validate`
- `GET /health`
