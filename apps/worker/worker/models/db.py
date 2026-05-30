from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from sqlmodel import Field, SQLModel, Column, JSON


class Project(SQLModel, table=True):
    id: Optional[str] = Field(default=None, primary_key=True)
    name: str
    root_path: str
    generated_project_path: Optional[str] = None
    default_env: str = "stg"
    created_at: datetime = Field(default_factory=datetime.utcnow)
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


class CaseActionMapping(SQLModel, table=True):
    id: Optional[str] = Field(default=None, primary_key=True)
    test_case_id: str = Field(index=True)
    raw_action_id: Optional[str] = None
    tc_step_index: int
    normalized_step_id: Optional[str] = None
    normalized_step_name: Optional[str] = None
    pom_method_name: Optional[str] = None
    status: str = "mapped"


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


class GeneratedFile(SQLModel, table=True):
    id: Optional[str] = Field(default=None, primary_key=True)
    project_id: str = Field(index=True)
    relative_path: str
    automation_key: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ExportLog(SQLModel, table=True):
    id: Optional[str] = Field(default=None, primary_key=True)
    execution_run_id: str = Field(index=True)
    target: str
    status: str
    message: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
