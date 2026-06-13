from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from worker.core.config import new_id
from worker.core.database import get_session
from worker.models.db import GeneratedFile, Project, TestCase
from worker.models.schemas import (
    FileContentUpdate,
    FileCreateRequest,
    FileRenameRequest,
    GenerationRequest,
    RawRefreshRegenerationRequest,
    RetireCaseRequest,
)
from worker.services.generated_runtime import ensure_generated_runtime
from worker.services.generated_file_status import refresh_generated_file_statuses
from worker.services.generated_file_status_summary import project_generated_file_status_summary
from worker.services.project_generator import (
    GenerationConflictError,
    GenerationResult,
    generate_project,
    retire_generated_case,
)
from worker.services.project_ide import (
    create_file,
    delete_file,
    list_file_tree,
    read_file,
    rename_file,
    search_project,
    write_file,
)
from worker.services.raw_refresh_regeneration import refresh_and_regenerate_case
from worker.services.structuring_service import get_latest_flow

router = APIRouter(prefix="/projects/{project_id}", tags=["generation"])


def _generation_summary(result: GenerationResult, *, preview: bool = False) -> dict:
    return {
        "preview": preview,
        "generationMode": result.mode,
        "selectedCaseIds": result.selected_case_ids,
        "affectedFiles": result.affected_files,
        "changedFiles": result.changed_files,
        "preservedFiles": result.preserved_files,
        "editedFiles": result.edited_files,
        "staleFiles": result.stale_files,
        "conflictFiles": result.conflict_files,
    }


def _generate(
    project_id: str,
    request: GenerationRequest,
    session: Session,
    *,
    selected_only: bool = False,
):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    if selected_only and not request.case_ids:
        raise HTTPException(400, "Selected generation requires caseIds")
    if selected_only and request.mode == "full":
        raise HTTPException(400, "Selected generation does not support full mode")
    mode = "incremental" if selected_only else request.mode
    try:
        result = generate_project(
            session,
            project_id,
            Path(project.root_path),
            request.case_ids,
            mode=mode,
        )
    except GenerationConflictError as exc:
        raise HTTPException(409, {"message": str(exc), **exc.summary()}) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    project.generated_project_path = str(result.output)
    session.add(project)
    session.commit()
    runtime_bootstrap = ensure_generated_runtime(
        result.output,
        install=True,
        session=session,
        project_id=project_id,
    )
    return {
        "generatedProjectPath": str(result.output),
        "runtimeBootstrap": runtime_bootstrap,
        "generationMode": result.mode,
        "selectedCaseIds": result.selected_case_ids,
        "affectedFiles": result.affected_files,
        "changedFiles": result.changed_files,
        "preservedFiles": result.preserved_files,
        "editedFiles": result.edited_files,
        "staleFiles": result.stale_files,
        "conflictFiles": result.conflict_files,
    }


@router.post("/generate")
def generate(
    project_id: str,
    request: GenerationRequest | None = None,
    session: Session = Depends(get_session),
):
    return _generate(project_id, request or GenerationRequest(), session)


@router.post("/generate/selected")
def generate_selected(
    project_id: str,
    request: GenerationRequest,
    session: Session = Depends(get_session),
):
    return _generate(project_id, request, session, selected_only=True)


@router.post("/generate/selected/preview")
def preview_generate_selected(
    project_id: str,
    request: GenerationRequest,
    session: Session = Depends(get_session),
):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    if not request.case_ids:
        raise HTTPException(400, "Selected generation preview requires caseIds")
    if request.mode == "full":
        raise HTTPException(400, "Selected generation preview does not support full mode")
    try:
        result = generate_project(
            session,
            project_id,
            Path(project.root_path),
            request.case_ids,
            mode="incremental",
            dry_run=True,
        )
    except GenerationConflictError as exc:
        raise HTTPException(409, {"message": str(exc), **exc.summary()}) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _generation_summary(result, preview=True)


@router.post("/cases/{case_id}/refresh-webwright-and-regenerate")
async def refresh_webwright_and_regenerate(
    project_id: str,
    case_id: str,
    request: RawRefreshRegenerationRequest | None = None,
    session: Session = Depends(get_session),
):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    case = session.get(TestCase, case_id)
    if not case or case.project_id != project_id:
        raise HTTPException(404, "Case not found")
    if not get_latest_flow(session, case_id):
        raise HTTPException(409, "Existing structured flow required for refresh regeneration")
    body = request or RawRefreshRegenerationRequest()
    try:
        return await refresh_and_regenerate_case(
            session,
            project,
            case,
            model_config=body.ww_model_config,
            job_id=new_id("refresh"),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/cases/{case_id}/refresh-webwright-and-regenerate/preview")
def preview_refresh_webwright_and_regenerate(
    project_id: str,
    case_id: str,
    session: Session = Depends(get_session),
):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    case = session.get(TestCase, case_id)
    if not case or case.project_id != project_id:
        raise HTTPException(404, "Case not found")
    if not get_latest_flow(session, case_id):
        raise HTTPException(409, "Existing structured flow required for refresh regeneration preview")
    try:
        result = generate_project(
            session,
            project_id,
            Path(project.root_path),
            [case_id],
            mode="incremental",
            dry_run=True,
        )
    except GenerationConflictError as exc:
        raise HTTPException(409, {"message": str(exc), **exc.summary()}) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "preview": True,
        "action": "raw_refresh_regenerate",
        "caseId": case.id,
        "automationKey": case.automation_key,
        "note": (
            "Preview covers post-merge incremental regeneration from the current structured state. "
            "Webwright re-run and raw merge are not simulated."
        ),
        "generation": _generation_summary(result, preview=True),
    }


@router.post("/cases/{case_id}/retire")
def retire_case(
    project_id: str,
    case_id: str,
    request: RetireCaseRequest,
    session: Session = Depends(get_session),
):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    case = session.get(TestCase, case_id)
    if not case or case.project_id != project_id:
        raise HTTPException(404, "Case not found")
    if not request.confirmed:
        raise HTTPException(400, "Retire cleanup requires confirmed=true")
    output = Path(project.generated_project_path or Path(project.root_path) / "generated")
    try:
        return retire_generated_case(
            session,
            project_id,
            output,
            case_id,
            action=request.action,
            reason=request.reason,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/cases/{case_id}/retire/preview")
def preview_retire_case(
    project_id: str,
    case_id: str,
    request: RetireCaseRequest | None = None,
    session: Session = Depends(get_session),
):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    case = session.get(TestCase, case_id)
    if not case or case.project_id != project_id:
        raise HTTPException(404, "Case not found")
    body = request or RetireCaseRequest()
    output = Path(project.generated_project_path or Path(project.root_path) / "generated")
    try:
        return retire_generated_case(
            session,
            project_id,
            output,
            case_id,
            action=body.action,
            reason=body.reason,
            preview=True,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/generated-files")
def generated_files(project_id: str, session: Session = Depends(get_session)):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    root = Path(project.generated_project_path or Path(project.root_path) / "generated")
    metadata = refresh_generated_file_statuses(session, project_id, root, commit=True)
    items = list_file_tree(root)
    for item in items:
        if item["type"] == "file" and item["path"] in metadata:
            item.update(metadata[item["path"]])
    return items


@router.get("/generated-files/status")
def generated_file_status(project_id: str, session: Session = Depends(get_session)):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return project_generated_file_status_summary(session, project)


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
