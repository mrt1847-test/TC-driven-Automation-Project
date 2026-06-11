# Generated Project Spec

Last aligned: 2026-06-05

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

## Secret Separation Contract

Generated projects must never commit or regenerate plaintext provider API keys,
passwords, auth cookies, bearer tokens, or local credential material. The
tracked template and generated output may include placeholder variable names
and non-secret runtime defaults only.

Secrets are supplied outside generated source through CI/Studio environment
variables, OS credential-backed Studio injection, ignored `.env*` files, or
ignored local config overrides such as `config/*.secret.json`,
`config/secrets*.json`, and `config/storage-state*.json`. Template copy and
full regeneration must skip those local secret override files even when a
custom template path contains them.

The generated runner must redact known secret environment values before writing
`artifacts/runs/{runId}/stdout.log`, `stderr.log`, and `results.json`.
`config/runtime-manifest.json`, generated-file metadata, and runner result
metadata must not include secret values or secret-bearing environment variable
names.

Structuring must also break the raw-script credential path before code
generation. Raw `fill` values that are entered into password-like fields, match
known secret environment values, or look like bearer/API/token material must be
persisted into `PageObjectMethod.body_plan_json` only as `${env.*}`
placeholders, with the affected entry left review-required. Generated page,
flow, test, mapping, and refresh-preview output must never include the original
credential literal.

## Directory Contract

```text
generated-automation-project/
  config/
    automation.yaml
    env.local.json
    env.stg.json
    env.prod.json
    runtime-manifest.json
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
      .gitkeep
  conftest.py
  .gitignore
  pytest.ini
  requirements.txt
  README.md
```

## Git-Ready Output

Generated projects must be safe to manage as a Git repository. Studio does not
need to run `git init`, but every generated output must include a deterministic
`.gitignore` covering:

- Python caches and coverage output;
- local virtual environments and `.env` files;
- runner artifacts under `artifacts/runs/`, while keeping
  `artifacts/runs/.gitkeep`;
- Playwright reports, blob reports, test-results, logs, and common OS/editor
  files.

Full regeneration must preserve existing `.git`, `.gitattributes`, and
`.gitmodules` metadata. Template copy must not bring stale local caches or
historical run artifacts into a generated project.

## Runtime Manifest

Generated projects include a deterministic machine-readable runtime manifest at
`config/runtime-manifest.json`.

The manifest contains:

- `schema=tc-studio.generated-runtime-manifest` and `manifestVersion`;
- required Python package expectations from `requirements.txt`, including the
  file hash and normalized requirement lines;
- Python runtime expectations for Studio (`RuntimeProfile.python`) and
  standalone use (`python` from the active shell);
- Playwright browser expectation, default browser, install command, supported
  browser list, and `PLAYWRIGHT_BROWSERS_PATH` cache behavior;
- fixture policy version, registered pytest plugins, `TC_*` environment
  variables, auth/base URL/context/artifact policy, and artifact root;
- supported standalone bootstrap/runner commands;
- supported Studio runner entrypoint and RuntimeProfile-derived defaults;
- `standalone=true` and `studio=true` compatibility flags.

The manifest must not include timestamps, secrets, API keys, selected case IDs,
or run-specific data. Full and selected generation must plan the manifest
through the generated-file conflict guard. User-edited tracked manifests block
regeneration before overwrite. Selected regeneration rewrites the manifest only
when runtime/profile/template inputs change, keeping normal selected-case
affected-file summaries stable.

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
    "pytest_playwright.pytest_playwright",
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

The default template implements this policy through `fixtures.browser_fixture`,
`fixtures.env_fixture`, `conftest.py`, and runner-provided `TC_*` environment
variables. The runner records pytest command/return code/log paths and maps
fixture-created artifacts back into each case result.

The runner disables ambient pytest entry-point plugin autoloading and registers
required plugins explicitly through `pytest_plugins`. Generated projects that
need additional third-party pytest plugins must register them explicitly.

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
- Create `artifacts/runs/{runId}/stdout.log` and `stderr.log`.
- Record pytest command, return code, and log paths in `results.json`.
- Store failure screenshots and traces when configured.
- Map deterministic screenshot/trace/video artifact paths back to each case
  when fixture artifacts exist.
- When pytest-playwright parameterizes a case by browser, artifact mapping must
  recognize browser-suffixed node names such as `test_case[chromium].png`.
- Studio/Worker wrapper logs must not overwrite the generated runner's pytest
  `stdout.log` / `stderr.log`; wrapper stdout/stderr must use separate files
  when the runner has already written pytest logs.
