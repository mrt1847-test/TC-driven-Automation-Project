# Workflow Spec

Last aligned: 2026-05-30

이 문서는 architecture의 실행 시퀀스를 PR 단위 검증이 가능한 워크플로우로 정리한다.

## Workflow 1: TC Import

Checklist: E-01, C1, D3

```text
User
  -> GUI: choose source and file/config
  -> Worker: preview/import request
  -> Case Import Service: parse and normalize
  -> SQLite: save TestCase
  -> GUI: show imported TC list
```

Done when:

- Excel preview returns normalized rows.
- Import writes TestCase rows with `automation_key`.
- GUI can show imported cases without manual DB changes.

## Workflow 2: Webwright Generate

Checklist: E-02, C3-C5, D4

```text
User
  -> GUI: select TC and run Webwright
  -> Worker: queue run and return jobId
  -> Webwright Adapter: execute native or WSL command
  -> Worker: collect final_script.py and trajectory.json
  -> Action Extraction: create RawAction rows
  -> Mapping Service: seed mapping
  -> GUI: show run status and artifacts
```

Done when:

- One selected TC creates one WebwrightRun.
- Run status transitions are visible.
- Raw actions are stored and visible in Mapping & Review.
- Logs stream through `/ws/logs/{job_id}`.

## Workflow 3: Mapping Review

Checklist: E-03, C6, D5

```text
User
  -> GUI: open TC in Mapping & Review
  -> Worker: load TC, raw actions, mappings
  -> GUI: user edits mapping
  -> Worker: save mapping and action updates
  -> SQLite: update CaseActionMapping
```

Done when:

- TC steps and raw actions can be reviewed side by side.
- User can save mapping changes.
- `needs_review` and `mapped` statuses are represented.

## Workflow 4: Project Generation

Checklist: E-04, B1-B3, C7-C8, D6

```text
User
  -> GUI: click Generate Project
  -> Worker: transform reviewed mappings into structured flow
  -> Project Generator: write generated project files
  -> SQLite: save GeneratedFile metadata
  -> GUI: open Project IDE
```

Done when:

- Generated project directory is created.
- `mappings/cases.yaml`, pages, flows, tests, fixtures, runner files exist.
- IDE file tree can browse and open files.
- Generated code preserves `automation_key`.

## Workflow 5: Project Execution

Checklist: E-05, C9, D7, D8

```text
User
  -> GUI: choose env/browser/target and click Run
  -> Worker: queue execution and return jobId
  -> Project Runner Service: call generated runner CLI
  -> Generated Project: run pytest/playwright
  -> Generated Project: write results.json and artifacts
  -> Worker: parse results.json into ExecutionRun/ExecutionResult
  -> GUI: show result summary and case table
```

Done when:

- GUI run creates ExecutionRun.
- Logs stream while running.
- `results.json` is parsed.
- Results screen shows summary, per-case status, and artifact links.

## Workflow 6: Result Export

Checklist: E-06, C10, B4, D8-03

```text
User
  -> GUI: choose export target
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

## MVP Gates

| Gate | Scope | Required workflows |
|------|-------|--------------------|
| MVP 1 | Excel based end-to-end | Workflows 1-5 |
| MVP 2 | Project IDE 강화 | Workflow 4 plus IDE edit/run loop |
| MVP 3 | testrail-clone integration | Workflows 1 and 6 for testrail-clone |
| MVP 4 | TestRail, Google Sheets, Excel write-back | Workflow 6 for all targets |

## Cross-Cutting Acceptance

- Every workflow keeps TC as the center object.
- Every generated/running/exported artifact can be traced by `automation_key`.
- Long-running steps have a job ID and visible logs.
- Generated project remains executable outside the GUI.
- Secrets never appear in generated files or logs.

