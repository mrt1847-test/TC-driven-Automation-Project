from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from worker.core.database import get_session
from worker.models.db import Project
from worker.services.artifacts import list_project_artifacts

router = APIRouter(prefix="/projects/{project_id}/artifacts", tags=["artifacts"])


def _get_project(session: Session, project_id: str) -> Project:
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return project


@router.get("")
def list_artifacts(
    project_id: str,
    automation_key: str | None = Query(default=None, alias="automationKey"),
    automation_key_snake: str | None = Query(default=None, alias="automation_key"),
    source_type: str | None = Query(default=None, alias="sourceType"),
    source_type_snake: str | None = Query(default=None, alias="source_type"),
    source_id: str | None = Query(default=None, alias="sourceId"),
    source_id_snake: str | None = Query(default=None, alias="source_id"),
    artifact_type: str | None = Query(default=None, alias="artifactType"),
    artifact_type_snake: str | None = Query(default=None, alias="artifact_type"),
    run_id: str | None = Query(default=None, alias="runId"),
    run_id_snake: str | None = Query(default=None, alias="run_id"),
    webwright_run_id: str | None = Query(default=None, alias="webwrightRunId"),
    webwright_run_id_snake: str | None = Query(default=None, alias="webwright_run_id"),
    execution_id: str | None = Query(default=None, alias="executionId"),
    execution_id_snake: str | None = Query(default=None, alias="execution_id"),
    session: Session = Depends(get_session),
):
    project = _get_project(session, project_id)
    return list_project_artifacts(
        session,
        project,
        automation_key=automation_key or automation_key_snake,
        source_type=source_type or source_type_snake,
        source_id=source_id or source_id_snake,
        artifact_type=artifact_type or artifact_type_snake,
        run_id=run_id or run_id_snake,
        webwright_run_id=webwright_run_id or webwright_run_id_snake,
        execution_id=execution_id or execution_id_snake,
    )
