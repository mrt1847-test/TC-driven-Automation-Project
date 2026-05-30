from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from worker.core.config import get_data_dir, new_id
from worker.core.database import get_session
from worker.models.db import Project

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("")
def list_projects(session: Session = Depends(get_session)):
    return session.exec(select(Project)).all()


@router.post("")
def create_project(payload: dict, session: Session = Depends(get_session)):
    name = payload.get("name", "Untitled Project")
    root = payload.get("rootPath") or str(get_data_dir() / "automation-projects" / new_id("proj"))
    path = Path(root)
    path.mkdir(parents=True, exist_ok=True)
    project = Project(
        id=new_id("proj"),
        name=name,
        root_path=str(path),
        generated_project_path=str(path / "generated"),
        default_env=payload.get("defaultEnv", "stg"),
    )
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


@router.get("/{project_id}")
def get_project(project_id: str, session: Session = Depends(get_session)):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return project


@router.patch("/{project_id}")
def update_project(project_id: str, payload: dict, session: Session = Depends(get_session)):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    for key in ["name", "root_path", "generated_project_path", "default_env"]:
        api_key = {"root_path": "rootPath", "generated_project_path": "generatedProjectPath", "default_env": "defaultEnv"}.get(key, key)
        if api_key in payload:
            setattr(project, key, payload[api_key])
    project.updated_at = datetime.utcnow()
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


@router.delete("/{project_id}")
def delete_project(project_id: str, session: Session = Depends(get_session)):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    session.delete(project)
    session.commit()
    return {"ok": True}
