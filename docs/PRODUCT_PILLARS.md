# Product Workspaces

Last aligned: 2026-05-30

이 제품은 크게 2개의 작업공간으로 나눈다. 이것은 단순한 탭 구분이 아니라 제품의 정보구조와 사용자 흐름을 결정하는 최상위 줄기다.

```text
1. TC -> Webwright Raw Code Studio
2. Automation IDE: Structure / Edit / Run
```

중심 객체는 계속 TC와 `automation_key`다. 사용자는 같은 TC를 두 작업공간을 거치며 raw code, structured automation design, executable project로 발전시킨다.

## Workspace 1: TC To Webwright Raw Code Studio

### Purpose

기존 TC를 불러오고, Webwright에 적용할 LLM/API 설정과 추가 프롬프트를 구성한 뒤, 선택한 TC를 Webwright로 실행해 raw 자동화 코드와 artifact를 만든다.

### User Questions

- 어떤 TC가 자동화 대상인가?
- 어떤 source에서 TC를 가져올 것인가?
- 이 TC의 source, step, expected result, start URL, priority는 무엇인가?
- 어떤 LLM provider/API key/model config로 Webwright를 실행할 것인가?
- TC 외에 어떤 추가 prompt/context를 Webwright에 넘길 것인가?
- Webwright가 이 TC를 어떤 브라우저 조작으로 풀었는가?
- raw script, trajectory, screenshot, log는 어디에 있는가?

### Main Surfaces

- Project Dashboard
- Source connector selector
- TC Import
- TC List
- LLM/API key setup
- Webwright prompt composer
- Prompt template/preset manager
- Webwright Generate
- raw script / trajectory / artifact viewer
- Webwright run log

### Inputs

- Excel
- testrail-clone
- TestRail
- Google Sheets
- manual start URL and execution settings
- LLM provider and API key stored through OS credential store
- Webwright model/base config
- additional prompt, domain hints, auth hints, selector preferences, assertion preferences

### Outputs

- `TestCase`
- source/import metadata
- Webwright prompt payload
- `WebwrightRun`
- `RawAction`
- run artifacts on disk

### Completion Signal

A TC is ready to move to Workspace 2 when:

- it has a stable `automation_key`
- Webwright run completed or was manually mocked for review
- raw actions were extracted
- artifact paths are available for review

### Recommended Features

- TC source import wizard with preview and column/source mapping.
- LLM provider/API key setup with keytar-backed storage and health validation.
- Prompt composer that combines TC title, preconditions, steps, expected result, start URL, and user-added context.
- Prompt presets for login-required flows, search flows, CRUD flows, analytics verification, and visual/assertion-heavy flows.
- Per-case prompt override and batch-level shared prompt.
- Dry-run prompt preview before Webwright execution.
- Webwright run queue with retry, cancel, and log streaming.
- Raw artifact inspector for `final_script.py`, `trajectory.json`, screenshots, and logs.

## Workspace 2: Automation IDE - Structure / Edit / Run

### Purpose

Webwright raw code를 그대로 저장하지 않고, IDE 형태의 작업공간에서 유지보수 가능한 자동화 구조로 바꾸고, 생성된 프로젝트를 편집·수정·실행한다.

이 작업공간은 기존의 `Structure`, `Project IDE`, `Runner`, `Results`, `Export`를 하나로 합친다. 사용자는 raw action mapping부터 POM 설계, generated file editing, runner execution까지 같은 IDE 안에서 처리한다.

### User Questions

- TC step과 raw action이 올바르게 대응되는가?
- 어떤 action을 assertion, wait, helper로 바꿔야 하는가?
- 이 flow는 어떤 Page Object와 method로 나뉘어야 하는가?
- 생성될 코드 구조가 재생성 가능하고 추적 가능한가?
- 생성된 파일이 어디에 있고 어떤 TC에서 왔는가?
- 코드를 직접 수정해야 하는 부분은 어디인가?
- 지금 선택한 TC나 파일을 바로 실행할 수 있는가?
- 실패 결과에서 관련 TC, mapping, generated source로 돌아갈 수 있는가?
- 결과를 원본 TC 관리 시스템으로 내보낼 수 있는가?

### Main Surfaces

- Mapping & Review
- normalized flow editor
- Page Object method planner
- selector/assertion/wait review
- structure diff/validation panel
- generated file tree
- code editor
- TC/mapping/result context panel
- runner controls
- execution log terminal
- result summary and artifacts
- export preview/write-back

### Inputs

- `TestCase`
- `RawAction`
- `CaseActionMapping`
- Webwright raw script and artifacts
- `StructuredFlow`
- `PageObject`
- `PageObjectMethod`
- generated project template
- manual code edits

### Outputs

- `CaseActionMapping`
- `StructuredFlow`
- `StructuredStep`
- `PageObject`
- `PageObjectMethod`
- approved generation plan
- generated project files
- `GeneratedFile`
- `ExecutionRun`
- `ExecutionResult`
- `ExportLog`
- updated external TC result where configured

### Completion Signal

The IDE workspace is useful when:

- mapping is reviewable and editable
- structured flow and page object method plan are visible
- generated project files can be edited and saved
- generated project can run without the GUI
- GUI can edit and save generated files
- runner can execute all/selected/failed cases
- results link back to `automation_key`
- export preview is available before write-back

## Workspace-Level Navigation

Top-level navigation should expose the two workspaces, not a flat list of many tabs.

```text
Workspace 1: Generate Raw
  - Import
  - Cases
  - LLM/API Key Setup
  - Prompt Composer
  - Webwright Runs
  - Raw Artifacts

Workspace 2: Automation IDE
  - Mapping Review
  - Normalized Flow
  - Page Object Plan
  - Structure Validation
  - File Tree
  - Editor
  - Runner
  - Results
  - Export
```

Settings and Setup are supporting surfaces, not product workspaces.

## Handoff Contract

| From | To | Handoff Object |
|------|----|----------------|
| Workspace 1 | Workspace 2 | `TestCase` + prompt payload + latest `WebwrightRun` + `RawAction[]` |
| Workspace 2 | Workspace 1 | missing/invalid raw action, prompt issue, or Webwright rerun request |
| Workspace 2 internal | Structure to runner | `StructuredFlow` + `PageObjectMethod[]` + generated files |
| Workspace 2 internal | Runner to structure | failed result context requiring mapping/code changes |

## Implementation Implication

The UI can still use React routes internally, but the user-facing model should not feel like separate unrelated tabs. It should feel like one workspace for generation and one IDE workspace for structuring, editing, running, and exporting.
