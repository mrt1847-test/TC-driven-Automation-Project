# TC-driven Automation Project Studio

TestRail, Excel, Google Sheets 등의 TC를 Webwright raw code로 변환하고, 구조화된 Playwright 자동화 프로젝트를 생성·실행·결과 반영하는 로컬 QA 자동화 IDE.

## 문서

- [Architecture](webwright_automation_generator_architecture.md)
- [Spec Index](docs/SPEC_INDEX.md)
- [Product Workspaces](docs/PRODUCT_PILLARS.md)
- [API Spec](docs/API_SPEC.md)
- [Screen Inventory](docs/SCREEN_INVENTORY.md)
- [UI/UX Direction](docs/UI_UX_DIRECTION.md)
- [Data Model Spec](docs/DATA_MODEL_SPEC.md)
- [Structuring Spec](docs/STRUCTURING_SPEC.md)
- [Self-Healing Spec](docs/SELF_HEALING_SPEC.md)
- [DB Schema](docs/DB_SCHEMA.md)
- [Generated Project Spec](docs/GENERATED_PROJECT_SPEC.md)
- [Workflow Spec](docs/WORKFLOW_SPEC.md)
- [Implementation Checklist](docs/IMPLEMENTATION_CHECKLIST.md)
- [Next Actions](docs/NEXT_ACTIONS.md)

## 구조

```text
apps/desktop/              Electron + React GUI
apps/worker/               FastAPI local worker
packages/generated-template/  Playwright pytest project template
```

## 요구사항

- Node.js 20+
- Python 3.11+
- (선택) Webwright CLI 설치 환경

## 개발 실행

```bash
# Worker 의존성
npm run install:worker

# Desktop 의존성
npm install

# Worker + Desktop 동시 실행
npm run dev
```

Worker만 실행:

```bash
cd apps/worker && python -m uvicorn worker.main:app --reload --port 8765
```

Generated template CLI:

```bash
cd packages/generated-template
pip install -r requirements.txt
python -m runner.cli list-cases
```

## 환경

- Worker API: `http://127.0.0.1:8765`
- Desktop dev: Vite dev server (Electron)
