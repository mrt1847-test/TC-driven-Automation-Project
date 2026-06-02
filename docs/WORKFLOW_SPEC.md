# Workflow Spec

Last aligned: 2026-06-03

This document turns the architecture into workflow-sized acceptance contracts.
All workflows follow the two-workspace model in
[PRODUCT_PILLARS.md](./PRODUCT_PILLARS.md):

- Workspace 1: Generate Raw
- Workspace 2: Automation IDE

## Workspace Overview

| # | Workflow | Workspace | Handoff out |
|---|----------|-----------|-------------|
| 1 | TC Import | Generate Raw | `TestCase` rows |
| 2 | Webwright Generate | Generate Raw | `WebwrightRun`, `RawAction`, artifacts |
| 7 | Selected Webwright Raw Refresh | Generate Raw <- Automation IDE | refreshed raw actions for selected already-structured TC |
| 3 | Mapping Review | Automation IDE | reviewed `CaseActionMapping` |
| 4 | Project Generation | Automation IDE | generated project files |
| 5 | Project Execution | Automation IDE | `ExecutionRun`, `ExecutionResult` |
| 8 | Failure Disposition And Maintenance | Automation IDE, optional Generate Raw handoff | healed selector, selected regeneration, or retired TC |
| 6 | Result Export | Automation IDE | external TC write-back |

## Workflow 1: TC Import

**Workspace:** Generate Raw  
**Checklist:** E-01, C1, D3

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

**Workspace:** Generate Raw  
**Checklist:** E-02, C2-C5, D4

```text
User
  -> GUI: configure LLM/prompt, select TC, run Webwright
  -> Worker: queue run and return jobId
  -> Webwright Adapter: execute native or WSL command
  -> Worker: collect final_script.py and trajectory.json
  -> Action Extraction: create RawAction rows
  -> Mapping Service: seed mapping
  -> GUI: show run status and artifacts
```

Done when:

- One selected TC creates one WebwrightRun, or explicit mock mode for review.
- Raw actions and artifact paths are stored.
- Logs stream through `/ws/logs/{job_id}`.
- TC is ready to hand off to Automation IDE.

## Workflow 3: Mapping Review

**Workspace:** Automation IDE  
**Checklist:** E-03, C6, D5

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
- One TC step can map to multiple raw actions when needed.

## Workflow 4: Project Generation

**Workspace:** Automation IDE  
**Checklist:** E-04, B1-B3, C7-C8, D6

```text
User
  -> GUI: click Generate Project
  -> Worker: structure/sync persists StructuredFlow, StructuredStep, PageObjectMethod
  -> Worker: generate code from DB entities
  -> Worker: ensure_generated_runtime
  -> SQLite: save GeneratedFile and GeneratedFileOrigin metadata
  -> GUI: open Project IDE file tree
```

Done when:

- Generated project directory is created.
- `mappings/cases.yaml`, pages, flows, tests, fixtures, and runner files exist.
- IDE file tree can browse and open files.
- Generated code preserves `automation_key`.
- Structured flow and POM plans are persisted in DB and reflected in generated files.
- `runtimeBootstrap.ok` is true or user can recover via Install Runtime.

## Workflow 5: Project Execution

**Workspace:** Automation IDE  
**Checklist:** E-05, C9, D6-07, D7, D8

```text
User
  -> GUI: optional Install Runtime if health/deps missing
  -> GUI: choose env/browser/target and click Run
  -> Worker: ensure_generated_runtime then queue execution
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
- Results panel shows summary, per-case status, and artifact links.
- Results link back to `automation_key`.
- Generated project can run without the GUI.

## Workflow 6: Result Export

**Workspace:** Automation IDE  
**Checklist:** E-06, C10, B4, D8-03

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

## Workflow 7: Selected Webwright Raw Refresh

**Workspace:** Automation IDE -> Generate Raw  
**Checklist:** D1-06, D4-02, E-02, C12-09

Triggered when Automation IDE detects missing/invalid raw action, prompt issue,
fresh raw evidence is needed, or the user intentionally reruns Webwright for
selected TCs that are already structured/generated.

```text
User in Automation IDE
  -> GUI: choose "Refresh Webwright raw for selected TC"
  -> GUI: switch to Generate Raw with same TC selected
  -> GUI: open Webwright Runs with TC context and prior prompt
  -> User: adjust prompt/config if needed, retry run
  -> Worker: refresh RawAction and mapping candidates for that TC
  -> Worker: merge refreshed raw actions into existing structured entities where safe
  -> GUI: return to Automation IDE with merged structure or review-required changes
```

Done when:

- Selected TC and `automation_key` carry across workspace switch.
- User can retry Webwright without re-importing TC.
- Old and new raw artifacts remain available for comparison.
- Refreshed raw actions merge into existing structured state when intent is clear.
- Ambiguous raw changes are marked for Mapping/Structure review instead of
  silently rebuilding the TC.

## Workflow 8: Failure Disposition And Maintenance

**Workspace:** Automation IDE, optional Generate Raw handoff  
**Checklist:** C12-08, C12-09, C12-10, C8-09, C8-10, D6-09, D6-10, E-11, E-12

Triggered when a generated project run fails.

```text
Execution failure
  -> Worker: link failure to automation_key, generated files, structured step, POM method, raw action
  -> Worker: classify disposition
  -> GUI: show evidence, confidence, and recommended action
  -> User: choose repair path
  -> Worker/GUI: apply selected path
  -> User: rerun selected or failed cases
```

Maintenance paths:

| Disposition | User action | Worker action |
|-------------|-------------|---------------|
| `selector_changed` | accept/reject selector healing | update structured selector/POM metadata, regenerate guarded files, rerun |
| `raw_refresh_required` | refresh Webwright raw for selected TC | merge raw actions into existing structure, incrementally regenerate affected files only |
| `feature_removed_retire_tc` | confirm retire/delete TC | retire/delete TC and cleanup generated artifacts only when not shared |
| `unknown` | inspect evidence manually | preserve evidence and avoid automatic code changes |

Done when:

- Failure reason is visible and tied to artifacts.
- The recommended action is specific to the failed TC.
- Already structured TCs can refresh Webwright raw for only the selected TC.
- New raw actions merge into existing structured entities before generation.
- Selected regeneration preserves unrelated generated cases in the same project.
- Feature removal requires human confirmation before retiring/deleting a TC.
- Generated artifact cleanup respects shared origins and edited-file conflicts.

## MVP Gates

| Gate | Scope | Required workflows |
|------|-------|--------------------|
| MVP 1 | Excel based end-to-end | Workflows 1-5 |
| MVP 2 | Automation IDE edit/regenerate/debug | Workflows 4, 5, 7, 8 |
| MVP 3 | testrail-clone integration | Workflows 1 and 6 |
| MVP 4 | TestRail, Google Sheets, Excel write-back | Workflow 6 for all targets |

## Cross-Cutting Acceptance

- Every workflow keeps TC as the center object.
- Every generated/running/exported artifact can be traced by `automation_key`.
- Long-running steps have a job ID and visible logs.
- Generated project remains executable outside the GUI.
- Secrets never appear in generated files or logs.
- Workspace transitions preserve project and TC selection where possible.
