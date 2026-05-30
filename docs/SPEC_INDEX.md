# Spec Index

Last aligned: 2026-05-31

이 폴더의 스펙 문서는 [Architecture](../webwright_automation_generator_architecture.md)를 구현 가능한 단위로 쪼갠 보조 문서다. **제품 정보구조의 기준은 [PRODUCT_PILLARS.md](./PRODUCT_PILLARS.md)** 이다. 구현 진행은 [Implementation Checklist](./IMPLEMENTATION_CHECKLIST.md)와 [Next Actions](./NEXT_ACTIONS.md)를 기준으로 추적한다.

## Product Workspace Map

모든 GUI·워크플로·화면 문서는 아래 2-workspace 모델을 따른다. flat tab 목록이 아니라 workspace 단위로 읽는다.

| Workspace | Purpose | Primary spec docs | Checklist |
|-----------|---------|-------------------|-----------|
| **Generate Raw** | TC import → LLM/prompt → Webwright raw code/action/artifact | SCREEN_INVENTORY (W1), UI_UX_DIRECTION, WORKFLOW 1–2, API (Cases, Webwright, Prompt) | D3, D4, C1–C5 |
| **Automation IDE** | Mapping → structure → edit → run → results → export | SCREEN_INVENTORY (W2), STRUCTURING_SPEC, GENERATED_PROJECT_SPEC, WORKFLOW 3–6 | D5–D8, C6–C12 |
| **Supporting** | Setup, Settings, global shell | SCREEN_INVENTORY (Setup/Settings), UI_UX_DIRECTION | D1–D2, D9, A3 |

Handoff contract: [PRODUCT_PILLARS.md — Handoff Contract](./PRODUCT_PILLARS.md#handoff-contract)

## Documents

| Document | Purpose | Main checklist area | Workspace |
|----------|---------|---------------------|-----------|
| [PRODUCT_PILLARS.md](./PRODUCT_PILLARS.md) | 2-workspace 최상위 정보구조, handoff, completion signal | All | All |
| [API_SPEC.md](./API_SPEC.md) | Local Worker HTTP/WebSocket API 계약 | A5, C1, C4, C6, C8, C9, C10, C11 | W1 + W2 + shared |
| [SCREEN_INVENTORY.md](./SCREEN_INVENTORY.md) | GUI 화면, workspace별 surface, 연결 API | D1-D9 | W1 + W2 + supporting |
| [UI_UX_DIRECTION.md](./UI_UX_DIRECTION.md) | Cursor-inspired 2-workspace IDE UX | D1-D9 | W1 + W2 |
| [DATA_MODEL_SPEC.md](./DATA_MODEL_SPEC.md) | SQLite/SQLModel 엔티티와 상태 모델 | A2, C 계열 | W1 outputs → W2 inputs |
| [STRUCTURING_SPEC.md](./STRUCTURING_SPEC.md) | raw → flow/POM/test 구조화 | C5-C8 | Automation IDE |
| [SELF_HEALING_SPEC.md](./SELF_HEALING_SPEC.md) | artifact-backed selector healing | C12, D5-D8 | Automation IDE |
| [DB_SCHEMA.md](./DB_SCHEMA.md) | 관계형 DB DDL | A2, C6-C8, C11 | W1 + W2 |
| [GENERATED_PROJECT_SPEC.md](./GENERATED_PROJECT_SPEC.md) | 독립 실행 Playwright/pytest 프로젝트 | B1-B4, C8-C10 | Automation IDE output |
| [WORKFLOW_SPEC.md](./WORKFLOW_SPEC.md) | workspace별 E2E 흐름과 완료 조건 | E1-E8, H1-H4 | W1 + W2 |

## Source Of Truth Rule

- **제품 workspace IA와 handoff**는 PRODUCT_PILLARS를 따른다.
- **시스템 경계와 서비스 책임**은 architecture 문서를 따른다.
- **실제 진행 상태**는 implementation checklist의 체크박스를 따른다.
- 이 스펙 문서들은 구현자가 PR 범위를 잡을 때 보는 계약서다.
- 코드와 문서가 다르면 해당 PR에서 하나의 체크리스트 라인 범위 안에서 맞춘다.
