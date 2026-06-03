# Runtime Spec

Last aligned: 2026-06-03

This document defines the runtime contract for three execution contexts:

- Generate Raw: Test case -> Webwright -> `final_script.py` / trajectory / logs.
- Generated Project: structured Playwright pytest project created from reviewed raw output.
- In-app Runner: Electron/Worker launching the generated project's `runner.cli`.

Related specs:

- [GENERATED_PROJECT_SPEC.md](./GENERATED_PROJECT_SPEC.md)
- [STRUCTURING_SPEC.md](./STRUCTURING_SPEC.md)
- [API_SPEC.md](./API_SPEC.md)

## Core Principle

The Studio must not rely on an implicit system Python or an implicit Playwright
browser cache. Webwright raw generation and generated project execution both
need an explicit Python interpreter and a verified Playwright browser install.

`RuntimeProfile` is the single source of truth for these paths.

## Runtime Contexts

| Context | Python | Required packages | Browser assets | Owner |
|---------|--------|-------------------|----------------|-------|
| Worker | `RuntimeProfile.python` for subprocess helpers, Electron-selected Python for Worker launch | Worker requirements | Usually none directly | Studio app |
| Webwright raw generation | `RuntimeProfile.webwright_python` | Webwright package/source, Playwright | `PLAYWRIGHT_BROWSERS_PATH` or Playwright default cache | Webwright adapter |
| Generated project runner | `RuntimeProfile.python` | generated `requirements.txt`, pytest, pytest-playwright, Playwright | `PLAYWRIGHT_BROWSERS_PATH` or standalone CI cache | generated project |

## RuntimeProfile Fields

| Field | Purpose |
|-------|---------|
| `mode` | `custom` or `bundled` |
| `python` | Python used for generated project bootstrap and runner subprocesses |
| `webwright_python` | Python used for live `python -m webwright.run.cli` |
| `webwright_root` | Working directory for Webwright config/source |
| `playwright_browsers_path` | Shared browser cache; passed as `PLAYWRIGHT_BROWSERS_PATH` |
| `template_path` | Source template copied into generated projects |
| `webwright_output_root` | Root for Webwright run artifacts |
| `execution_mode` | `native` or `wsl` |
| `base_config` / `model_config` | Webwright config file names |
| `model_name` | Optional model override passed to Webwright for providers where the default model is unavailable |
| `webwright_shell` | Optional native shell path passed as `environment.shell`, primarily Git Bash/bundled bash on Windows |
| `webwright_step_limit` | Optional Webwright agent step cap passed as `agent.step_limit` to prevent unbounded raw-generation retries |
| `webwright_run_timeout_seconds` | Worker-side timeout for live Webwright subprocesses; generated artifacts are harvested before failing or completing |

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `TC_STUDIO_PYTHON` | Explicit Python path selected by Studio |
| `TC_STUDIO_RESOURCES` | Packaged runtime root in bundled mode |
| `TC_STUDIO_RUNTIME_MODE` | `custom` or `bundled` |
| `TC_STUDIO_PLAYWRIGHT_BROWSERS_PATH` | Studio browser cache path; runner may translate this to `PLAYWRIGHT_BROWSERS_PATH` |
| `PLAYWRIGHT_BROWSERS_PATH` | Path consumed by Playwright |
| `TC_HEADLESS` | Generated pytest headless toggle |
| `TC_ENV` | Generated pytest environment name |
| `WEBWRIGHT_MODE` | `live` or `mock` for `prepare-runtime.ps1`; live is the product default |
| `WEBWRIGHT_SOURCE` | optional pinned external Webwright source path for bundled live staging; overrides `third_party/webwright` |
| `WEBWRIGHT_SOURCE_VERSION` | commit SHA, tag, or release identifier for `WEBWRIGHT_SOURCE` |
| `WEBWRIGHT_PIP_PACKAGE` | optional pinned pip requirement, for example `webwright==1.2.3` |
| `WEBWRIGHT_CONFIG_SOURCE` | config source required when using a pip package without a source tree |

