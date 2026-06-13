# UI/UX Direction

Last aligned: 2026-06-13

이 제품의 UI/UX는 Cursor 같은 작업 중심 IDE를 참고한다. 목표는 마케팅형 SaaS 화면이 아니라, QA 자동화 담당자가 TC를 가져오고, raw automation을 검토하고, 구조화된 프로젝트를 편집·실행하는 로컬 작업 환경이다.

**제품 정보구조의 기준:** [PRODUCT_PILLARS.md](./PRODUCT_PILLARS.md) — `Generate Raw`와 `Automation IDE: Structure / Edit / Run`. flat tab 목록이 아니다.

## Product Feel

- Quiet, dense, keyboard-friendly desktop tool.
- Project-first, file-aware, context-rich workflow.
- User should feel like they are inside an automation workspace, not a dashboard-only web app.
- Visual priority is clarity, state, and fast switching between related work surfaces.

## Cursor-Inspired Principles

Cursor에서 참고할 방향:

- 좌측 탐색 영역은 프로젝트/작업 단계/파일 탐색의 기준점이 된다.
- 중앙 영역은 항상 현재 주요 작업물을 보여준다.
- 우측 패널은 선택된 TC, mapping, generated file, run result 같은 context를 보여준다.
- 하단 패널은 terminal, runner log, Webwright log, diagnostics를 담당한다.
- command-oriented actions are close to the current context.
- 작업 전환이 빨라야 하며 화면 이동만으로 맥락이 끊기지 않아야 한다.

Cursor를 그대로 복제하지 않는다. 이 앱의 중심 객체는 코드 파일이 아니라 TC와 `automation_key`다.

## Layout Model

```text
Top: compact titlebar / project switcher / global actions

Left Activity Bar:
  - Generate Raw
  - Automation IDE
  - Settings (supporting, not a product workspace)

Generate Raw secondary nav (when active):
  - Dashboard, Import, Cases, Prompt, LLM/API Key, Webwright Runs, Raw Artifacts

Automation IDE secondary nav (when active):
  - Mapping, Flow, POM Plan, Validation, IDE, Runner, Results, Export
  - Runner/Results/Export are panels, not peer workspaces

Primary Work Area:
  - active workspace surface

Right Context Panel:
  - selected TC
  - automation_key
  - mapping summary
  - latest run/result
  - source metadata

Bottom Panel:
  - logs
  - runner terminal
  - diagnostics
  - generated output
```

## Two Workspaces

The app should not feel like a row of independent tabs. It should feel like one local automation workbench with two large workspaces.

### 1. Generate Raw

Purpose: import TC, configure Webwright/LLM context, and produce raw code/actions.

Contained surfaces:

- Project overview
- source connector selector
- TC import
- TC list
- LLM provider/API key setup
- prompt composer and prompt presets
- Webwright run table
- raw script, trajectory, screenshots, logs

Recommended prompt/LLM controls:

- provider and model config
- OS credential-backed API key entry
- batch-level shared prompt
- per-case prompt override
- start URL/auth/domain hints
- assertion and selector preferences
- prompt preview before execution

### 2. Automation IDE

Purpose: structure raw code, edit generated files, run automation, inspect results, and export outcomes.

Contained surfaces:

- TC step to raw action mapping
- normalized flow editor
- Page Object method planner
- selector/assertion/wait review
- structure validation
- generated file tree
- code editor
- TC/mapping/result context
- runner controls
- execution terminal/log
- result artifacts
- export preview

Runner belongs inside Automation IDE as an execution panel, not as an unrelated top-level tab.

## Workspace Handoff UX

