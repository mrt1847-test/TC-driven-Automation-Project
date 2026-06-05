from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

from sqlmodel import Session, select

from worker.models.db import GeneratedFile, GeneratedFileStatus


def hash_text(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def hash_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def latest_generated_files_by_path(
    session: Session,
    project_id: str,
    relative_paths: set[str] | None = None,
) -> dict[str, GeneratedFile]:
    query = select(GeneratedFile).where(GeneratedFile.project_id == project_id)
    if relative_paths:
        query = query.where(GeneratedFile.relative_path.in_(sorted(relative_paths)))
    rows = session.exec(query).all()
    rows_by_path: dict[str, list[GeneratedFile]] = {}
    for row in rows:
        rows_by_path.setdefault(row.relative_path, []).append(row)
    return {
        relative_path: sorted(
            path_rows,
            key=lambda row: (row.updated_at, row.created_at, row.id or ""),
            reverse=True,
        )[0]
        for relative_path, path_rows in rows_by_path.items()
    }


def refresh_generated_file_statuses(
    session: Session,
    project_id: str,
    output: Path,
    *,
    relative_paths: set[str] | None = None,
    planned_contents: dict[str, str] | None = None,
    planned_deletions: set[str] | None = None,
    commit: bool = False,
) -> dict[str, dict]:
    planned_contents = planned_contents or {}
    planned_deletions = planned_deletions or set()
    tracked_paths = set(relative_paths or set()) | set(planned_contents) | planned_deletions
    rows = latest_generated_files_by_path(
        session,
        project_id,
        tracked_paths or None,
    )
    assessments: dict[str, dict] = {}
    now = datetime.utcnow()

    for relative_path, row in rows.items():
        if row.status == GeneratedFileStatus.obsolete.value:
            continue

        target = output / relative_path
        current_hash = hash_file(target)
        planned_hash = (
            hash_text(planned_contents[relative_path])
            if relative_path in planned_contents
            else None
        )
        file_changed = bool(
            row.content_hash
            and (current_hash is None or current_hash != row.content_hash)
        )
        source_changed = bool(
            row.content_hash
            and (planned_hash is not None or relative_path in planned_deletions)
            and planned_hash != row.content_hash
        )

        if source_changed and file_changed:
            next_status = GeneratedFileStatus.conflict.value
        elif file_changed:
            next_status = GeneratedFileStatus.edited.value
        elif source_changed:
            next_status = GeneratedFileStatus.stale.value
        else:
            next_status = GeneratedFileStatus.generated.value

        if row.status != next_status:
            row.status = next_status
            row.updated_at = now
            session.add(row)

        assessments[relative_path] = {
            "path": relative_path,
            "status": next_status,
            "storedHash": row.content_hash,
            "currentHash": current_hash,
            "plannedHash": planned_hash,
            "onDiskChanged": file_changed,
            "sourceChanged": source_changed,
            "plannedDeletion": relative_path in planned_deletions,
        }

    if commit:
        session.commit()
    else:
        session.flush()
    return assessments
