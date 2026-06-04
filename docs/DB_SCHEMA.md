# DB Schema

Last aligned: 2026-06-05

This document defines the relational schema needed to support TC import, Webwright raw action extraction, mapping review, structuring, project generation, execution, and result export.

The current code already has a baseline subset. The schema below is the intended contract for the next durable implementation.

**Product workspace map** ([PRODUCT_PILLARS.md](./PRODUCT_PILLARS.md)):

| Layer | Tables | Workspace |
|-------|--------|-----------|
| Project shell | `schema_versions`, `projects` | Shared |
| Generate Raw | `test_cases`, `webwright_runs`, `raw_actions`, artifact metadata | Generate Raw |
| Automation IDE | `case_action_mappings`, `structured_flows`, `structured_steps`, `page_objects`, `page_object_methods`, `generated_files`, `execution_runs`, `execution_results`, `export_logs`, healing tables | Automation IDE |

## Schema Principles

- SQLite is the local relational store.
- File contents live on disk; DB stores paths, relations, statuses, hashes, and structured metadata.
- `automation_key` is a stable cross-table lookup key, but internal relations should use IDs.
- Use JSON columns only for flexible source payloads or low-value metadata, not for core relations.
- Every generated artifact should be traceable back to TC and raw action origins.
- Webwright and runner artifacts are first-class metadata for review and self-healing, but file bytes stay on disk.

## Core Tables

```sql
CREATE TABLE schema_versions (
  id TEXT PRIMARY KEY,
  version INTEGER NOT NULL,
  description TEXT,
  applied_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE projects (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  root_path TEXT NOT NULL,
  generated_project_path TEXT,
  default_env TEXT NOT NULL DEFAULT 'stg',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE test_cases (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  source_type TEXT NOT NULL,
  source_case_id TEXT NOT NULL,
  source_location_json TEXT,
  title TEXT NOT NULL,
  preconditions_json TEXT,
  steps_json TEXT NOT NULL DEFAULT '[]',
  expected_result TEXT,
  automation_key TEXT NOT NULL,
  tags_json TEXT,
  priority TEXT,
  start_url TEXT,
  status TEXT NOT NULL DEFAULT 'imported',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(project_id, automation_key)
);

CREATE INDEX idx_test_cases_project_status ON test_cases(project_id, status);
CREATE INDEX idx_test_cases_source ON test_cases(project_id, source_type, source_case_id);
```

## Webwright Raw Layer

```sql
CREATE TABLE webwright_runs (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  test_case_id TEXT NOT NULL REFERENCES test_cases(id) ON DELETE CASCADE,
  automation_key TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  output_path TEXT,
  final_script_path TEXT,
  trajectory_path TEXT,
  error_message TEXT,
  started_at TEXT,
  ended_at TEXT,
  created_at TEXT NOT NULL
);

CREATE INDEX idx_webwright_runs_case_created ON webwright_runs(test_case_id, created_at);
CREATE INDEX idx_webwright_runs_project_status ON webwright_runs(project_id, status);

CREATE TABLE raw_actions (
  id TEXT PRIMARY KEY,
  webwright_run_id TEXT NOT NULL REFERENCES webwright_runs(id) ON DELETE CASCADE,
  automation_key TEXT NOT NULL,
  order_index INTEGER NOT NULL,
  type TEXT NOT NULL,
  target TEXT,
  selector TEXT,
  value TEXT,
  source_line INTEGER,
  confidence REAL,
  metadata_json TEXT,
  created_at TEXT NOT NULL
);

CREATE INDEX idx_raw_actions_run_order ON raw_actions(webwright_run_id, order_index);
CREATE INDEX idx_raw_actions_key ON raw_actions(automation_key);
```

## Artifact And Healing Layer

```sql
CREATE TABLE artifact_assets (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  automation_key TEXT,
  source_type TEXT NOT NULL,
  source_id TEXT,
  artifact_type TEXT NOT NULL,
  file_path TEXT NOT NULL,
  content_hash TEXT,
  metadata_json TEXT,
  created_at TEXT NOT NULL
);

CREATE INDEX idx_artifact_assets_key ON artifact_assets(project_id, automation_key);
CREATE INDEX idx_artifact_assets_source ON artifact_assets(source_type, source_id);

CREATE TABLE selector_candidates (
  id TEXT PRIMARY KEY,
  raw_action_id TEXT REFERENCES raw_actions(id) ON DELETE CASCADE,
  page_object_method_id TEXT,
  selector_type TEXT NOT NULL,
  selector_value TEXT NOT NULL,
  confidence REAL NOT NULL DEFAULT 0,
  source_artifact_id TEXT REFERENCES artifact_assets(id) ON DELETE SET NULL,
  metadata_json TEXT,
  created_at TEXT NOT NULL
);

CREATE INDEX idx_selector_candidates_raw_action ON selector_candidates(raw_action_id);
CREATE INDEX idx_selector_candidates_method ON selector_candidates(page_object_method_id);

CREATE TABLE healing_proposals (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  automation_key TEXT NOT NULL,
  execution_result_id TEXT,
  page_object_method_id TEXT,
  structured_step_id TEXT,
  kind TEXT NOT NULL,
  old_value TEXT,
  new_value TEXT NOT NULL,
  confidence REAL NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'proposed',
  evidence_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX idx_healing_proposals_key_status ON healing_proposals(project_id, automation_key, status);
```

