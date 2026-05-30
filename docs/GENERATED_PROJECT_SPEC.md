# Generated Project Spec

Last aligned: 2026-05-31

Generated automation project는 실제 Playwright/pytest 실행 단위다. GUI 없이도 독립 실행 가능해야 하고, CI에서도 같은 CLI로 실행되어야 한다.

**Product workspace:** primary output of **Automation IDE** ([PRODUCT_PILLARS.md](./PRODUCT_PILLARS.md)). Webwright `final_script.py` from Generate Raw is input material, not the final executable project.

## Design Rules

- Webwright `final_script.py`는 최종 코드가 아니라 구조화 재료다.
- Generated project owns executable test logic.
- GUI and Worker may create/edit/run the project, but generated project must remain runnable by itself.
- `automation_key` must appear in mappings, tests, and results.
- Secrets must be read from environment or external config, never hardcoded.

## Directory Contract

```text
generated-automation-project/
  config/
    automation.yaml
    env.local.json
    env.stg.json
    env.prod.json
  fixtures/
    browser_fixture.py
    env_fixture.py
  flows/
    {automation_key}_flow.py
  mappings/
    cases.yaml
  pages/
    base_page.py
    {page_name}.py
  runner/
    __init__.py
    cli.py
    mapping_loader.py
    pytest_runner.py
    result_parser.py
    result_writer.py
    testrail_clone_uploader.py
    testrail_uploader.py
    excel_writer.py
    google_sheets_writer.py
  tests/
    test_{automation_key}.py
  conftest.py
  pytest.ini
  requirements.txt
  README.md
```

## cases.yaml

`mappings/cases.yaml` connects original TC metadata to generated test files.

```yaml
cases:
  - automation_key: user_login_001
    source_type: excel
    source_case_id: CASE-001
    title: User can login
    test_file: tests/test_user_login_001.py
    flow: flows/user_login_001_flow.py
    page_objects:
      - pages/login_page.py
    tags:
      - smoke
```

## Runner CLI

Checklist: B2

### list-cases

```bash
python -m runner.cli list-cases
```

Expected behavior:

- Read `mappings/cases.yaml`.
- Print or return all known `automation_key` values and titles.
- Exit non-zero if mappings are invalid.

### run

```bash
python -m runner.cli run --env stg --browser chromium --all
```

Supported target modes:

```bash
python -m runner.cli run --env stg --browser chromium --all
python -m runner.cli run --env stg --browser chromium --automation-key user_login_001
python -m runner.cli run --env stg --browser chromium --case-id CASE-001
```

Expected behavior:

- Resolve env config.
- Invoke pytest/playwright.
- Create `results.json`.
- Store screenshots/traces when failures occur.
- Preserve `automation_key` in every result record.

### rerun-failed

```bash
python -m runner.cli rerun-failed --from results/results.json
```

Expected behavior:

- Read previous result file.
- Select failed cases.
- Run only failed targets.
- Write a new result file.

### export

```bash
python -m runner.cli export --target testrail-clone --results results/results.json --preview
```

Expected behavior:

- Load results and mappings.
- Preview or write back to target.
- Never write secrets into generated project files.

## results.json

```json
{
  "run_id": "run_20260530_001",
  "env": "stg",
  "browser": "chromium",
  "started_at": "2026-05-30T14:00:00Z",
  "ended_at": "2026-05-30T14:01:20Z",
  "summary": {
    "total": 1,
    "passed": 1,
    "failed": 0,
    "skipped": 0
  },
  "results": [
    {
      "automation_key": "user_login_001",
      "source_type": "excel",
      "source_case_id": "CASE-001",
      "title": "User can login",
      "status": "passed",
      "duration_ms": 8042,
      "error": null,
      "screenshot_path": null,
      "trace_path": null
    }
  ]
}
```

## Code Generation Contract

| Output | Purpose | Source |
|--------|---------|--------|
| Page object method | Stable selector/action wrapper | reviewed raw actions |
| Flow function | Business-level sequence | normalized mapping |
| Test function | pytest entrypoint | TC and flow |
| Fixture | browser/env setup | template |
| Mapping YAML | TC to code/result link | TestCase and generation metadata |

## Naming Rules

- `automation_key` is lowercase snake_case.
- Test files use `test_{automation_key}.py`.
- Flow files use `{automation_key}_flow.py`.
- Page methods use verb-oriented names such as `click_login_button`.
- Generated names should be deterministic so regeneration creates minimal diffs.

## Security Rules

- Do not store API keys in `config/*.json`, `automation.yaml`, tests, flows, or pages.
- Runtime secrets come from environment variables or OS credential store integration controlled by the parent app.
- Logs must mask known token patterns before writing artifacts.

## Baseline Verification

The generated project baseline is acceptable when:

- `python -m runner.cli list-cases` works.
- `python -m runner.cli run --env stg --browser chromium --all` can run at least a sample case.
- `results.json` is produced with `automation_key`.
- The project can be run outside Electron.