Follow [PRODUCT_PILLARS.md — Handoff Contract](./PRODUCT_PILLARS.md#handoff-contract).

| Transition | UX requirement |
|------------|------------------|
| Generate Raw → Automation IDE | When TC meets W1 completion signal, offer "Open in Mapping" with `automation_key` selected |
| Automation IDE → Generate Raw | From mapping gap or result diagnosis, offer "Rerun Webwright" / "Fix in Generate Raw" without losing TC selection |
| Automation IDE internal | Failed run links to Mapping, Flow, POM plan, or generated file in same workspace |
| Cross-workspace | Project and selected TC stay visible in shell header or context panel |

## Completion Signals (UI)

Surface readiness using PRODUCT_PILLARS completion signals, not only HTTP success:

- **Generate Raw ready for handoff:** stable `automation_key`, Webwright run completed (or mock), raw actions + artifact paths visible.
- **Automation IDE useful:** mapping editable, structure/generation runnable, results link to `automation_key`, export preview available.

## Navigation

- Use persistent left navigation.
- Keep current project and selected TC visible whenever possible.
- Allow deep linking to a case by `automation_key`.
- Implementation note (D1-08): `?automation_key=<key>` resolves the selected
  TC within the active project. GUI handoff links from generated-file, result,
  export, and healing contexts should preserve that key when opening Mapping,
  Webwright, or related IDE surfaces.
- Screens should preserve selection state when moving between Generate Raw and Automation IDE.
- Avoid wizard-like flows after initial setup unless the operation truly requires sequential confirmation.

## Screen Density

- Prefer compact tables, split panes, tabs, and resizable panels.
- Avoid landing-page hero sections, promotional cards, or oversized empty-state illustrations.
- Empty states should offer the next concrete action, such as importing Excel or creating a project.
- Cards are acceptable for repeated summaries, but main work surfaces should feel like panels or editors.

## Visual Style

- Default theme: dark, neutral, low-glare.
- Accent color should be used sparingly for selection, primary action, and status.
- Use status colors consistently:
  - imported / queued: neutral
  - running: blue
  - needs review: amber
  - mapped/generated/passed: green
  - failed/error: red
  - stale/conflict: purple or orange
- Avoid one-note palettes dominated by only slate/blue/purple. Use restrained semantic colors for status and artifact types.

## Interaction Patterns

- Primary commands should be visible near the current work surface.
- Secondary commands can live in menus or toolbar icons.
- Dangerous actions require confirmation.
- Long-running actions immediately return visible status and stream logs.
- Generated file edits should show saved/dirty/stale state.
- Regeneration should warn if generated files have manual edits or conflicts.
  Automation IDE surfaces Worker 409 conflict summaries with edited/stale/conflict
  file lists, recovery guidance, preview-before-apply, and guarded maintenance actions.

## Key Work Surfaces

### TC Table

- Dense table with filters for status, source, priority, and tag.
- Selecting a row updates the right context panel.
- Row actions: run Webwright, open mapping, open result, open generated file.

### Generate Raw Studio

- Import and preview TC before writing to DB.
- Keep LLM/API key and prompt controls close to Webwright run controls.
- Show the exact prompt payload that will be sent to Webwright.
- Treat raw script and trajectory as generated artifacts for review, not as final automation code.
- Failed Webwright runs should show the Worker-classified error category with an actionable
  summary, recovery steps, retry control, and quick links to the run folder/stderr logs.
  Mapping Review should reuse the same classified failure panel for the latest run evidence.

### Automation IDE Mapping Review

Use a split-pane workflow:

```text
Left: TC steps
Center: raw actions from Webwright
Right: normalized step and POM method plan
Bottom: raw code, screenshot, logs
```

The user should be able to inspect intent, raw action, and generated structure without losing position.

Mapping API validation failures should appear inline in the Mapping Review
surface, near the save/review controls. The message should preserve the Worker
`detail` text when possible, explain that the local draft and selected TC remain
intact, and point to the next recovery action such as fixing duplicate/foreign
action IDs, adding a Webwright run, or rerunning Generate Raw.

### Project IDE

Cursor-like file workspace:

```text
Left: generated file tree
Center: code editor
Right: TC/mapping/result context
Bottom: runner terminal/logs
```

The IDE is scoped to generated automation projects and structure review. It should not become a full general-purpose editor. Runner controls, execution results, and export preview live here as adjacent panels.

### Runner And Logs

- Run controls stay compact.
- Logs are searchable and copyable.
- The active job status is visible across screens.
- Failed execution should link directly to result detail, mapping review, and generated source.
- Bootstrap/runtime failures in Runner and Results should map Worker `bootstrap.message`,
  pip/Playwright status, and failed case errors to titled recovery guidance with
  Health Check, Install Dependencies, retry, rerun-failed, Diagnosis, and run-folder/log
  actions without clearing execution history.
- Export preview/write-back failures should map Worker validation `issues`, API
  `detail`, and Excel `failed` rows to titled recovery guidance with per-item
  listings, retry preview/export, Settings/mapping/results links, and an explicit
  note that local `results.json` is preserved on validation failures.

## Component Guidelines

- Use icon buttons for common editor/runner actions such as run, stop, retry, save, open folder, search, collapse.
- Use segmented controls for modes such as source type, target type, preview/export.
- Use tabs for related artifact views: raw code, screenshot, logs, trajectory.
- Use resizable panes for Mapping and IDE screens.
- Use badges for status, source type, and result target.
- Use command palette later for navigation and actions, but do not block MVP on it.

## Copy And Labels

- Labels should be short and operational.
- Prefer `Run Selected`, `Retry Failed`, `Generate Project`, `Preview Export`, `Open Mapping`.
- Avoid explanatory marketing copy inside the app.
- Error messages should identify what failed, where to inspect it, and the next action.

## MVP UI Acceptance

The first UI pass is acceptable when:

- The app feels like a local workbench rather than a SaaS admin dashboard.
- The left navigation exposes the two large workspaces rather than a long flat tab list.
- The right context and bottom logs are consistent across the two workspaces.
- TC selection can carry through raw generation, structure review, project editing, running, and results.
- Long-running work has visible status and logs.
- Generated project files and TC context can be inspected together.
