# Generated Project Spec

Last aligned: 2026-06-03

The generated automation project is the final executable automation artifact.
Webwright `final_script.py` is raw input material; it is not the final project.

The generated project must run in two contexts:

- inside TC Automation Studio through the Worker and `RuntimeProfile`;
- outside Studio through `python -m runner.cli` in CI or a local shell.

Related specs:

- [RUNTIME_SPEC.md](./RUNTIME_SPEC.md)
- [STRUCTURING_SPEC.md](./STRUCTURING_SPEC.md)

## Design Rules

- Generated project owns executable pytest/Playwright logic.
- Studio may generate, edit, bootstrap, and launch the project, but the project
  must remain independently runnable.
- `automationKey` must appear in mappings, test metadata, logs, and results.
- Secrets must come from environment variables or external config, never
  generated source files.
- Regeneration must be deterministic and must not silently overwrite user edits.
- Selected TC regeneration must preserve unrelated generated cases and artifacts.

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
    generated_page.py
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
  artifacts/
    runs/
      {runId}/
  conftest.py
  pytest.ini
  requirements.txt
  README.md
```

## Runtime Manifest

Generated projects should include a machine-readable runtime manifest, for
example `config/runtime.json` or `config/automation.yaml`, containing:

- required Python package set or lock reference;
- supported browsers;
- default browser and headless setting;
- expected Playwright browser cache behavior;
- fixture policy version;
- supported runner commands;
- whether the project was generated for Studio-only or standalone-compatible use.

## cases.yaml

`mappings/cases.yaml` connects TC source metadata to generated files and results.

```yaml
cases:
  - automationKey: user_login_001
    sourceType: excel
    sourceCaseId: CASE-001
    title: User can login
    testFile: tests/test_user_login_001.py
    testFunction: test_user_login_001
    flow: flows/user_login_001_flow.py
    pageObjects:
      - pages/generated_page.py
    tags:
      - smoke
