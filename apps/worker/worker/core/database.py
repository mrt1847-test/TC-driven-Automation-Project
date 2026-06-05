from __future__ import annotations

from datetime import datetime

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
SCHEMA_VERSION = 1
SCHEMA_VERSION_DESCRIPTION = "Phase 1 SQLModel create_all baseline"

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


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        record_schema_version(session)


def get_session():
    with Session(engine) as session:
        yield session