Suggested `artifact_assets.source_type` values:

- `webwright_run`
- `raw_action`
- `mapping`
- `generated_file`
- `execution_run`
- `execution_result`

Suggested `artifact_assets.artifact_type` values:

- `final_script`
- `trajectory`
- `screenshot`
- `trace`
- `video`
- `log`
- `metadata`

Suggested `healing_proposals.kind` values:

- `selector_replace`
- `wait_adjust`
- `assertion_update`
- `pom_method_patch`

Suggested `healing_proposals.status` values:

- `proposed`
- `accepted`
- `rejected`
- `applied`
- `superseded`

## Mapping Review Layer

One TC step can map to multiple raw actions, so the mapping table should be many-to-many at the action level.

Mapping API persistence contract:

- `GET /mappings` returns `action_ids` from `case_action_mapping_actions`
  ordered by `order_index`, with `case_action_mappings.raw_action_id` used only
  as a legacy fallback when no join rows exist.
- `PUT /mappings` validates every submitted action ID against Webwright runs
  owned by the selected case before changing mappings or edited actions.
- A successful PUT replaces the selected case's mapping/join rows atomically,
  removes stale links, and keeps legacy `raw_action_id` equal to the first
  ordered action ID or `NULL` for an empty mapping.
- Duplicate TC step indexes and duplicate action IDs within one step are
  rejected instead of creating ambiguous ordered joins.

```sql
CREATE TABLE case_action_mappings (
  id TEXT PRIMARY KEY,
  test_case_id TEXT NOT NULL REFERENCES test_cases(id) ON DELETE CASCADE,
  tc_step_index INTEGER NOT NULL,
  normalized_step_id TEXT,
  normalized_step_name TEXT,
  pom_method_name TEXT,
  status TEXT NOT NULL DEFAULT 'mapped',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE case_action_mapping_actions (
  mapping_id TEXT NOT NULL REFERENCES case_action_mappings(id) ON DELETE CASCADE,
  raw_action_id TEXT NOT NULL REFERENCES raw_actions(id) ON DELETE CASCADE,
  order_index INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(mapping_id, raw_action_id)
);

CREATE INDEX idx_case_action_mappings_case_step ON case_action_mappings(test_case_id, tc_step_index);
```

Note: the current implementation stores `raw_action_id` directly on `case_action_mappings`. That is enough for simple 1:1 mapping, but this join table is needed for realistic TC step to multiple actions.

## Structured Layer

These tables make normalized structure durable and reviewable before code generation.

```sql
CREATE TABLE structured_flows (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  test_case_id TEXT NOT NULL REFERENCES test_cases(id) ON DELETE CASCADE,
  automation_key TEXT NOT NULL,
  name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft',
  version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(test_case_id, version)
);

CREATE TABLE structured_steps (
  id TEXT PRIMARY KEY,
  structured_flow_id TEXT NOT NULL REFERENCES structured_flows(id) ON DELETE CASCADE,
  mapping_id TEXT REFERENCES case_action_mappings(id) ON DELETE SET NULL,
  order_index INTEGER NOT NULL,
  name TEXT NOT NULL,
  kind TEXT NOT NULL,
  page_object_method_id TEXT,
  assertion_json TEXT,
  wait_json TEXT,
  metadata_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX idx_structured_steps_flow_order ON structured_steps(structured_flow_id, order_index);
```

Suggested `structured_flows.status` values:

- `draft`
- `needs_review`
- `approved`
- `generated`
- `stale`

Suggested `structured_steps.kind` values:

- `navigation`
- `interaction`
- `assertion`
- `wait`
- `helper`
- `custom_code`

## Page Object Layer