```

## Pytest Fixture Contract

`conftest.py` must register the fixture modules used by all generated tests:

```python
pytest_plugins = [
    "fixtures.browser_fixture",
    "fixtures.env_fixture",
]
```

The fixture contract must provide or configure:

| Fixture/setting | Requirement |
|-----------------|-------------|
| browser selection | honor pytest-playwright `--browser` and runner CLI `--browser` |
| headless mode | `TC_HEADLESS=true/false`; runner maps `--headed` to this |
| env config | `TC_ENV` selects `config/env.{env}.json` |
| base URL | `base_url` from env config or runner option; tests should avoid hard-coded environment URLs when possible |
| context args | viewport, HTTPS errors, locale/timezone, permissions, storage state |
| auth state | optional `storage_state` path from env config or secret-managed setup |
| timeouts/retries | deterministic defaults in pytest.ini or fixture config |
| artifacts | screenshot/trace/video paths under `artifacts/runs/{runId}` |
| browser cache | honor `PLAYWRIGHT_BROWSERS_PATH` when supplied |

The default template may start minimal, but B3-04 is not complete until these
policies are implemented and documented in the generated project README.

## Runner CLI

### list-cases

```bash
python -m runner.cli list-cases
```

Expected behavior:

- Read `mappings/cases.yaml`.
- Print or return known `automationKey` values and titles.
- Exit non-zero if mappings are missing or invalid.

### run

```bash
python -m runner.cli run --env stg --browser chromium --all
python -m runner.cli run --env stg --browser chromium --case-key user_login_001
python -m runner.cli run --env stg --browser chromium --all --run-id 20260530_001
```

Expected behavior:

- Resolve env config.
- Invoke pytest once per run unless a documented advanced mode is selected.
- Pass browser/headed/env/base-url/artifact settings to pytest.
- Create `artifacts/runs/{runId}/results.json`.
- Store failure screenshots and traces when configured.
- Preserve `automationKey` in every result record.

### rerun-failed

```bash
python -m runner.cli rerun-failed --from-run-id 20260530_001 --run-id 20260530_001_rerun
```

Expected behavior:

- Read previous `results.json`.
- Select failed cases only.
- Run those targets with the previous env/browser unless overridden.
- Write a new run result.

### export

```bash
python -m runner.cli export --run-id 20260530_001 --target testrail-clone
```

Expected behavior:

- Load results and mappings.
- Preview or write back according to adapter policy.
- Never write secrets into generated files.

## In-App Bootstrap Contract

Studio may install dependencies before running:

```text
python -m pip install -r requirements.txt
python -m playwright install chromium
```

Bootstrap is not a best-effort background task. It must block runner execution
when dependencies or browser assets are missing. Worker responses should include:

- missing file or package;
- pip stdout/stderr;
- Playwright install stdout/stderr;
- browser executable check result;
- suggested next action.

If bootstrap fails during an in-app run, Studio must still create deterministic
run artifacts under `artifacts/runs/{runId}`:

- `stdout.log` with bootstrap details;
- `stderr.log` with the actionable failure message;
- `results.json` with a `bootstrap` object and failed case entry when the run
  targeted a specific `automationKey`.

## results.json

```json
{
  "runId": "20260530_001",
  "projectName": "generated-automation-project",
  "env": "stg",
  "browser": "chromium",
  "startedAt": "2026-05-30T14:00:00Z",
  "endedAt": "2026-05-30T14:01:20Z",
  "summary": {
    "total": 1,
    "passed": 1,
    "failed": 0,
    "skipped": 0
  },
  "cases": [
    {
      "automationKey": "user_login_001",
      "sourceType": "excel",
      "sourceCaseId": "CASE-001",
      "title": "User can login",
      "status": "passed",
      "durationMs": 8042,
      "error": null,
      "artifacts": {
        "screenshot": null,
        "trace": null,
        "video": null
      }
    }
  ]
}
```

## Code Generation Contract

| Output | Purpose | Source |
|--------|---------|--------|
| Page object method | Stable selector/action wrapper | `PageObjectMethod.body_plan_json` |
| Flow function | Business-level sequence | `StructuredFlow` / `StructuredStep` |
| Test function | pytest entrypoint | TestCase + flow |
| Fixture | browser/env setup | generated-template |
| Mapping YAML | TC to code/result link | TestCase + generation metadata |
| Runtime manifest | execution contract | template + RuntimeProfile-derived defaults |

## Maintenance Contract

The generated project is expected to contain many TCs. A maintenance action for
one failed TC must not destroy the rest of the project.

Selected regeneration must:

- update only the selected TC test, flow, mapping entry, and directly impacted
  page object methods;
- keep unrelated `tests/`, `flows/`, `pages/`, `artifacts/runs/`, and
  `mappings/cases.yaml` entries;
- return an affected-file summary to Studio;
- respect edited-file conflict guards before overwriting generated source.

TC retire/delete cleanup must:

- remove or mark obsolete the selected TC's test and mapping entry;
- remove shared flow/page code only when no active TC still references it;
- preserve historical `artifacts/runs/` and result files for audit.

## Baseline Verification

The generated project baseline is acceptable when:

- `python -m runner.cli list-cases` works.
- `python -m runner.cli run --env stg --browser chromium --all` runs at least one case.
- `results.json` is produced with `automationKey`.
- artifact paths are deterministic.
- the project can run outside Electron after installing `requirements.txt` and Playwright browser assets.

## Standalone CI Commands

Run these from the generated project root:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m playwright install chromium
python -m runner.cli list-cases
python -m runner.cli run --env stg --browser chromium --all
```

CI should archive `artifacts/runs/`. Secrets must be supplied through the CI
environment, not generated source files.

## Open Implementation Work

- B2-08: runner artifact contract hardening.
- B3-04: generated pytest fixture/browser policy.
- C8-08: generated-project runtime manifest.
- C8-09: selected TC incremental regeneration.
- C8-10: TC retire/delete generated artifact cleanup.
- C12-09: selected TC Webwright refresh regeneration flow.
- C12-10: TC retire recommendation and cleanup flow.
- E-10: generated pytest/browser contract E2E.
- E-11: selected TC Webwright refresh incremental regeneration E2E.
- E-12: feature-removed TC retire cleanup E2E.
