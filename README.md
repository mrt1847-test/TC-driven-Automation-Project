# TC-driven Automation Project Studio

Local QA automation IDE for turning imported test cases into Webwright raw
scripts, then into structured Playwright pytest automation projects that can be
edited, run, and exported.

The product is organized around two user-facing workspaces:

1. **Generate Raw** - import TCs, compose prompts, generate Webwright raw scripts,
   actions, and artifacts.
2. **Automation IDE** - map raw actions, structure flows/page objects, edit the
   generated project, run tests, inspect results, and export.

Setup Wizard and Settings are supporting surfaces, not separate product
workspaces.

## Documentation

Start here:

- [Spec Index](docs/SPEC_INDEX.md) - source-of-truth map and document ownership
- [Next Actions](docs/NEXT_ACTIONS.md) - AI operating queue for the next implementation batch
- [Implementation Checklist](docs/IMPLEMENTATION_CHECKLIST.md) - implementation status and next work items
- [Architecture](webwright_automation_generator_architecture.md) - long-form product/system design

Core contracts:

- [Runtime Spec](docs/RUNTIME_SPEC.md) - Python/Webwright/Playwright runtime contract
- [Structuring Spec](docs/STRUCTURING_SPEC.md) - raw script/actions to structured project
- [Generated Project Spec](docs/GENERATED_PROJECT_SPEC.md) - generated pytest project contract
- [API Spec](docs/API_SPEC.md) - Local Worker HTTP/WebSocket contract

Supporting guides are linked from [Spec Index](docs/SPEC_INDEX.md) only.

## Structure

```text
apps/desktop/                 Electron + React GUI
apps/worker/                  FastAPI local worker
packages/generated-template/  Playwright pytest project template
docs/                         product, runtime, API, and implementation docs
```

## Requirements

- Node.js 20+ (see `.nvmrc` and `package.json` engines)
- Python 3.11+ (see `.python-version`)
- Optional: real Webwright CLI/package for live raw generation

## Development

Install Worker dependencies:

```bash
npm run install:worker
```

Install Node dependencies:

```bash
npm install
```

Run Worker and Desktop together:

```bash
npm run dev
```

Run Worker only:

```bash
cd apps/worker
python -m uvicorn worker.main:app --reload --port 8765
```

Generated template CLI smoke:

```bash
cd packages/generated-template
pip install -r requirements.txt
python -m runner.cli list-cases
```

## Windows Installer

```powershell
npm run build
npm run dist:win
```

Bundled runtime path:

```powershell
npm run dist:win:full
```

Installer artifacts are written to `apps/desktop/release/`. Runtime packaging
requirements are defined in [Runtime Spec](docs/RUNTIME_SPEC.md).

## Third-Party Software

This project vendors Microsoft Webwright (MIT) for live raw generation.

- [third_party/NOTICE.md](third_party/NOTICE.md) — attribution, citation, local patches
- [docs/THIRD_PARTY_LEGAL.md](docs/THIRD_PARTY_LEGAL.md) — compliance checklist and bundled notices

Validate before release:

```powershell
npm run validate:third-party
```

## Runtime

- Worker API: `http://127.0.0.1:8765`
- Desktop dev: Electron + Vite renderer
