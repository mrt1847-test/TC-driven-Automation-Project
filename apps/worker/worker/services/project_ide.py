from __future__ import annotations

from pathlib import Path

from sqlmodel import Session, select

from worker.models.db import GeneratedFile, TestCase


def list_file_tree(root: Path, base: Path | None = None) -> list[dict]:
    base = base or root
    items = []
    if not root.exists():
        return items
    for path in sorted(root.rglob("*")):
        if path.name.startswith(".") or "__pycache__" in path.parts:
            continue
        rel = path.relative_to(base).as_posix()
        items.append({
            "path": rel,
            "type": "directory" if path.is_dir() else "file",
        })
    return items


def read_file(root: Path, rel_path: str) -> str:
    target = (root / rel_path).resolve()
    if not str(target).startswith(str(root.resolve())):
        raise PermissionError("Invalid path")
    return target.read_text(encoding="utf-8")


def write_file(root: Path, rel_path: str, content: str) -> None:
    target = root / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def create_file(root: Path, rel_path: str, content: str = "") -> None:
    write_file(root, rel_path, content)


def delete_file(root: Path, rel_path: str) -> None:
    target = root / rel_path
    if target.is_file():
        target.unlink()
    elif target.is_dir():
        import shutil
        shutil.rmtree(target)


def rename_file(root: Path, old_path: str, new_path: str) -> None:
    (root / old_path).rename(root / new_path)


def search_project(session: Session, project_id: str, root: Path, query: str) -> list[dict]:
    results = []
    q = query.lower()
    for case in session.exec(select(TestCase).where(TestCase.project_id == project_id)).all():
        if q in case.automation_key.lower() or q in case.title.lower():
            results.append({"type": "testcase", "automationKey": case.automation_key, "title": case.title})
    if root.exists():
        for path in root.rglob("*"):
            if path.is_file() and path.suffix in {".py", ".yaml", ".json"}:
                try:
                    text = path.read_text(encoding="utf-8")
                except Exception:
                    continue
                if q in text.lower():
                    results.append({"type": "file", "path": path.relative_to(root).as_posix(), "match": "content"})
    return results
