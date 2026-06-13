from __future__ import annotations

import shutil
from pathlib import Path, PurePosixPath, PureWindowsPath

from sqlmodel import Session, select

from worker.models.db import TestCase


class ProjectPathError(ValueError):
    pass


def _root_path(root: Path) -> Path:
    return root.resolve(strict=False)


def _safe_relative_parts(rel_path: str) -> tuple[str, ...]:
    if not rel_path or "\x00" in rel_path:
        raise ProjectPathError("Generated file path is required")
    if rel_path.startswith(("\\", "/")):
        raise ProjectPathError("Generated file path must be relative")

    windows_path = PureWindowsPath(rel_path)
    if windows_path.drive or windows_path.is_absolute():
        raise ProjectPathError("Generated file path must be relative")

    normalized = rel_path.replace("\\", "/")
    posix_path = PurePosixPath(normalized)
    if posix_path.is_absolute():
        raise ProjectPathError("Generated file path must be relative")

    parts = posix_path.parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ProjectPathError("Generated file path cannot traverse outside the generated project")
    return tuple(parts)


def _ensure_inside_root(root: Path, target: Path) -> Path:
    root_resolved = _root_path(root)
    resolved = target.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ProjectPathError("Generated file path escapes the generated project") from exc
    if resolved == root_resolved:
        raise ProjectPathError("Generated file path must point inside the generated project")
    return resolved


def resolve_project_path(root: Path, rel_path: str) -> Path:
    parts = _safe_relative_parts(rel_path)
    return _ensure_inside_root(root, _root_path(root).joinpath(*parts))


def _is_safe_tree_entry(root: Path, path: Path) -> bool:
    if path.is_symlink():
        return False
    try:
        _ensure_inside_root(root, path)
    except ProjectPathError:
        return False
    return True


def list_file_tree(root: Path, base: Path | None = None) -> list[dict]:
    base = _root_path(base or root)
    root = _root_path(root)
    items = []
    if not root.exists():
        return items
    for path in sorted(root.rglob("*")):
        if not _is_safe_tree_entry(root, path):
            continue
        if path.name.startswith(".") or "__pycache__" in path.parts:
            continue
        rel = path.resolve(strict=False).relative_to(base).as_posix()
        items.append({
            "path": rel,
            "type": "directory" if path.is_dir() else "file",
        })
    return items


def read_file(root: Path, rel_path: str) -> str:
    target = resolve_project_path(root, rel_path)
    return target.read_text(encoding="utf-8")


def write_file(root: Path, rel_path: str, content: str) -> None:
    target = resolve_project_path(root, rel_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target = _ensure_inside_root(root, target)
    target.write_text(content, encoding="utf-8")


def create_file(root: Path, rel_path: str, content: str = "") -> None:
    write_file(root, rel_path, content)


def delete_file(root: Path, rel_path: str) -> None:
    target = resolve_project_path(root, rel_path)
    if target.is_file():
        target.unlink()
    elif target.is_dir():
        shutil.rmtree(target)


def rename_file(root: Path, old_path: str, new_path: str) -> None:
    source = resolve_project_path(root, old_path)
    target = resolve_project_path(root, new_path)
    source.rename(target)


def search_project(session: Session, project_id: str, root: Path, query: str) -> list[dict]:
    results = []
    q = query.lower()
    for case in session.exec(select(TestCase).where(TestCase.project_id == project_id)).all():
        if q in case.automation_key.lower() or q in case.title.lower():
            results.append({"type": "testcase", "automationKey": case.automation_key, "title": case.title})
    root = _root_path(root)
    if root.exists():
        for path in root.rglob("*"):
            if not _is_safe_tree_entry(root, path):
                continue
            if path.is_file() and path.suffix in {".py", ".yaml", ".json"}:
                try:
                    text = path.read_text(encoding="utf-8")
                except Exception:
                    continue
                if q in text.lower():
                    results.append({
                        "type": "file",
                        "path": path.resolve(strict=False).relative_to(root).as_posix(),
                        "match": "content",
                    })
    return results
