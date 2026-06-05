from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from sqlalchemy import Index, UniqueConstraint
from sqlmodel import Field, SQLModel, Column, JSON


class Project(SQLModel, table=True):
    id: Optional[str] = Field(default=None, primary_key=True)
    name: str
    root_path: str
    generated_project_path: Optional[str] = None
    default_env: str = "stg"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class SchemaVersion(SQLModel, table=True):
    __tablename__ = "schema_versions"

    id: str = Field(default="tc_studio", primary_key=True)
    version: int
    description: Optional[str] = None
    applied_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class TestCaseStatus(str, Enum):
    imported = "imported"
    webwright_pending = "webwright_pending"
    webwright_running = "webwright_running"
    webwright_completed = "webwright_completed"
    webwright_failed = "webwright_failed"
    needs_review = "needs_review"
    mapped = "mapped"
    structured = "structured"
    generated = "generated"
    retired = "retired"
    deleted = "deleted"


class TestCase(SQLModel, table=True):
    id: Optional[str] = Field(default=None, primary_key=True)
    project_id: str = Field(index=True)
    source_type: str
    source_case_id: str
    source_location_json: Optional[str] = None
    title: str
    preconditions_json: Optional[str] = None
    steps_json: str = "[]"
    expected_result: Optional[str] = None
    automation_key: str = Field(index=True)
    tags_json: Optional[str] = None
    priority: Optional[str] = None
    start_url: Optional[str] = None
    status: str = TestCaseStatus.imported.value
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class WebwrightRunStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"
    needs_review = "needs_review"
    structured = "structured"
    generated = "generated"


class WebwrightRun(SQLModel, table=True):
    id: Optional[str] = Field(default=None, primary_key=True)
    project_id: str = Field(index=True)
    test_case_id: str = Field(index=True)
    automation_key: str = Field(index=True)
    status: str = WebwrightRunStatus.pending.value
    output_path: Optional[str] = None
    final_script_path: Optional[str] = None
    trajectory_path: Optional[str] = None
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ProjectPromptContext(SQLModel, table=True):
    __tablename__ = "project_prompt_contexts"

    project_id: str = Field(foreign_key="project.id", primary_key=True)
    batch_prompt: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class CasePromptOverride(SQLModel, table=True):
    __tablename__ = "case_prompt_overrides"
    __table_args__ = (
        Index("idx_case_prompt_overrides_key", "project_id", "automation_key"),
    )

    project_id: str = Field(foreign_key="project.id", primary_key=True)
    case_id: str = Field(foreign_key="testcase.id", primary_key=True)
    automation_key: str = Field(index=True)
    prompt_override: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class PromptPreset(SQLModel, table=True):
    __tablename__ = "prompt_presets"
    __table_args__ = (
        Index("idx_prompt_presets_project_category", "project_id", "category"),
        Index("idx_prompt_presets_builtin", "is_builtin", "category"),
    )

    id: Optional[str] = Field(default=None, primary_key=True)
    project_id: Optional[str] = Field(default=None, foreign_key="project.id")
    category: str
    name: str
    guidance: str
    is_builtin: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class WebwrightPromptPayload(SQLModel, table=True):
    __tablename__ = "webwright_prompt_payloads"
    __table_args__ = (
        UniqueConstraint("webwright_run_id", name="uq_webwright_prompt_payloads_run"),
        Index("idx_webwright_prompt_payloads_project_case", "project_id", "test_case_id"),
        Index("idx_webwright_prompt_payloads_project_run", "project_id", "webwright_run_id"),
        Index("idx_webwright_prompt_payloads_key", "project_id", "automation_key"),
    )

    id: Optional[str] = Field(default=None, primary_key=True)
    project_id: str = Field(foreign_key="project.id", index=True)
    test_case_id: str = Field(foreign_key="testcase.id", index=True)
    webwright_run_id: str = Field(foreign_key="webwrightrun.id", index=True)
    automation_key: str = Field(index=True)
    final_prompt: str
    base_prompt: str = ""
    preset_id: Optional[str] = Field(default=None, index=True)
    preset_category: Optional[str] = None
    preset_name: Optional[str] = None
    preset_guidance: str = ""
    batch_prompt: str = ""
    case_prompt_override: str = ""
    environment: str = "stg"
    start_url: str = ""
    webwright_model_config: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)


class RawAction(SQLModel, table=True):
    id: Optional[str] = Field(default=None, primary_key=True)
    webwright_run_id: str = Field(index=True)
    automation_key: str = Field(index=True)
    order_index: int
    type: str
    target: Optional[str] = None
    selector: Optional[str] = None
    value: Optional[str] = None
    source_line: Optional[int] = None


