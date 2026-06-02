# CI Standalone Guide

Last aligned: 2026-06-02

This guide describes how to run a generated automation project without the
desktop GUI or Local Worker. The commands are CI-provider neutral and can be
used in GitHub Actions, Jenkins, GitLab CI, Azure Pipelines, or a local shell.

## Scope

Use this guide after the Worker has generated a project into a directory such
as `generated/`.

The generated project owns executable pytest tests, `runner.cli`,
`mappings/cases.yaml`, `artifacts/runs/{runId}/results.json`, and export
adapters. The parent Studio app may generate, edit, or launch the project, but
CI should only need the generated project folder plus Python.

## Prerequisites

Run these commands from the generated project root.

```bash
python --version
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m playwright install chromium
```

For CI caching, keep Playwright browser cache outside the workspace when your
provider supports it:

```bash
export PLAYWRIGHT_BROWSERS_PATH="$HOME/.cache/ms-playwright"
```

On Windows PowerShell:

```powershell
$env:PLAYWRIGHT_BROWSERS_PATH="$env:USERPROFILE\.cache\ms-playwright"
```

## Health Check

Before running tests, verify that the generated project has the minimum files
expected by the Studio Worker project health check:

```text
requirements.txt
runner/cli.py
mappings/cases.yaml
```

When the Local Worker is available, the equivalent API is:

```bash
curl -X POST "http://127.0.0.1:8765/projects/{projectId}/health?generated_path=/path/to/generated"
```

Without the Worker, use a shell check in CI:

```bash
test -f requirements.txt
test -f runner/cli.py
test -f mappings/cases.yaml
```

## Environment

`runner.cli run` passes the selected environment to pytest as `TC_ENV`.

```bash
python -m runner.cli run --env stg --browser chromium --all
```

Generated tests and fixtures may read:

- `TC_ENV`: selected environment name, such as `local`, `stg`, or `prod`
- `PLAYWRIGHT_BROWSERS_PATH`: optional CI cache path for Playwright browsers
- target-specific secrets: CI secret variables consumed by custom export adapters or test code

Do not commit API keys, passwords, cookies, or service account JSON into the
generated project. Store secrets in your CI provider and read them from
environment variables.

## Runner Commands

List known cases:

```bash
python -m runner.cli list-cases
```

Run all cases:

```bash
python -m runner.cli run --env stg --browser chromium --all
```

Run one case by automation key:

```bash
python -m runner.cli run --env stg --browser chromium --case-key sample_case_001
```

Pin a CI run ID for predictable artifact paths:

```bash
python -m runner.cli run --env stg --browser chromium --all --run-id "$CI_RUN_ID"
```

Rerun only failed cases from a previous run:

```bash
python -m runner.cli rerun-failed --from-run-id "$CI_RUN_ID" --run-id "$CI_RUN_ID-rerun"
```

Export a completed run:

```bash
python -m runner.cli export --run-id "$CI_RUN_ID" --target testrail-clone
python -m runner.cli export --run-id "$CI_RUN_ID" --target testrail
python -m runner.cli export --run-id "$CI_RUN_ID" --target excel
python -m runner.cli export --run-id "$CI_RUN_ID" --target google-sheets
```

Current baseline behavior:

- `testrail-clone` posts to `http://localhost:3000` by default.
- `testrail` and `google-sheets` are stub adapters in the generated template.
- `excel` writes back to files referenced by `mappings/cases.yaml`.
- `runner.cli export` currently performs write-back; preview-first behavior is available through the Worker export APIs, not the standalone template CLI.

## Artifacts

Each run writes:

```text
artifacts/
  runs/
    {runId}/
      results.json
```

`results.json` contains `runId`, `env`, `browser`, summary counts, and `cases[]`
with each case's `automationKey`, source metadata, status, duration, error, and
artifact paths.

Archive this directory as a CI artifact:

```bash
tar -czf automation-artifacts.tgz artifacts/runs
```

On Windows PowerShell:

```powershell
Compress-Archive -Path artifacts\runs -DestinationPath automation-artifacts.zip -Force
```

## Minimal CI Shape

```yaml
steps:
  - checkout
  - setup-python
  - run: python -m pip install --upgrade pip
  - run: python -m pip install -r requirements.txt
  - run: python -m playwright install chromium
  - run: test -f runner/cli.py && test -f mappings/cases.yaml
  - run: python -m runner.cli list-cases
  - run: python -m runner.cli run --env stg --browser chromium --all --run-id "$CI_RUN_ID"
  - archive: artifacts/runs
```

## Troubleshooting

- `unrecognized arguments: --browser=chromium --headed=false`: install `pytest-playwright` from `requirements.txt`.
- `Previous run not found`: confirm the previous run ID exists under `artifacts/runs/{runId}/results.json`.
- `Run not found`: export needs an existing run ID under `artifacts/runs`.
- Browser executable missing: run `python -m playwright install chromium`, and verify the CI cache did not restore a partial browser install.
- No cases listed: inspect `mappings/cases.yaml`; `runner.cli` reads that file directly.

## Verification Status

This guide is aligned to the current generated-template CLI:

- `list-cases`
- `run --all`
- `run --case-key`
- `run --run-id`
- `rerun-failed --from-run-id`
- `export --run-id --target`

Checklist note: I-04 documents the baseline CI contract. B2-07 is covered by
`npm run e2e:cli-standalone`, which exercises these commands directly against a
temporary generated project without the Worker.