```sql
CREATE TABLE page_objects (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  file_path TEXT NOT NULL,
  url_pattern TEXT,
  description TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(project_id, name)
);

CREATE TABLE page_object_methods (
  id TEXT PRIMARY KEY,
  page_object_id TEXT NOT NULL REFERENCES page_objects(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  method_type TEXT NOT NULL,
  selector TEXT,
  value_template TEXT,
  return_type TEXT,
  body_plan_json TEXT NOT NULL DEFAULT '[]',
  source_mapping_id TEXT REFERENCES case_action_mappings(id) ON DELETE SET NULL,
  status TEXT NOT NULL DEFAULT 'draft',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(page_object_id, name)
);

CREATE INDEX idx_page_object_methods_status ON page_object_methods(status);
```

Suggested `method_type` values:

- `navigate`
- `click`
- `fill`
- `select`
- `assert`
- `wait`
- `composite`
- `custom`

## Generated Artifact Layer

```sql
CREATE TABLE generated_files (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  relative_path TEXT NOT NULL,
  automation_key TEXT,
  source_type TEXT,
  source_id TEXT,
  content_hash TEXT,
  status TEXT NOT NULL DEFAULT 'generated',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(project_id, relative_path)
);

CREATE TABLE generated_file_origins (
  generated_file_id TEXT NOT NULL REFERENCES generated_files(id) ON DELETE CASCADE,
  origin_type TEXT NOT NULL,
  origin_id TEXT NOT NULL,
  PRIMARY KEY(generated_file_id, origin_type, origin_id)
);

CREATE INDEX idx_generated_files_project_status ON generated_files(project_id, status);
CREATE INDEX idx_generated_files_key ON generated_files(automation_key);
```

Suggested `generated_files.status` values:

- `generated`
- `edited`
- `stale`
- `conflict`

Suggested `generated_file_origins.origin_type` values:

- `test_case`
- `raw_action`
- `mapping`
- `structured_flow`
- `structured_step`
- `page_object`
- `page_object_method`

Runtime persistence contract:

- the generator upserts and deduplicates to one active `generated_files` row per
  project and relative path even where an existing runtime database predates
  the documented uniqueness constraint;
- metadata and the actual output hash are written after the file exists;
- case-specific files receive their complete current origin set, while shared
  page and mappings files receive the union of relevant case origins;
- regeneration replaces origin rows deterministically so stale links and
  duplicate path metadata do not survive;
- `source_type` and `source_id` remain as a backward-compatible primary origin.

## Execution And Export

```sql
CREATE TABLE execution_runs (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  run_id TEXT NOT NULL,
  env TEXT NOT NULL,
  browser TEXT NOT NULL,
  headed INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'pending',
  result_path TEXT,
  started_at TEXT,
  ended_at TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE execution_results (
  id TEXT PRIMARY KEY,
  execution_run_id TEXT NOT NULL REFERENCES execution_runs(id) ON DELETE CASCADE,
  automation_key TEXT NOT NULL,
  source_type TEXT,
  source_case_id TEXT,
  title TEXT,
  status TEXT NOT NULL,
  duration_ms INTEGER,
  error TEXT,
  screenshot_path TEXT,
  trace_path TEXT
);

CREATE INDEX idx_execution_runs_project_created ON execution_runs(project_id, created_at);
CREATE INDEX idx_execution_results_run_key ON execution_results(execution_run_id, automation_key);

CREATE TABLE export_logs (
  id TEXT PRIMARY KEY,
  execution_run_id TEXT NOT NULL REFERENCES execution_runs(id) ON DELETE CASCADE,
  target TEXT NOT NULL,
  status TEXT NOT NULL,
  message TEXT,
  created_at TEXT NOT NULL
);
```

## Migration From Current Baseline

The current baseline can migrate incrementally:

1. Record the current local-development baseline in `schema_versions`.
2. Keep `projects`, `test_cases`, `webwright_runs`, `raw_actions`, `execution_runs`, `execution_results`, `generated_files`, `export_logs`.
3. Split multi-action mapping into `case_action_mapping_actions`.
4. Add `structured_flows` and `structured_steps`.
5. Add `page_objects` and `page_object_methods`.
6. Add `generated_file_origins`, `content_hash`, and `status` to generated file tracking.
7. Add `artifact_assets`, `selector_candidates`, and `healing_proposals` for artifact-backed self-healing.

## Minimum Schema For Next Structuring PR

For the next PR focused on structuring, implement at least:

- `structured_flows`
- `structured_steps`
- `page_objects`
- `page_object_methods`
- `case_action_mapping_actions`
- `generated_file_origins`
- `generated_files.content_hash`
- `generated_files.status`
- `artifact_assets`
- `selector_candidates`
- `healing_proposals`