## Live Webwright Readiness Contract

The live Webwright gate must prove all of the following:

1. `webwright_root` exists.
2. `base_config` and `model_config` are resolvable from `webwright_root`, unless Webwright package defaults are explicitly documented.
3. `webwright_python --version` works.
4. `webwright_python -m webwright.run.cli --help` or an equivalent import probe succeeds.
5. `webwright_python -m playwright --version` succeeds.
6. The requested browser executable exists under the active Playwright cache, or `python -m playwright install <browser>` can install it.

`base.yaml` alone is not evidence that Webwright is installed. A placeholder
Webwright root may only enable mock/dev mode; it must not make health checks
or live runs report Webwright as ready.

## Mock Mode Contract

Mock raw generation is allowed for demos and local smoke tests, but it must be
explicitly reported:

- Health should show Webwright live readiness as failed or mock-only.
- Webwright run logs should include a clear mock marker.
- E2E tests that validate product readiness must use a real Webwright package
  and must assert that mock mode was not used.

## Generated Project Bootstrap Contract

Before an in-app generated project run, the Worker may call dependency
bootstrap:

```text
python -m pip install -r requirements.txt
python -m playwright install chromium
```

Bootstrap must be fail-fast:

- If `requirements.txt` is missing, stop before runner execution.
- If `pip install` fails, stop before runner execution and return pip output.
- If `python -m playwright install <browser>` fails, stop before runner execution.
- If the browser executable cannot be resolved after install, stop before runner execution.
- Runner API responses and logs must surface the actionable failure reason.

Repeated installs should be avoided through a per-project/runtime readiness
record keyed by generated project path/hash and `RuntimeProfile`.

## Bundled Runtime Layout

Windows bundled runtime is staged under `runtime-staging/` and copied into
Electron `resources/runtime`:

```text
runtime-staging/
  python/
  webwright/
  generated-template/
  ms-playwright/
```

`scripts/prepare-runtime.ps1` must stage:

- embeddable Python with pip enabled,
- Worker requirements,
- generated-template requirements,
- Playwright browser binaries,
- a real Webwright package/source tree when bundled live Webwright is expected.
- `THIRD_PARTY_NOTICES.txt` containing `third_party/NOTICE.md`, the full
  Microsoft Webwright MIT license text, bundled Python license text when available,
  and installed Python package license metadata.

Release policy:

- Product/live bundled runtime defaults to `WEBWRIGHT_MODE=live`.
- The preferred product path is the vendored source at `third_party/webwright`.
  It must keep `LICENSE` and `VENDORED_VERSION.txt`; project-level attribution
  and local patch notes live in `third_party/NOTICE.md`.
- `WEBWRIGHT_SOURCE` plus `WEBWRIGHT_SOURCE_VERSION` remains supported for an
  explicit external source override.
- A pip package is allowed only when it is pinned with `==` or an immutable
  direct reference. If the package does not provide the runtime config files,
  `WEBWRIGHT_CONFIG_SOURCE` must provide `base.yaml` and `model_openai.yaml`.
- If vendored source, external source, and pinned package are all unavailable,
  `prepare-runtime.ps1` fails before staging a live-labeled runtime.
- Mock/dev placeholder staging is allowed only with `-WebwrightMode mock` or
  `WEBWRIGHT_MODE=mock`.

Product `dist:win:full` validation must use real Webwright. Mock/dev staging is
only for demos and local smoke checks.

## Live Webwright E2E Gate

E-09 is an opt-in live gate. It must not pass through mock fallback. Local and
CI environments that want to close E-09 must provide:

| Variable | Required | Purpose |
|----------|----------|---------|
| `TC_LIVE_WEBWRIGHT_ROOT` | optional | external Webwright root override; defaults to settings or `third_party/webwright` |
| `TC_LIVE_WEBWRIGHT_PYTHON` | optional | Python used for `python -m webwright.run.cli`; defaults to `TC_STUDIO_PYTHON` or `python` |
| `TC_LIVE_WEBWRIGHT_BASE_CONFIG` | optional | base config name; defaults to `base.yaml` |
| `TC_LIVE_WEBWRIGHT_MODEL_CONFIG` | optional | model config name; defaults to `model_openai.yaml` |
| `TC_LIVE_PLAYWRIGHT_BROWSERS_PATH` | optional | explicit Playwright browser cache for live validation |

