# Spec Index

Last aligned: 2026-06-06

This index maps product workspaces, implementation areas, and supporting specs.
Implementation progress is tracked in [IMPLEMENTATION_CHECKLIST.md](./IMPLEMENTATION_CHECKLIST.md).

## Product Workspace Map

| Workspace | Purpose | Primary spec docs | Checklist |
|-----------|---------|-------------------|-----------|
| Generate Raw | TC import -> prompt/LLM -> Webwright raw script/actions/artifacts | [RUNTIME_SPEC.md](./RUNTIME_SPEC.md), [API_SPEC.md](./API_SPEC.md) | D3, D4, C1-C5 |
| Automation IDE | Mapping -> structure -> edit -> run -> results -> export | [STRUCTURING_SPEC.md](./STRUCTURING_SPEC.md), [GENERATED_PROJECT_SPEC.md](./GENERATED_PROJECT_SPEC.md), [API_SPEC.md](./API_SPEC.md) | D5-D8, C6-C12 |
| Supporting | Setup, Settings, runtime, installer, app shell | [PRODUCT_PILLARS.md](./PRODUCT_PILLARS.md), [RUNTIME_SPEC.md](./RUNTIME_SPEC.md) | D1, D2, D9, A3, I |

## Source Of Truth Documents

| Document | Purpose | Main checklist area | Workspace |
|----------|---------|---------------------|-----------|
| [PRODUCT_PILLARS.md](./PRODUCT_PILLARS.md) | product pillars, workspace model, handoff contract | All | All |
| [RUNTIME_SPEC.md](./RUNTIME_SPEC.md) | RuntimeProfile, Python/Webwright/Playwright readiness, bundled/custom runtime, bootstrap fail-fast | C3-07, C3-08, C9-06, C9-07, E-09, I-08 | Generate Raw + Automation IDE + Supporting |
| [API_SPEC.md](./API_SPEC.md) | Local Worker HTTP/WebSocket contract | A5, C1, C4, C6-C12 | W1 + W2 + shared |
| [STRUCTURING_SPEC.md](./STRUCTURING_SPEC.md) | raw script/actions -> structured flow/POM/test generation | C5-C8, C7-11, C8-07 | Automation IDE |
| [DB_SCHEMA.md](./DB_SCHEMA.md) | relational DB schema | A2, C6-C8, C11 | W1 + W2 |
| [GENERATED_PROJECT_SPEC.md](./GENERATED_PROJECT_SPEC.md) | standalone Playwright pytest project, fixture policy, runner contract | B1-B4, B2-08, B3-04, C8-C10, E-10 | Automation IDE output |

## Supporting Guides

These documents should not redefine core contracts. They point back to the
source-of-truth documents above.

| Document | Purpose | Owns new checklist items? |
|----------|---------|---------------------------|
| [SCREEN_INVENTORY.md](./SCREEN_INVENTORY.md) | GUI surfaces and connected APIs | No, references D items |
| [UI_UX_DIRECTION.md](./UI_UX_DIRECTION.md) | UI direction for the two workspaces | No, references D items |
| [SELF_HEALING_SPEC.md](./SELF_HEALING_SPEC.md) | healing flow detail under Automation IDE | Yes, C12 only |
| [WORKFLOW_SPEC.md](./WORKFLOW_SPEC.md) | E2E sequence and acceptance notes | No, references E/H items |
| [NEXT_ACTIONS.md](./NEXT_ACTIONS.md) | AI operating queue for the next implementation batch | No, points to one checklist item |

## Post-MVP Checklist Follow-ups

After the 2026-06-06 docs audit, [IMPLEMENTATION_CHECKLIST.md](./IMPLEMENTATION_CHECKLIST.md)
tracked additional rows for:

- subprocess cancel depth (`C3-09`, `C9-08`);
- Generate Raw Worker C2 prompt API wiring (`D4-07`);
- API_SPEC Planned/Partial endpoints (`C7-13`, `C12-11`, `C12-12`);
- real TestRail/Sheets connector depth (`C1-08`, `C1-09`, `C10-07`, `C10-08`, `G-04`);
- optional extensions in section **J. Post-MVP**.

These tracked follow-ups are complete as of 2026-06-13. New work should be
added first to the owning source-of-truth spec and checklist, then queued in
[NEXT_ACTIONS.md](./NEXT_ACTIONS.md).

## Runtime Planning Correction

The 2026-06-03 correction adds explicit planning for:

- real Webwright CLI readiness instead of placeholder config detection;
- Python/Playwright browser requirements for both raw generation and generated project execution;
- generated-template pytest fixture/browser policy;
- raw-script-to-structured-project method body planning;
- generated file origin links and stale/conflict protection;
- clean Windows bundled runtime validation.

## Source Of Truth Rule

- Product workspace IA and handoff: [PRODUCT_PILLARS.md](./PRODUCT_PILLARS.md).
- Runtime paths and readiness: [RUNTIME_SPEC.md](./RUNTIME_SPEC.md).
- Generated pytest project contract: [GENERATED_PROJECT_SPEC.md](./GENERATED_PROJECT_SPEC.md).
- Raw-to-structured transformation: [STRUCTURING_SPEC.md](./STRUCTURING_SPEC.md).
- Database schema: [DB_SCHEMA.md](./DB_SCHEMA.md).
- API shape: [API_SPEC.md](./API_SPEC.md).
- Implementation status: [IMPLEMENTATION_CHECKLIST.md](./IMPLEMENTATION_CHECKLIST.md).
- AI operating queue: [NEXT_ACTIONS.md](./NEXT_ACTIONS.md).

When code and docs disagree, update the relevant spec and checklist in the same
work item so future implementation does not hide planning gaps.
