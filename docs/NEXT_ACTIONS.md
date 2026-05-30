# Next Actions

Last aligned: 2026-05-30

Goal: keep the next development batch to roughly one PR. Direction lives in [webwright_automation_generator_architecture.md](../webwright_automation_generator_architecture.md). Progress should be tracked by flipping exactly one line in [IMPLEMENTATION_CHECKLIST.md](./IMPLEMENTATION_CHECKLIST.md) from `[ ]` to `[x]`.

**`[x]` = baseline shipped, not full product parity.** A checked line means the architecture-level baseline for that item exists and has been verified enough to support the next dependent checklist line.

## Spec Sources

- [Architecture](../webwright_automation_generator_architecture.md): product definition, system boundaries, TC-centered flow, GUI/worker/generated-project responsibilities.
- [Spec Index](./SPEC_INDEX.md): implementation-facing spec document map.
- [Product Workspaces](./PRODUCT_PILLARS.md): top-level 2-workspace product structure.
- [API Spec](./API_SPEC.md): Local Worker HTTP/WebSocket contract.
- [Screen Inventory](./SCREEN_INVENTORY.md): GUI screen responsibilities and connected APIs.
- [UI/UX Direction](./UI_UX_DIRECTION.md): Cursor-inspired IDE/workbench interaction direction.
- [Data Model Spec](./DATA_MODEL_SPEC.md): SQLite/SQLModel entity contracts.
- [Structuring Spec](./STRUCTURING_SPEC.md): Webwright raw code to normalized flow/POM/test conversion contract.
- [Self-Healing Spec](./SELF_HEALING_SPEC.md): artifact-backed selector healing and failure diagnosis contract.
- [DB Schema](./DB_SCHEMA.md): relational schema needed for durable structuring and regeneration.
- [Generated Project Spec](./GENERATED_PROJECT_SPEC.md): generated Playwright/pytest project contract.
- [Workflow Spec](./WORKFLOW_SPEC.md): E2E workflow sequence and acceptance criteria.
- [Implementation Checklist](./IMPLEMENTATION_CHECKLIST.md): execution order, phase, layer, and dependency tracking.

## Loop

1. Implement or verify only the unchecked checklist line named in **Current batch**.
2. When it ships, flip only that line to `[x]` and add a short parenthetical note.
3. Do not add new checklist lines for polish inside an already completed area.
4. Pick the next unchecked line from **Next batch candidates** and replace **Current batch** with it.

---

## Current batch

**Section:** A1. Monorepo / DevEnv

**Checklist line (exact line done when this is `[x]`):**

- [ ] **A1-04** 통합 dev 스크립트 — §4.1 | Phase 0 | Layer: Infra | Depends: A1-02, A1-03

### Scope (only what closes the line above)

- Verify root `package.json` provides a single entry to run worker + desktop together (`npm run dev`) and separate targets (`dev:worker`, `dev:desktop`).
- Confirm `install:worker` installs Python deps and both dev targets start without manual path hacks.
- If already present, close the checklist line with a short note such as `(baseline scaffold verified)`.

### Out of scope for this batch

- Production packaging, CI pipelines, or Docker.
- Worker auto-start from Electron main process (A4-01).
- README/version pinning polish (A1-05).
- Marking multiple already-present checklist lines in the same PR.

---

## Next batch candidates

Pick only unchecked lines from below when replacing **Current batch**.

| Suggested order | Section | Checklist line |
|-----------------|---------|----------------|
| 1 | A1 | A1-05 루트 README, `.gitignore`, Python/Node 버전 고정 — §15 |
| 2 | A4 | A4-01 Worker subprocess 자동 기동 — §5.2 |

## Review Notes

- `IMPLEMENTATION_CHECKLIST.md` is currently the authoritative progress tracker, but it appears behind the repository state because all lines are unchecked while baseline files already exist.
- Raw-to-structured conversion needs its own schema work before C7/C8 can be considered durable; see `STRUCTURING_SPEC.md` and `DB_SCHEMA.md`.
- UI work should be organized around the two product workspaces, not a flat list of tabs; see `PRODUCT_PILLARS.md`.
- Prefer small sync PRs that verify and mark one baseline at a time before moving into deeper Phase 1 feature work.
- Keep each batch tied to the architecture principle it supports: TC as the center, Webwright raw code as material, GUI as orchestrator, worker as local service, and generated project as independently runnable automation.