- Studio/Worker execution status must be `failed` when the generated
  `results.json` summary contains failed cases, even if `runner.cli` exited zero
  after successfully writing the result contract.
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

Studio may cache successful bootstrap readiness outside the generated project,
keyed by generated project/runtime-manifest/requirements/runtime inputs. Cache
hits may skip redundant install commands, but must still verify browser
readiness and must not change standalone project behavior.

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

Page object code generation normalizes persisted Playwright locator expressions:

- a terminal action already present in a selector expression is stripped before
  the reviewed action is emitted, preventing output such as
  `.click().click()`; alias methods such as `select_option` for the planned
  `select` action are stripped the same way;
- a leading `page.` locator is scoped to the generated page object as
  `self.page.`.
- generated page method names are taken from `PageObjectMethod.name`, which is
  case-scoped by structuring as
  `{automation_key}__step_{tc_step_index}_{readable_method_base}` to prevent
  same-named TC steps in different cases from overwriting each other; generated
  flow files call these scoped names while mappings and step labels keep the
  shorter reviewed display text.

Method body rendering (C8-11) consumes the full ordered
`PageObjectMethod.body_plan_json`:

- every plan entry is rendered in order; multi-action mapped steps emit one
  line per action instead of only the first entry;
- interaction coverage includes `click`, `fill`, `press`, `check`, `uncheck`,
  `hover`, `select` (emitted as `select_option`), `set_input_files` (string or
  Python list-literal file values), and `drag_to` (target expression scoped to
  `self.page.`);
- assertion entries are emitted as Playwright `expect(...)` calls:
  `assert_text` → `to_contain_text`, `assert_url` → `to_have_url`,
  `assert_visible`/`assert_hidden` → `to_be_visible`/`to_be_hidden`, and
  `assert_count` → `to_have_count` with an integer value; the generated page
  file imports `expect` only when assertions exist;
- wait entries are emitted as locator `wait_for(state=...)`/`wait_for()` or
  `page.wait_for_load_state(...)` for load states; `wait_for_request` and
  `wait_for_response` require expect-context wiring around the triggering
  action and therefore remain explicit review comments;
- review-required, unsupported, and missing-action entries stay deterministic
  comments, and `pass` is appended only when a method has no executable line.

Value parameterization (C8-12) keeps generated code env-switchable:

- `goto` URLs whose scheme+origin match the configured generation base URL are
  emitted as relative paths (`self.page.goto("/login?next=...")`); the runtime
  Playwright context `base_url` (env config `baseUrl` / `TC_BASE_URL`) resolves
  them, so `TC_ENV` switching applies; foreign-origin URLs stay absolute;
- the generation base URL is resolved deterministically from the project
  default env config: `generated/config/env.<defaultEnv>.json` first, falling
  back to the template config, reading `baseUrl`/`base_url`;
- `${env.dot.path}` placeholders in body-plan values (fill/press/select,
  `assert_text`/`assert_url`, goto, non-list `set_input_files`) render as
  runtime lookups `self._env_value("dot.path")`; mixed text renders via
  `"...{}...".format(self._env_value(...))`;
- when placeholders are present, the generated page file emits a self-contained
  `_load_env_config()` helper (reads `config/env.{TC_ENV}.json`, default `stg`)
  and a `GeneratedPage._env_value()` accessor that raises `KeyError` for
  missing paths; env-free pages keep the minimal class shape unchanged;
- non-placeholder literal values keep their existing `json.dumps` rendering,
  and all rendering stays deterministic for the regeneration guards.
- credential placeholders produced by structuring use the same rendering path
  after review, while review-required credential entries remain deterministic
  comments until a reviewer confirms the placeholder/config contract.

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

C8-10 implements this as an explicit human-confirmed soft terminal state
transition. It removes only hash-verified private files, marks their metadata
`obsolete`, rebuilds shared page/mapping content and origins from active cases,
and returns `conflict` without cleanup for edited or unproven shared files.

## Baseline Verification

The generated project baseline is acceptable when:

- `python -m runner.cli list-cases` works.
- `python -m runner.cli run --env stg --browser chromium --all` runs at least one case.
- `results.json` is produced with `automationKey`.
- artifact paths are deterministic.
- Worker-run E2E exercises real pytest-playwright `page`, `context`, `base_url`,
  env config, and artifact fixtures with local Chromium.
- the default generated-template sample runs against a deterministic `data:`
  page and does not depend on an external website.
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

- None for generated-project maintenance E2E; see IMPLEMENTATION_CHECKLIST F/G
  items for remaining product work.