## Installing Live Webwright

Use the vendored Microsoft Webwright source for normal local/product setup:

```powershell
.\scripts\setup-live-webwright.ps1 -UpdateSettings
```

This installs `third_party/webwright` into the selected Python environment by
editable install, installs Playwright Chromium, applies the local Windows patch
if needed, and writes `.data/settings.json`.

An external checkout remains supported when testing a different upstream ref.
The official repository ships `src/webwright/run/cli.py` and configs under
`src/webwright/config/`, and the documented install path is editable install
plus Playwright Chromium:

```powershell
git clone https://github.com/microsoft/Webwright.git .runtime/webwright
cd .runtime/webwright
git rev-parse HEAD
python -m pip install -e .
python -m playwright install chromium
python -c "import importlib.util; raise SystemExit(0 if importlib.util.find_spec('webwright.run.cli') else 1)"
```

Optional explicit path form:

```powershell
.\scripts\setup-live-webwright.ps1 `
  -InstallRoot C:\tools\Webwright `
  -Python C:\Python311\python.exe `
  -WebwrightRef <commit-sha-or-tag> `
  -PlaywrightBrowsersPath C:\tools\ms-playwright `
  -UpdateSettings
```

After install, verify from `apps/worker`:

```powershell
python -m pytest tests/e2e/test_live_webwright_runtime.py -q
```

Before running live generation, export the API key for the selected model
config. A generic root `.env` entry named `API_KEY` is also supported; Studio
maps it to the provider-specific variable from `settings.webwright.apiProvider`
and `settings.webwright.modelConfig`.

| Config | Required env |
|--------|--------------|
| `model_claude.yaml` | `ANTHROPIC_API_KEY` |
| `model_openai.yaml` | `OPENAI_API_KEY` |
| `model_openrouter.yaml` | `OPENROUTER_API_KEY` |

Example:

```powershell
$env:ANTHROPIC_API_KEY = "<secret>"
python -m pytest tests/e2e/test_live_webwright_runtime.py -q
```

The live gate must:

- call `POST /settings/validate` and assert `webwrightCli.ok`,
  `webwrightConfig.ok`, and `mockMode.enabled == false`;
- run `POST /projects/{project_id}/webwright-runs` for a selected TC;
- assert the run completed with `final_script.py`, logs, metadata, indexed
  `RawAction` rows, and `ArtifactAsset` rows;
- assert run logs do not contain the mock marker.

If these variables are not supplied, the E-09 test harness may skip, but the
checklist item remains open.

Verification entry points:

- `apps/worker/tests/e2e/test_live_webwright_runtime.py` for pytest-driven DB
  and artifact indexing assertions.
- `scripts/e2e_live_webwright_runtime.py` for a live Worker HTTP flow using the
  current app settings, or `TC_LIVE_*` environment overrides.
- `scripts/setup-live-webwright.ps1` for vendored/external source install and
  settings update. It defaults to `third_party/webwright` and accepts
  `-InstallRoot` for an external checkout.

### Windows Shell Compatibility

The Microsoft Webwright `base.yaml` config is bash-oriented: it instructs the
agent to emit `bash_command`, sets `environment.shell: /bin/bash`, and validates
commands with `/bin/bash -n`. A native Windows checkout can still pass package,
config, browser, and credential readiness while failing at generation time if
`/bin/bash` is unavailable.

This has been reproduced both through the app's Webwright adapter and through a
README-style direct CLI command from the Webwright checkout. On Windows, the
direct command also needs `PYTHONUTF8=1` or equivalent UTF-8 mode before config
loading reaches the shell validation stage.

`microsoft/Webwright#30` fixes the first Windows blocker by skipping
`_validate_bash_command`'s `/bin/bash -n` syntax check on `sys.platform ==
"win32"`. Local validation shows this is necessary but not sufficient:
`local_workspace.py` also needs a Windows execution path for bash-style
commands. Python's `subprocess.run(command, shell=True, executable=<Git Bash
path with spaces>)` does not work reliably on Windows; Git Bash must be invoked
as an argv list, for example `[bash.exe, "-lc", command]`.

E-09 cannot close on Windows native execution until one explicit strategy is
selected:

- run Webwright through WSL with a Linux Webwright venv and Linux path mapping;
- provide a supported native Git Bash/bundled bash execution path and verify
  Webwright uses it for both command validation and command execution;
- or define a Windows-compatible Webwright config/adapter contract that does not
  require `bash_command`/`/bin/bash` while still producing `final_script.py`.

The Worker should classify this failure separately from timeout, browser, and
credential failures so the user sees an actionable shell/runtime prerequisite.

## Windows Packaging Commands

Baseline installer:

```powershell
npm run build
npm run dist:win
```

Bundled-runtime installer:

```powershell
npm run dist:win:full
```

`dist:win:full` runs `prepare-runtime` first, then packages Electron with
`runtime-staging/` copied into `resources/runtime`.

## Health API Contract

`GET /health` and `POST /settings/validate` should report:

| Key | Meaning |
|-----|---------|
| `runtimeMode` | active mode and resource root |
| `python` | generated runner Python readiness |
| `webwrightPython` | Webwright Python readiness |
| `webwrightCli` | actual `webwright.run.cli` readiness, not config-file presence |
| `webwrightConfig` | base/model config path readiness |
| `webwrightShell` | Windows native Git Bash/bundled bash readiness for bash-style Webwright commands |
| `templatePath` | generated-template path readiness |
| `playwright` | Playwright Python package readiness |
| `playwrightBrowser` | requested browser executable readiness |
| `mockMode` | whether raw generation would fall back to mock |

`allOk` should only be true when the selected runtime mode can perform the
intended live workflow. If mock mode is active, expose a separate mock/dev OK
state instead of conflating it with production readiness.

## Verification Gates

Minimum runtime gates:

- C3-07: live Webwright CLI readiness probe.
- C3-08: vendored Webwright source/package decision.
- C9-06: generated runtime bootstrap fail-fast.
- E-09: live Webwright runtime E2E.
- E-10: generated pytest/browser contract E2E.
- I-08: clean Windows `dist:win:full` validation.

## Implementation Status

Done:

- RuntimeProfile resolver exists.
- Electron passes bundled runtime environment variables.
- `PLAYWRIGHT_BROWSERS_PATH` is passed to subprocesses.
- `prepare-runtime.ps1` stages Python, template requirements, and Chromium.
- generated project bootstrap exists.
- Webwright live readiness uses root, Python, config, and `webwright.run.cli`
  import checks; placeholder `base.yaml` alone does not pass live readiness.
  Config readiness accepts both root-level configs and the official source
  checkout layout `src/webwright/config/*.yaml`.
- Health output separates `webwrightRoot`, `webwrightPython`, `webwrightCli`,
  `webwrightConfig`, and explicit `mockMode`.
- `prepare-runtime.ps1` enforces the Webwright package/source policy: live
  staging fails without a pinned source/package, unpinned pip packages fail, and
  mock staging requires explicit opt-in.
- generated project bootstrap is fail-fast before `runner.cli`: missing files,
  pip failures, Playwright install failures, and browser check failures return
  structured bootstrap status/logs and write run artifacts/results.
- E-09 live Webwright runtime E2E passes locally with a real Microsoft Webwright
  checkout/venv, OpenAI `gpt-5-mini`, Git Bash shell readiness, explicit
  `webwrightShell` health, nested `final_script.py` harvesting, indexed
  `RawAction` rows, artifact indexing, and mock mode disabled.

Open:

- clean Windows bundled runtime E2E must be recorded.
