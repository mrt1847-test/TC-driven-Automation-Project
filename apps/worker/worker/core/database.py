from __future__ import annotations

from sqlmodel import SQLModel, create_engine, Session

from worker.core.config import get_db_path
from worker.models.db import (
    Project,
    TestCase,
    WebwrightRun,
    RawAction,
    CaseActionMapping,
    ExecutionRun,
    ExecutionResult,
    GeneratedFile,
    ExportLog,
)

engine = create_engine(f"sqlite:///{get_db_path()}", echo=False)


def init_db() -> None:
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session
