from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import and_, or_
from sqlmodel import Session, select

from worker.models.db import (
    ArtifactAsset,
    ArtifactAssetSourceType,
    ExecutionResult,
    ExecutionRun,
    Project,
    RawAction,
    WebwrightRun,
)


def _parse_metadata(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _iso(value: object) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else None


def _is_relative_to(path: Path, root: Path | None) -> bool:
    if root is None:
        return False
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def _same_path(path: Path, other: str | None) -> bool:
    if not other:
        return False
    try:
        return path.resolve() == Path(other).resolve()
    except OSError:
        return False


def _execution_result_dir(run: ExecutionRun | None) -> Path | None:
    if not run or not run.result_path:
        return None
    return Path(run.result_path).parent


def _resolve_execution_result_path(raw_path: str | None, run: ExecutionRun | None) -> Path | None:
    if not raw_path:
        return None
    path = Path(raw_path)
    if path.is_absolute():
        return path
    result_dir = _execution_result_dir(run)
    return path if result_dir is None else result_dir / path


def _safe_webwright_path(session: Session, asset: ArtifactAsset, path: Path) -> str | None:
    if not asset.source_id:
        return None
    run = session.get(WebwrightRun, asset.source_id)
    if not run or run.project_id != asset.project_id:
        return None
    output_root = Path(run.output_path) if run.output_path else None
    if _is_relative_to(path, output_root) or _same_path(path, run.final_script_path) or _same_path(path, run.trajectory_path):
        return str(path)
    return None


def _safe_raw_action_path(session: Session, asset: ArtifactAsset, path: Path) -> str | None:
    if not asset.source_id:
        return None
    action = session.get(RawAction, asset.source_id)
    if not action:
        return None
    run = session.get(WebwrightRun, action.webwright_run_id)
    if not run or run.project_id != asset.project_id:
        return None
    output_root = Path(run.output_path) if run.output_path else None
    return str(path) if _is_relative_to(path, output_root) else None


def _safe_execution_run_path(session: Session, asset: ArtifactAsset, path: Path) -> str | None:
    if not asset.source_id:
        return None
    run = session.get(ExecutionRun, asset.source_id)
    if not run or run.project_id != asset.project_id:
        return None
    result_dir = _execution_result_dir(run)
    if _is_relative_to(path, result_dir) or _same_path(path, run.result_path):
        return str(path)
    return None


def _safe_execution_result_path(session: Session, asset: ArtifactAsset, path: Path) -> str | None:
    if not asset.source_id:
        return None
    result = session.get(ExecutionResult, asset.source_id)
    if not result:
        return None
    run = session.get(ExecutionRun, result.execution_run_id)
    if not run or run.project_id != asset.project_id:
        return None
    result_dir = _execution_result_dir(run)
    screenshot = _resolve_execution_result_path(result.screenshot_path, run)
    trace = _resolve_execution_result_path(result.trace_path, run)
    if _is_relative_to(path, result_dir) or (screenshot and _same_path(path, str(screenshot))) or (trace and _same_path(path, str(trace))):
        return str(path)
    return None


def _safe_file_path(session: Session, asset: ArtifactAsset) -> str | None:
    path = Path(asset.file_path)
    if not path.is_absolute():
        return asset.file_path
    if asset.source_type == ArtifactAssetSourceType.webwright_run.value:
        return _safe_webwright_path(session, asset, path)
    if asset.source_type == ArtifactAssetSourceType.raw_action.value:
        return _safe_raw_action_path(session, asset, path)
    if asset.source_type == ArtifactAssetSourceType.execution_run.value:
        return _safe_execution_run_path(session, asset, path)
    if asset.source_type == ArtifactAssetSourceType.execution_result.value:
        return _safe_execution_result_path(session, asset, path)
    return None


def _artifact_payload(session: Session, asset: ArtifactAsset) -> dict[str, Any]:
    metadata = _parse_metadata(asset.metadata_json)
    safe_file_path = _safe_file_path(session, asset)
    file_name = metadata.get("file_name") or Path(asset.file_path).name
    relative_path = metadata.get("relative_path")
    title = metadata.get("title") or file_name or asset.artifact_type
    return {
        "id": asset.id,
        "projectId": asset.project_id,
        "automationKey": asset.automation_key,
        "sourceType": asset.source_type,
        "sourceId": asset.source_id,
        "artifactType": asset.artifact_type,
        "kind": asset.artifact_type,
        "title": title,
        "filePath": safe_file_path,
        "pathAvailable": safe_file_path is not None,
        "fileName": file_name,
        "relativePath": relative_path,
        "contentHash": asset.content_hash,
        "metadata": metadata,
        "createdAt": _iso(asset.created_at),
    }


def artifact_asset_payload(session: Session, asset: ArtifactAsset) -> dict[str, Any]:
    return _artifact_payload(session, asset)


def list_project_artifacts(
    session: Session,
    project: Project,
    *,
    automation_key: str | None = None,
    source_type: str | None = None,
    source_id: str | None = None,
    artifact_type: str | None = None,
    run_id: str | None = None,
    webwright_run_id: str | None = None,
    execution_id: str | None = None,
) -> dict[str, Any]:
    statement = select(ArtifactAsset).where(ArtifactAsset.project_id == project.id)
    if automation_key:
        statement = statement.where(ArtifactAsset.automation_key == automation_key)
    if source_type:
        statement = statement.where(ArtifactAsset.source_type == source_type)
    if source_id:
        statement = statement.where(ArtifactAsset.source_id == source_id)
    if artifact_type:
        statement = statement.where(ArtifactAsset.artifact_type == artifact_type)
    if run_id:
        statement = statement.where(ArtifactAsset.source_id == run_id)
    if webwright_run_id:
        statement = statement.where(
            ArtifactAsset.source_type == ArtifactAssetSourceType.webwright_run.value,
            ArtifactAsset.source_id == webwright_run_id,
        )
    if execution_id:
        result_ids = [
            result_id
            for result_id in session.exec(
                select(ExecutionResult.id).where(ExecutionResult.execution_run_id == execution_id)
            ).all()
            if result_id
        ]
        execution_clauses = [
            and_(
                ArtifactAsset.source_type == ArtifactAssetSourceType.execution_run.value,
                ArtifactAsset.source_id == execution_id,
            )
        ]
        if result_ids:
            execution_clauses.append(
                and_(
                    ArtifactAsset.source_type == ArtifactAssetSourceType.execution_result.value,
                    ArtifactAsset.source_id.in_(result_ids),
                )
            )
        statement = statement.where(or_(*execution_clauses))

    artifacts = session.exec(statement.order_by(ArtifactAsset.created_at, ArtifactAsset.id)).all()
    return {
        "projectId": project.id,
        "artifacts": [_artifact_payload(session, artifact) for artifact in artifacts],
    }
