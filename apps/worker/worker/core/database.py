from __future__ import annotations

from datetime import datetime

from sqlalchemy import inspect, text
from sqlmodel import SQLModel, create_engine, Session

from worker.core.config import get_db_path
from worker.models.db import (
    Project,
    ProjectPromptContext,
    PromptPreset,
    SchemaVersion,
    TestCase,
    CasePromptOverride,
    WebwrightPromptPayload,
    WebwrightRun,
    RawAction,
    ArtifactAsset,
    CaseActionMapping,
    CaseActionMappingAction,
    StructuredFlow,
    StructuredStep,
    PageObject,
    PageObjectMethod,
    SelectorCandidate,
    ExecutionRun,
    ExecutionResult,
    GeneratedRuntimeInstallState,
    HealingProposal,
    GeneratedFile,
    GeneratedFileOrigin,
    ExportLog,
)

SCHEMA_VERSION_ID = "tc_studio"
SCHEMA_VERSION = 2
SCHEMA_VERSION_DESCRIPTION = "Prompt composer selected preset schema"

engine = create_engine(f"sqlite:///{get_db_path()}", echo=False)


def record_schema_version(session: Session) -> SchemaVersion:
    now = datetime.utcnow()
    current = session.get(SchemaVersion, SCHEMA_VERSION_ID)
    if current is None:
        current = SchemaVersion(
            id=SCHEMA_VERSION_ID,
            version=SCHEMA_VERSION,
            description=SCHEMA_VERSION_DESCRIPTION,
            applied_at=now,
            updated_at=now,
        )
    elif current.version < SCHEMA_VERSION:
        current.version = SCHEMA_VERSION
        current.description = SCHEMA_VERSION_DESCRIPTION
        current.updated_at = now

    session.add(current)
    session.commit()
    session.refresh(current)
    return current


def apply_lightweight_schema_upgrades() -> None:
    inspector = inspect(engine)
    if "project_prompt_contexts" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("project_prompt_contexts")}
        if "selected_preset_id" not in columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE project_prompt_contexts ADD COLUMN selected_preset_id TEXT"))


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    apply_lightweight_schema_upgrades()
    with Session(engine) as session:
        record_schema_version(session)


def get_session():
    with Session(engine) as session:
        yield session