class ArtifactAssetSourceType(str, Enum):
    webwright_run = "webwright_run"
    raw_action = "raw_action"
    mapping = "mapping"
    generated_file = "generated_file"
    execution_run = "execution_run"
    execution_result = "execution_result"


class ArtifactAssetType(str, Enum):
    final_script = "final_script"
    trajectory = "trajectory"
    screenshot = "screenshot"
    trace = "trace"
    video = "video"
    log = "log"
    metadata = "metadata"


class ArtifactAsset(SQLModel, table=True):
    __tablename__ = "artifact_assets"
    __table_args__ = (
        Index("idx_artifact_assets_key", "project_id", "automation_key"),
        Index("idx_artifact_assets_source", "source_type", "source_id"),
    )

    id: Optional[str] = Field(default=None, primary_key=True)
    project_id: str = Field(foreign_key="project.id", index=True)
    automation_key: Optional[str] = None
    source_type: str
    source_id: Optional[str] = None
    artifact_type: str
    file_path: str
    content_hash: Optional[str] = None
    metadata_json: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class CaseActionMapping(SQLModel, table=True):
    id: Optional[str] = Field(default=None, primary_key=True)
    test_case_id: str = Field(index=True)
    raw_action_id: Optional[str] = None
    tc_step_index: int
    normalized_step_id: Optional[str] = None
    normalized_step_name: Optional[str] = None
    pom_method_name: Optional[str] = None
    status: str = "mapped"


class CaseActionMappingAction(SQLModel, table=True):
    __tablename__ = "case_action_mapping_actions"

    mapping_id: str = Field(foreign_key="caseactionmapping.id", primary_key=True)
    raw_action_id: str = Field(foreign_key="rawaction.id", primary_key=True)
    order_index: int = 0


class StructuredFlowStatus(str, Enum):
    draft = "draft"
    needs_review = "needs_review"
    approved = "approved"
    generated = "generated"
    stale = "stale"


class StructuredStepKind(str, Enum):
    navigation = "navigation"
    interaction = "interaction"
    assertion = "assertion"
    wait = "wait"
    helper = "helper"
    custom_code = "custom_code"


class StructuredFlow(SQLModel, table=True):
    __tablename__ = "structured_flows"
    __table_args__ = (UniqueConstraint("test_case_id", "version"),)

    id: Optional[str] = Field(default=None, primary_key=True)
    project_id: str = Field(foreign_key="project.id", index=True)
    test_case_id: str = Field(foreign_key="testcase.id", index=True)
    automation_key: str = Field(index=True)
    name: str
    status: str = StructuredFlowStatus.draft.value
    version: int = 1
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class StructuredStep(SQLModel, table=True):
    __tablename__ = "structured_steps"
    __table_args__ = (Index("idx_structured_steps_flow_order", "structured_flow_id", "order_index"),)

    id: Optional[str] = Field(default=None, primary_key=True)
    structured_flow_id: str = Field(foreign_key="structured_flows.id")
    mapping_id: Optional[str] = Field(default=None, foreign_key="caseactionmapping.id")
    order_index: int
    name: str
    kind: str = StructuredStepKind.interaction.value
    page_object_method_id: Optional[str] = None
    assertion_json: Optional[str] = None
    wait_json: Optional[str] = None
    metadata_json: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class PageObjectMethodType(str, Enum):
    navigate = "navigate"
    click = "click"
    fill = "fill"
    select = "select"
    assert_ = "assert"
    wait = "wait"
    composite = "composite"
    custom = "custom"


class PageObjectMethodStatus(str, Enum):
    draft = "draft"
    approved = "approved"
    generated = "generated"
    stale = "stale"


class PageObject(SQLModel, table=True):
    __tablename__ = "page_objects"
    __table_args__ = (UniqueConstraint("project_id", "name"),)

    id: Optional[str] = Field(default=None, primary_key=True)
    project_id: str = Field(foreign_key="project.id", index=True)
    name: str
    file_path: str
    url_pattern: Optional[str] = None
    description: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class PageObjectMethod(SQLModel, table=True):
    __tablename__ = "page_object_methods"
    __table_args__ = (
        UniqueConstraint("page_object_id", "name"),
        Index("idx_page_object_methods_status", "status"),
    )

    id: Optional[str] = Field(default=None, primary_key=True)
    page_object_id: str = Field(foreign_key="page_objects.id")
    name: str
    method_type: str
    selector: Optional[str] = None
    value_template: Optional[str] = None
    return_type: Optional[str] = None
    body_plan_json: str = "[]"
    source_mapping_id: Optional[str] = Field(default=None, foreign_key="caseactionmapping.id")
    status: str = PageObjectMethodStatus.draft.value
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class SelectorCandidateType(str, Enum):
    role = "role"
    text = "text"
    test_id = "test_id"
    css = "css"
    xpath = "xpath"


