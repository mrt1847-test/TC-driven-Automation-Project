from __future__ import annotations

import hashlib
import json
from pathlib import Path

from sqlmodel import Session, select

from worker.core.config import new_id
from worker.models.db import (
    ArtifactAsset,
    ArtifactAssetSourceType,
    ArtifactAssetType,
    ExecutionResult,
    ExecutionRun,
    WebwrightRun,
)

_SCREENSHOT_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _same_path(path: Path, other: str | None) -> bool:
    if not other:
        return False
    return path.resolve() == Path(other).resolve()


def _artifact_type_for_path(path: Path, run: WebwrightRun) -> str | None:
    name = path.name.lower()
    suffix = path.suffix.lower()
    if _same_path(path, run.final_script_path) or name == "final_script.py":
        return ArtifactAssetType.final_script.value
    if _same_path(path, run.trajectory_path) or name == "trajectory.json":
        return ArtifactAssetType.trajectory.value
    if name == "metadata.json":
        return ArtifactAssetType.metadata.value
    if suffix == ".log":
        return ArtifactAssetType.log.value
    if suffix in _SCREENSHOT_SUFFIXES:
        return ArtifactAssetType.screenshot.value
    return None


def _collect_artifact_files(run: WebwrightRun) -> list[Path]:
    output_path = Path(run.output_path) if run.output_path else None
    candidates: list[Path] = []

    for explicit_path in [run.final_script_path, run.trajectory_path]:
        if explicit_path:
            candidates.append(Path(explicit_path))

    if output_path and output_path.exists():
        candidates.extend(path for path in output_path.rglob("*") if path.is_file())

    unique: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        if not path.exists() or not path.is_file() or _artifact_type_for_path(path, run) is None:
            continue
        key = str(path.resolve())
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def index_webwright_run_artifacts(session: Session, run: WebwrightRun) -> list[ArtifactAsset]:
    files = _collect_artifact_files(run)
    if not files:
        return []

    existing = session.exec(
        select(ArtifactAsset)
        .where(ArtifactAsset.source_type == ArtifactAssetSourceType.webwright_run.value)
        .where(ArtifactAsset.source_id == run.id)
    ).all()
    for asset in existing:
        session.delete(asset)

    output_root = Path(run.output_path) if run.output_path else None
    indexed: list[ArtifactAsset] = []
    for path in files:
        artifact_type = _artifact_type_for_path(path, run)
        if artifact_type is None:
            continue
        relative_path = None
        if output_root is not None:
            try:
                relative_path = str(path.resolve().relative_to(output_root.resolve()))
            except ValueError:
                relative_path = None

        metadata = {
            "run_id": run.id,
            "test_case_id": run.test_case_id,
            "status": run.status,
            "file_name": path.name,
            "relative_path": relative_path,
            "size_bytes": path.stat().st_size,
        }
        asset = ArtifactAsset(
            id=new_id("art"),
            project_id=run.project_id,
            automation_key=run.automation_key,
            source_type=ArtifactAssetSourceType.webwright_run.value,
            source_id=run.id,
            artifact_type=artifact_type,
            file_path=str(path),
            content_hash=_sha256(path),
            metadata_json=json.dumps(metadata, sort_keys=True),
        )
        session.add(asset)
        indexed.append(asset)

    session.commit()
    for asset in indexed:
        session.refresh(asset)
    return indexed


def _result_artifact_dir(run: ExecutionRun) -> Path | None:
    if not run.result_path:
        return None
    return Path(run.result_path).parent


def _execution_metadata(path: Path, run: ExecutionRun, relative_path: str | None, source: str) -> dict:
    return {
        "execution_id": run.id,
        "run_id": run.run_id,
        "status": run.status,
        "file_name": path.name,
        "relative_path": relative_path,
        "size_bytes": path.stat().st_size,
        "source": source,
    }


