from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from worker.core.database import get_session
from worker.models.db import GeneratedFile, Project
from worker.models.schemas import FileContentUpdate, FileCreateRequest, FileRenameRequest
from worker.services.generated_runtime import ensure_generated_runtime
from worker.services.project_generator import generate_project
from worker.services.project_ide import (
    create_file,
    delete_file,
    list_file_tree,
    read_file,
    rename_file,
    search_project,
    write_file,
)

router = APIRouter(prefix="/projects/{project_id}", tags=["generation"])


@router.post("/generate")
def generate(project_id: str, payload: dict | None = None, session: Session = Depends(get_session)):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    case_ids = (payload or {}).get("caseIds")
    output = generate_project(session, project_id, Path(project.root_path), case_ids)
    project.generated_project_path = str(output)
    session.add(project)
    session.commit()
    runtime_bootstrap = ensure_generated_runtime(output, install=True)
    return {"generatedProjectPath": str(output), "runtimeBootstrap": runtime_bootstrap}


@router.get("/generated-files")
def generated_files(project_id: str, session: Session = Depends(get_session)):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    root = Path(project.generated_project_path or Path(project.root_path) / "generated")
    return list_file_tree(root)


@router.get("/generated-files/content")
def get_file_content(project_id: str, path: str, session: Session = Depends(get_session)):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    root = Path(project.generated_project_path or Path(project.root_path) / "generated")
    return {"path": path, "content": read_file(root, path)}


@router.put("/generated-files/content")
def put_file_content(project_id: str, body: FileContentUpdate, session: Session = Depends(get_session)):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    root = Path(project.generated_project_path or Path(project.root_path) / "generated")
    write_file(root, body.path, body.content)
    return {"ok": True}


@router.post("/generated-files/create")
def create_generated_file(project_id: str, body: FileCreateRequest, session: Session = Depends(get_session)):
    project = session.get(Project, project_id)
    root = Path(project.generated_project_path or Path(project.root_path) / "generated")
    create_file(root, body.path, body.content)
    return {"ok": True}


@router.delete("/generated-files")
def delete_generated_file(project_id: str, path: str, session: Session = Depends(get_session)):
    project = session.get(Project, project_id)
    root = Path(project.generated_project_path or Path(project.root_path) / "generated")
    delete_file(root, path)
    return {"ok": True}


@router.post("/generated-files/rename")
def rename_generated_file(project_id: str, body: FileRenameRequest, session: Session = Depends(get_session)):
    project = session.get(Project, project_id)
    root = Path(project.generated_project_path or Path(project.root_path) / "generated")
    rename_file(root, body.old_path, body.new_path)
    return {"ok": True}


@router.get("/search")
def search(project_id: str, q: str, session: Session = Depends(get_session)):
    project = session.get(Project, project_id)
    root = Path(project.generated_project_path or Path(project.root_path) / "generated")
    return search_project(session, project_id, root, q)
