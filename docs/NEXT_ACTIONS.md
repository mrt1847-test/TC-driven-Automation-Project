# Next Actions

Last aligned: 2026-06-02

Goal: keep the next development batch to roughly one PR. Direction lives in [webwright_automation_generator_architecture.md](../webwright_automation_generator_architecture.md). **Product workspace IA** lives in [PRODUCT_PILLARS.md](./PRODUCT_PILLARS.md). Progress should be tracked by flipping exactly one line in [IMPLEMENTATION_CHECKLIST.md](./IMPLEMENTATION_CHECKLIST.md) from `[ ]` to `[x]`.

**`[x]` = baseline shipped, not full product parity.** A checked line means the architecture-level baseline for that item exists and has been verified enough to support the next dependent checklist line.

## Spec Sources

- [Architecture](../webwright_automation_generator_architecture.md): product definition, system boundaries, TC-centered flow, GUI/worker/generated-project responsibilities.
- [Spec Index](./SPEC_INDEX.md): implementation-facing spec document map and workspace map.
- [Product Workspaces](./PRODUCT_PILLARS.md): top-level 2-workspace product structure, handoff, completion signals.
- [API Spec](./API_SPEC.md): Local Worker HTTP/WebSocket contract.
- [Screen Inventory](./SCREEN_INVENTORY.md): GUI screen responsibilities and connected APIs.
- [UI/UX Direction](./UI_UX_DIRECTION.md): Cursor-inspired IDE/workbench interaction direction.
- [Data Model Spec](./DATA_MODEL_SPEC.md): SQLite/SQLModel entity contracts.
- [Structuring Spec](./STRUCTURING_SPEC.md): Webwright raw code to normalized flow/POM/test conversion contract.
- [Self-Healing Spec](./SELF_HEALING_SPEC.md): artifact-backed selector healing and failure diagnosis contract.
- [DB Schema](./DB_SCHEMA.md): relational schema needed for durable structuring and regeneration.
- [Generated Project Spec](./GENERATED_PROJECT_SPEC.md): generated Playwright/pytest project contract.
- [CI Standalone Guide](./CI_STANDALONE_GUIDE.md): generated project standalone CI command order, artifacts, and environment notes.
- [Windows Installer Guide](./WINDOWS_INSTALLER.md): Electron Windows packaging path, prerequisites, output, and signing limitations.
- [Workflow Spec](./WORKFLOW_SPEC.md): E2E workflow sequence and acceptance criteria.
- [Implementation Checklist](./IMPLEMENTATION_CHECKLIST.md): execution order, phase, layer, and dependency tracking.

## Loop

1. Implement or verify only the unchecked checklist line named in **Current batch**.
2. When it ships, flip only that line to `[x]` and add a short parenthetical note.
3. Do not add new checklist lines for polish inside an already completed area.
4. Pick the next unchecked line from **Next batch candidates** and replace **Current batch** with it.

---

## Current batch

**Section:** C. Worker Service / Artifact-backed Self-Healing

**Checklist line (exact line done when this is `[x]`):**

- [ ] **C12-04** failure → structured step/POM method link resolver — Spec: SELF_HEALING_SPEC | Phase 2 | Layer: Worker | Depends: C7-08, C12-03

### Scope (only what closes the line above)

- Add a lightweight resolver that links failed execution result context to likely `StructuredStep` / `PageObjectMethod` rows.
- Use automation key plus persisted mappings/structured/page object metadata where available.
- Persist or return resolver metadata enough for later healing proposal generation.
- Keep existing execution artifact indexing and result detail behavior working.
- When it ships, close the checklist line with a short note such as `(baseline failure-to-structure resolver verified)`.

### Out of scope for this batch

- Healing proposal generation APIs.
- Accept/apply/regenerate/rerun behavior.
- GUI evidence viewer changes.
- Automatic selector scoring/patching.
- Marking multiple already-present checklist lines in the same PR.

---

## Next batch candidates

Pick only unchecked lines from below when replacing **Current batch**.

| Suggested order | Section | Checklist line |
|-----------------|---------|----------------|
| 1 | C | C12-05 healing proposal generation API — Spec: SELF_HEALING_SPEC, API_SPEC |
| 2 | C | C12-06 accepted proposal apply/regenerate/rerun flow — Spec: SELF_HEALING_SPEC |

## Review Notes

- All docs under `docs/` are aligned to [PRODUCT_PILLARS.md](./PRODUCT_PILLARS.md) as of 2026-05-31 (workspace map, handoff, nav IA).
- GUI implementation should follow **Generate Raw** vs **Automation IDE** grouping; Runner/Results/Export are IDE panels, not peer workspaces.
- Raw-to-structured conversion needs schema work before C7/C8 are durable; see `STRUCTURING_SPEC.md` and `DB_SCHEMA.md`.
- Prefer small sync PRs that verify and mark one baseline at a time before moving into deeper Phase 1 feature work.
- Keep each batch tied to the architecture principle it supports: TC as the center, Webwright raw code as material, GUI as orchestrator, worker as local service, and generated project as independently runnable automation.
