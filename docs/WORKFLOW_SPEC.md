# Workflow Spec

Last aligned: 2026-05-31

이 문서는 architecture의 실행 시퀀스를 PR 단위 검증이 가능한 워크플로우로 정리한다. 모든 workflow는 [PRODUCT_PILLARS.md](./PRODUCT_PILLARS.md)의 2-workspace 모델과 handoff contract를 따른다.

## Workspace Overview

| # | Workflow | Workspace | Handoff out |
|---|----------|-----------|-------------|
| 1 | TC Import | Generate Raw | `TestCase` rows |
| 2 | Webwright Generate | Generate Raw | `WebwrightRun`, `RawAction`, artifacts |
| 7 | Generate Raw rerun (reverse handoff) | Generate Raw ← Automation IDE | refreshed raw actions |
| 3 | Mapping Review | Automation IDE | reviewed `CaseActionMapping` |
| 4 | Project Generation | Automation IDE | generated project files |
| 5 | Project Execution | Automation IDE | `ExecutionRun`, `ExecutionResult` |
| 6 | Result Export | Automation IDE | external TC write-back |

## Workflow 1: TC Import

**Workspace:** Generate Raw  
**Checklist:** E-01, C1, D3

```text
User
  -> GUI (Generate Raw): choose source and file/config
  -> Worker: preview/import request
  -> Case Import Service: parse and normalize
  -> SQLite: save TestCase
  -> GUI: show imported TC list
```

Done when (PRODUCT_PILLARS W1):

- Excel preview returns normalized rows.
- Import writes TestCase rows with `automation_key`.
- GUI can show imported cases without manual DB changes.

## Workflow 2: Webwright Generate

**Workspace:** Generate Raw  
**Checklist:** E-02, C2-C5, D4

```text
User
  -> GUI (Generate Raw): configure LLM/prompt, select TC, run Webwright
  -> Worker: queue run and return jobId
  -> Webwright Adapter: execute native or WSL command
  -> Worker: collect final_script.py and trajectory.json
  -> Action Extraction: create RawAction rows
  -> Mapping Service: seed mapping
  -> GUI: show run status and artifacts
```

Done when (PRODUCT_PILLARS W1 completion signal):

- TC has stable `automation_key`.
- One selected TC creates one WebwrightRun (or mock for review).
- Run status transitions are visible.
- Raw actions are stored; artifact paths are available.
- Logs stream through `/ws/logs/{job_id}`.
- TC is ready to hand off to Automation IDE (Mapping).

## Workflow 3: Mapping Review

**Workspace:** Automation IDE  
**Checklist:** E-03, C6, D5

```text
User
  -> GUI (Automation IDE): open TC in Mapping & Review
  -> Worker: load TC, raw actions, mappings
  -> GUI: user edits mapping
  -> Worker: save mapping and action updates
  -> SQLite: update CaseActionMapping
```

Done when (PRODUCT_PILLARS W2):

- TC steps and raw actions can be reviewed side by side.
- User can save mapping changes.
- `needs_review` and `mapped` statuses are represented.
- Mapping is reviewable and editable.

## Workflow 4: Project Generation

**Workspace:** Automation IDE  
**Checklist:** E-04, B1-B3, C7-C8, D6

```text
User
  -> GUI (Automation IDE): click Generate Project
  -> Worker: transform reviewed mappings into structured flow
  -> Project Generator: write generated project files
  -> SQLite: save GeneratedFile metadata
  -> GUI: open Project IDE file tree
```

Done when:

- Generated project directory is created.
- `mappings/cases.yaml`, pages, flows, tests, fixtures, runner files exist.
- IDE file tree can browse and open files.
- Generated code preserves `automation_key`.
- Structured flow and POM plan are visible where implemented.

## Workflow 5: Project Execution

**Workspace:** Automation IDE (Runner panel)  
**Checklist:** E-05, C9, D6-07, D7, D8

```text
User
  -> GUI (Automation IDE): choose env/browser/target and click Run
  -> Worker: queue execution and return jobId
  -> Project Runner Service: call generated runner CLI
  -> Generated Project: run pytest/playwright
  -> Generated Project: write results.json and artifacts
  -> Worker: parse results.json into ExecutionRun/ExecutionResult
  -> GUI: show result summary and case table
```

Done when (PRODUCT_PILLARS W2):

- GUI run creates ExecutionRun.
- Logs stream while running.
- `results.json` is parsed.
- Results panel shows summary, per-case status, artifact links.
- Results link back to `automation_key`.
- Generated project can run without the GUI.

## Workflow 6: Result Export

**Workspace:** Automation IDE (Export panel)  
**Checklist:** E-06, C10, B4, D8-03

```text
User
  -> GUI (Automation IDE): choose export target
  -> Worker: preview export
  -> User: confirm write-back
  -> Result Export Service: load results and mapping
  -> Adapter: write to selected target
  -> SQLite: save ExportLog
  -> GUI: show export status
```

Done when:

- Preview shows exactly what will be written.
- Export maps results by `automation_key` and source case ID.
- Export failure is visible and does not corrupt local results.

## Workflow 7: Generate Raw Rerun (Reverse Handoff)

**Workspace:** Automation IDE → Generate Raw  
**Checklist:** D1-06, D4-02, E-02

Triggered when Automation IDE detects missing/invalid raw action, prompt issue, or user requests Webwright rerun.

```text
User (in Automation IDE)
  -> GUI: failure/mapping gap → "Rerun Webwright" or "Fix in Generate Raw"
  -> GUI: switch to Generate Raw workspace with same TC selected
  -> GUI: open Webwright Runs with TC context and prior prompt
  -> User: adjust prompt/config if needed, retry run
  -> Workflow 2 continues
  -> GUI: return to Automation IDE Mapping with refreshed RawAction
```

Done when (PRODUCT_PILLARS handoff W2 → W1):

- Selected TC and `automation_key` carry across workspace switch.
- User can retry Webwright without re-importing TC.
- Refreshed raw actions are visible in Mapping after rerun.

## MVP Gates

| Gate | Scope | Required workflows |
|------|-------|--------------------|
| MVP 1 | Excel based end-to-end | Workflows 1–5 |
| MVP 2 | Automation IDE edit/regenerate/debug | Workflow 4 plus IDE edit/run loop, D6-07 |
| MVP 3 | testrail-clone integration | Workflows 1 and 6 for testrail-clone |
| MVP 4 | TestRail, Google Sheets, Excel write-back | Workflow 6 for all targets |

## Cross-Cutting Acceptance

- Every workflow keeps TC as the center object.
- Every generated/running/exported artifact can be traced by `automation_key`.
- Long-running steps have a job ID and visible logs.
- Generated project remains executable outside the GUI.
- Secrets never appear in generated files or logs.
- Workspace transitions preserve project and TC selection where possible.
