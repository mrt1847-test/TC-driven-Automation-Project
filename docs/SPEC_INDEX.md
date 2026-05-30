# Spec Index

Last aligned: 2026-05-30

이 폴더의 스펙 문서는 [Architecture](../webwright_automation_generator_architecture.md)를 구현 가능한 단위로 쪼갠 보조 문서다. 구현 진행은 [Implementation Checklist](./IMPLEMENTATION_CHECKLIST.md)와 [Next Actions](./NEXT_ACTIONS.md)를 기준으로 추적한다.

## Documents

| Document | Purpose | Main checklist area |
|----------|---------|---------------------|
| [PRODUCT_PILLARS.md](./PRODUCT_PILLARS.md) | 제품을 2개 큰 작업공간으로 나누는 최상위 정보구조 | All |
| [API_SPEC.md](./API_SPEC.md) | Local Worker HTTP/WebSocket API 계약 | A5, C1, C4, C6, C8, C9, C10, C11 |
| [SCREEN_INVENTORY.md](./SCREEN_INVENTORY.md) | Electron GUI 화면 목록, 책임, 연결 API | D1-D9 |
| [UI_UX_DIRECTION.md](./UI_UX_DIRECTION.md) | Cursor를 참고한 IDE형 작업공간 UI/UX 방향 | D1-D9 |
| [DATA_MODEL_SPEC.md](./DATA_MODEL_SPEC.md) | SQLite/SQLModel 엔티티와 상태 모델 | A2, C 계열 |
| [STRUCTURING_SPEC.md](./STRUCTURING_SPEC.md) | Webwright raw code를 normalized flow/POM/test로 바꾸는 구조화 계약 | C5-C8 |
| [SELF_HEALING_SPEC.md](./SELF_HEALING_SPEC.md) | Webwright/runner artifacts를 구조화 이후 selector healing에 활용하는 계약 | C12, D5-D8 |
| [DB_SCHEMA.md](./DB_SCHEMA.md) | 구조화까지 포함한 관계형 DB DDL | A2, C6-C8, C11 |
| [GENERATED_PROJECT_SPEC.md](./GENERATED_PROJECT_SPEC.md) | 생성되는 Playwright/pytest 프로젝트 구조와 CLI 계약 | B1-B4, C8-C10 |
| [WORKFLOW_SPEC.md](./WORKFLOW_SPEC.md) | 주요 E2E 흐름과 완료 조건 | E1-E6, H1-H4 |

## Source Of Truth Rule

- 제품 방향과 경계는 architecture 문서를 따른다.
- 실제 진행 상태는 implementation checklist의 체크박스를 따른다.
- 이 스펙 문서들은 구현자가 PR 범위를 잡을 때 보는 계약서다.
- 코드와 문서가 다르면 해당 PR에서 하나의 체크리스트 라인 범위 안에서 맞춘다.