class SelectorCandidate(SQLModel, table=True):
    __tablename__ = "selector_candidates"
    __table_args__ = (
        Index("idx_selector_candidates_raw_action", "raw_action_id"),
        Index("idx_selector_candidates_method", "page_object_method_id"),
    )

    id: Optional[str] = Field(default=None, primary_key=True)
    raw_action_id: Optional[str] = Field(default=None, foreign_key="rawaction.id")
    page_object_method_id: Optional[str] = Field(default=None, foreign_key="page_object_methods.id")
    selector_type: str
    selector_value: str
    confidence: float = 0
    source_artifact_id: Optional[str] = Field(default=None, foreign_key="artifact_assets.id")
    metadata_json: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class GeneratedFileStatus(str, Enum):
    generated = "generated"
    edited = "edited"
    stale = "stale"
    conflict = "conflict"
    obsolete = "obsolete"


class ExecutionRun(SQLModel, table=True):
    id: Optional[str] = Field(default=None, primary_key=True)
    project_id: str = Field(index=True)
    run_id: str = Field(index=True)
    env: str
    browser: str
    headed: bool = False
    status: str = "pending"
    result_path: Optional[str] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ExecutionResult(SQLModel, table=True):
    id: Optional[str] = Field(default=None, primary_key=True)
    execution_run_id: str = Field(index=True)
    automation_key: str = Field(index=True)
    source_type: Optional[str] = None
    source_case_id: Optional[str] = None
    title: Optional[str] = None
    status: str
    duration_ms: Optional[int] = None
    error: Optional[str] = None
    screenshot_path: Optional[str] = None
    trace_path: Optional[str] = None


class GeneratedRuntimeInstallState(SQLModel, table=True):
    __tablename__ = "generated_runtime_install_states"
    __table_args__ = (
        Index("idx_generated_runtime_install_project_key", "project_id", "readiness_key"),
        Index("idx_generated_runtime_install_project_path", "project_id", "generated_project_path"),
    )

    id: Optional[str] = Field(default=None, primary_key=True)
    project_id: str = Field(foreign_key="project.id", index=True)
    generated_project_path: str
    generated_project_hash: str
    requirements_hash: str
    runtime_manifest_hash: str
    runtime_profile_hash: str
    readiness_key: str = Field(index=True)
    python_path: str
    browser: str = "chromium"
    browser_cache_path: str = ""
    status: str = "ready"
    message: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class HealingProposalKind(str, Enum):
    selector_replace = "selector_replace"
    wait_adjust = "wait_adjust"
    assertion_update = "assertion_update"
    pom_method_patch = "pom_method_patch"


class HealingProposalStatus(str, Enum):
    proposed = "proposed"
    accepted = "accepted"
    rejected = "rejected"
    applied = "applied"
    superseded = "superseded"


class HealingProposal(SQLModel, table=True):
    __tablename__ = "healing_proposals"
    __table_args__ = (
        Index("idx_healing_proposals_key_status", "project_id", "automation_key", "status"),
    )

    id: Optional[str] = Field(default=None, primary_key=True)
    project_id: str = Field(foreign_key="project.id")
    automation_key: str
    execution_result_id: Optional[str] = Field(default=None, foreign_key="executionresult.id")
    page_object_method_id: Optional[str] = Field(default=None, foreign_key="page_object_methods.id")
    structured_step_id: Optional[str] = Field(default=None, foreign_key="structured_steps.id")
    kind: str
    old_value: Optional[str] = None
    new_value: str
    confidence: float = 0
    status: str = HealingProposalStatus.proposed.value
    evidence_json: str = "[]"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class GeneratedFile(SQLModel, table=True):
    __table_args__ = (
        Index("idx_generated_files_project_status", "project_id", "status"),
        Index("idx_generated_files_key", "automation_key"),
    )

    id: Optional[str] = Field(default=None, primary_key=True)
    project_id: str = Field(index=True)
    relative_path: str
    automation_key: Optional[str] = None
    source_type: Optional[str] = None
    source_id: Optional[str] = None
    content_hash: Optional[str] = None
    status: str = GeneratedFileStatus.generated.value
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class GeneratedFileOrigin(SQLModel, table=True):
    __tablename__ = "generated_file_origins"

    generated_file_id: str = Field(foreign_key="generatedfile.id", primary_key=True)
    origin_type: str = Field(primary_key=True)
    origin_id: str = Field(primary_key=True)


class ExportLog(SQLModel, table=True):
    id: Optional[str] = Field(default=None, primary_key=True)
    execution_run_id: str = Field(index=True)
    target: str
    status: str
    message: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
