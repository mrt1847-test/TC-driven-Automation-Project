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
| `WEBWRIGHT_SOURCE` | pinned Webwright source/submodule path for bundled live staging |
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
- a real, pinned Webwright package or source tree when bundled live Webwright is expected.

Release policy:

- Product/live bundled runtime defaults to `WEBWRIGHT_MODE=live`.
- Live staging requires either `WEBWRIGHT_SOURCE` plus
  `WEBWRIGHT_SOURCE_VERSION`, or a pinned `WEBWRIGHT_PIP_PACKAGE`.
- The preferred product path is a bundled Webwright source/submodule identified
  by `WEBWRIGHT_SOURCE_VERSION`.
- A pip package is allowed only when it is pinned with `==` or an immutable
  direct reference. If the package does not provide the runtime config files,
  `WEBWRIGHT_CONFIG_SOURCE` must provide `base.yaml` and `model_openai.yaml`.
- If neither source nor pinned package is provided, `prepare-runtime.ps1` fails
  before staging a live-labeled runtime.
- Mock/dev placeholder staging is allowed only with `-WebwrightMode mock` or
  `WEBWRIGHT_MODE=mock`.

Product `dist:win:full` validation must use real Webwright. Mock/dev staging is
only for demos and local smoke checks.

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
- C3-08: pinned Webwright source/package decision.
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
- Health output separates `webwrightRoot`, `webwrightPython`, `webwrightCli`,
  `webwrightConfig`, and explicit `mockMode`.
- `prepare-runtime.ps1` enforces the Webwright package/source policy: live
  staging fails without a pinned source/package, unpinned pip packages fail, and
  mock staging requires explicit opt-in.
- generated project bootstrap is fail-fast before `runner.cli`: missing files,
  pip failures, Playwright install failures, and browser check failures return
  structured bootstrap status/logs and write run artifacts/results.

Open:

- clean Windows bundled runtime E2E must be recorded.