def _relative_to_result_dir(path: Path, run: ExecutionRun) -> str | None:
    artifact_dir = _result_artifact_dir(run)
    if artifact_dir is None:
        return None
    try:
        return str(path.resolve().relative_to(artifact_dir.resolve()))
    except ValueError:
        return None


def _resolve_result_artifact_path(raw_path: str | None, run: ExecutionRun) -> Path | None:
    if not raw_path:
        return None
    path = Path(raw_path)
    if path.is_absolute():
        return path
    artifact_dir = _result_artifact_dir(run)
    if artifact_dir is None:
        return path
    return artifact_dir / path


def _delete_existing_assets(session: Session, source_type: str, source_id: str | None) -> None:
    if not source_id:
        return
    existing = session.exec(
        select(ArtifactAsset)
        .where(ArtifactAsset.source_type == source_type)
        .where(ArtifactAsset.source_id == source_id)
    ).all()
    for asset in existing:
        session.delete(asset)


def _add_execution_asset(
    session: Session,
    run: ExecutionRun,
    path: Path,
    *,
    source_type: str,
    source_id: str,
    artifact_type: str,
    source: str,
    automation_key: str | None = None,
) -> ArtifactAsset | None:
    if not path.exists() or not path.is_file():
        return None
    relative_path = _relative_to_result_dir(path, run)
    asset = ArtifactAsset(
        id=new_id("art"),
        project_id=run.project_id,
        automation_key=automation_key,
        source_type=source_type,
        source_id=source_id,
        artifact_type=artifact_type,
        file_path=str(path),
        content_hash=_sha256(path),
        metadata_json=json.dumps(_execution_metadata(path, run, relative_path, source), sort_keys=True),
    )
    session.add(asset)
    return asset


def index_execution_failure_artifacts(session: Session, run: ExecutionRun) -> list[ArtifactAsset]:
    results = session.exec(select(ExecutionResult).where(ExecutionResult.execution_run_id == run.id)).all()
    failed_results = [result for result in results if result.status == "failed"]
    if run.status != "failed" and not failed_results:
        return []

    _delete_existing_assets(session, ArtifactAssetSourceType.execution_run.value, run.id)
    for result in results:
        _delete_existing_assets(session, ArtifactAssetSourceType.execution_result.value, result.id)

    indexed: list[ArtifactAsset] = []
    if run.result_path:
        result_path = Path(run.result_path)
        asset = _add_execution_asset(
            session,
            run,
            result_path,
            source_type=ArtifactAssetSourceType.execution_run.value,
            source_id=run.id or "",
            artifact_type=ArtifactAssetType.metadata.value,
            source="results_json",
        )
        if asset:
            indexed.append(asset)

    artifact_dir = _result_artifact_dir(run)
    if artifact_dir and artifact_dir.exists():
        for log_path in sorted(artifact_dir.glob("*.log")):
            asset = _add_execution_asset(
                session,
                run,
                log_path,
                source_type=ArtifactAssetSourceType.execution_run.value,
                source_id=run.id or "",
                artifact_type=ArtifactAssetType.log.value,
                source="runner_log",
            )
            if asset:
                indexed.append(asset)

    for result in failed_results:
        artifact_paths = [
            (result.screenshot_path, ArtifactAssetType.screenshot.value, "screenshot"),
            (result.trace_path, ArtifactAssetType.trace.value, "trace"),
        ]
        for raw_path, artifact_type, source in artifact_paths:
            path = _resolve_result_artifact_path(raw_path, run)
            if path is None:
                continue
            asset = _add_execution_asset(
                session,
                run,
                path,
                source_type=ArtifactAssetSourceType.execution_result.value,
                source_id=result.id or "",
                artifact_type=artifact_type,
                source=source,
                automation_key=result.automation_key,
            )
            if asset:
                indexed.append(asset)

    session.commit()
    for asset in indexed:
        session.refresh(asset)
    return indexed
