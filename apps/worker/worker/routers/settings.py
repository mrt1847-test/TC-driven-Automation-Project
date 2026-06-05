from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from worker.core.database import get_session
from worker.core.config import load_settings, save_settings
from worker.models.db import Project
from worker.models.schemas import AppSettings
from worker.services.health import check_health, install_dependencies, project_health_check

router = APIRouter(tags=["settings"])


@router.get("/health")
def health():
    return check_health()


@router.get("/settings")
def get_settings():
    return load_settings()


@router.put("/settings")
def update_settings(settings: AppSettings):
    save_settings(settings)
    return settings


@router.post("/settings/validate")
def validate_settings():
    return check_health()


@router.post("/projects/{project_id}/health")
def project_health(project_id: str, generated_path: str | None = None):
    path = Path(generated_path) if generated_path else None
    if not path:
        return {"ok": False, "message": "generated path required"}
    return project_health_check(path)


@router.post("/projects/{project_id}/install-dependencies")
def install_deps(
    project_id: str,
    generated_path: str,
    browser: str = "chromium",
    session: Session = Depends(get_session),
):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return install_dependencies(Path(generated_path), session=session, project_id=project_id, browser=browser)
