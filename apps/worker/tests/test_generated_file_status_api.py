from __future__ import annotations

import hashlib

from sqlmodel import Session, select

from worker.models.db import (
    GeneratedFile,
    GeneratedFileOrigin,
    GeneratedFileStatus,
    Project,
    RawAction,
    TestCase as DbTestCase,
    WebwrightRun,
)


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _tracked_file(
    session: Session,
    *,
    generated_root,
    project_id: str,
    file_id: str,
    path: str,
    stored_content: str,
    disk_content: str | None = None,
    status: str = GeneratedFileStatus.generated.value,
    automation_key: str | None = None,
    source_type: str | None = None,
    source_id: str | None = None,
    origins: list[tuple[str, str]] | None = None,
) -> None:
    target = generated_root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    if disk_content is not None:
        target.write_bytes(disk_content.encode("utf-8"))
    row = GeneratedFile(
        id=file_id,
        project_id=project_id,
        relative_path=path,
        automation_key=automation_key,
        source_type=source_type,
        source_id=source_id,
        content_hash=_hash_text(stored_content),
        status=status,
    )
    session.add(row)
    for origin_type, origin_id in origins or []:
        session.add(GeneratedFileOrigin(
            generated_file_id=file_id,
            origin_type=origin_type,
            origin_id=origin_id,
        ))


def _seed_status_graph(project_id: str, foreign_project_id: str, tmp_path) -> dict[str, str]:
    import worker.core.database as database

    generated_root = tmp_path / "generated-status"
    foreign_root = tmp_path / "foreign-generated-status"
    generated_root.mkdir()
    foreign_root.mkdir()
    with Session(database.engine) as session:
        project = session.get(Project, project_id)
        project.generated_project_path = str(generated_root)
        session.add(project)
        foreign_project = session.get(Project, foreign_project_id)
        foreign_project.generated_project_path = str(foreign_root)
        session.add(foreign_project)

        case = DbTestCase(
            id="tc_status_api",
            project_id=project_id,
            source_type="excel",
            source_case_id="TC-STATUS",
            title="Generated status API",
            steps_json="[]",
            automation_key="status_api",
            status="generated",
        )
        run = WebwrightRun(
            id="ww_status_api",
            project_id=project_id,
            test_case_id=case.id,
            automation_key=case.automation_key,
            status="completed",
        )
        action = RawAction(
            id="raw_status_api",
            webwright_run_id=run.id,
            automation_key=case.automation_key,
            order_index=1,
            type="click",
            selector="page.locator('#status')",
            target="Status",
        )
        session.add_all([case, run, action])

        _tracked_file(
            session,
            generated_root=generated_root,
            project_id=project_id,
            file_id="gf_status_clean",
            path="pages/clean.py",
            stored_content="clean\n",
            disk_content="clean\n",
            automation_key=case.automation_key,
            source_type="test_case",
            source_id=case.id,
            origins=[("test_case", case.id), ("raw_action", action.id)],
        )
        _tracked_file(
            session,
            generated_root=generated_root,
            project_id=project_id,
            file_id="gf_status_edited",
            path="tests/test_edited.py",
            stored_content="old edited\n",
            disk_content="old edited\n# user edit\n",
            automation_key=case.automation_key,
            source_type="test_case",
            source_id=case.id,
            origins=[("test_case", case.id)],
        )
        _tracked_file(
            session,
            generated_root=generated_root,
            project_id=project_id,
            file_id="gf_status_stale",
            path="flows/stale_flow.py",
            stored_content="stale but untouched\n",
            disk_content="stale but untouched\n",
            status=GeneratedFileStatus.stale.value,
            automation_key=case.automation_key,
            source_type="test_case",
            source_id=case.id,
            origins=[("test_case", case.id)],
        )
        _tracked_file(
            session,
            generated_root=generated_root,
            project_id=project_id,
            file_id="gf_status_conflict",
            path="pages/conflict.py",
            stored_content="conflict base\n",
            disk_content="conflict base\n# user edit\n",
            status=GeneratedFileStatus.stale.value,
            automation_key=case.automation_key,
            source_type="raw_action",
            source_id=action.id,
            origins=[("raw_action", action.id), ("webwright_run", run.id)],
        )
        _tracked_file(
            session,
            generated_root=generated_root,
            project_id=project_id,
            file_id="gf_status_obsolete",
            path="tests/test_obsolete.py",
            stored_content="obsolete\n",
            disk_content=None,
            status=GeneratedFileStatus.obsolete.value,
            automation_key="retired_case",
            source_type="test_case",
            source_id="tc_retired",
        )
        _tracked_file(
            session,
            generated_root=foreign_root,
            project_id=foreign_project_id,
            file_id="gf_status_foreign",
            path="pages/foreign.py",
            stored_content="foreign\n",
            disk_content="foreign\n# edit\n",
            status=GeneratedFileStatus.stale.value,
            automation_key="foreign",
        )
        session.commit()

    return {
        "case_id": "tc_status_api",
        "raw_action_id": "raw_status_api",
    }


def test_generated_file_status_api_returns_clean_empty_project(client, project_id: str) -> None:
    response = client.get(f"/projects/{project_id}/generated-files/status")

    assert response.status_code == 200
    body = response.json()
    assert body["projectId"] == project_id
    assert body["ok"] is True
    assert body["counts"] == {
        "total": 0,
        "generated": 0,
        "edited": 0,
        "stale": 0,
        "conflict": 0,
        "obsolete": 0,
    }
    assert body["files"] == []


def test_generated_file_status_api_summarizes_statuses_origins_and_guidance(
    client,
    project_id: str,
    tmp_path,
) -> None:
    import worker.core.database as database

    foreign_project_id = client.post("/projects", json={"name": "Foreign"}).json()["id"]
    seeded = _seed_status_graph(project_id, foreign_project_id, tmp_path)

    response = client.get(f"/projects/{project_id}/generated-files/status")

    assert response.status_code == 200
    body = response.json()
    assert body["projectId"] == project_id
    assert body["ok"] is False
    assert body["counts"] == {
        "total": 5,
        "generated": 1,
        "edited": 1,
        "stale": 1,
        "conflict": 1,
        "obsolete": 1,
    }
    assert body["editedFiles"] == ["tests/test_edited.py"]
    assert body["staleFiles"] == ["flows/stale_flow.py"]
    assert body["conflictFiles"] == ["pages/conflict.py"]
    assert body["obsoleteFiles"] == ["tests/test_obsolete.py"]
    assert [item["path"] for item in body["files"]] == [
        "pages/conflict.py",
        "tests/test_edited.py",
        "flows/stale_flow.py",
        "tests/test_obsolete.py",
        "pages/clean.py",
    ]
    assert "pages/foreign.py" not in {item["path"] for item in body["files"]}

    by_path = {item["path"]: item for item in body["files"]}
    edited = by_path["tests/test_edited.py"]
    assert edited["status"] == "edited"
    assert edited["onDiskChanged"] is True
    assert edited["sourceChanged"] is False
    assert edited["guidance"]["blocksGeneration"] is True
    assert edited["source"]["id"] == seeded["case_id"]
    assert edited["source"]["automationKey"] == "status_api"
    assert edited["origins"][0]["type"] == "test_case"
    assert edited["origins"][0]["title"] == "Generated status API"

    stale = by_path["flows/stale_flow.py"]
    assert stale["status"] == "stale"
    assert stale["onDiskChanged"] is False
    assert stale["sourceChanged"] is True
    assert stale["guidance"]["action"] == "regenerate"

    conflict = by_path["pages/conflict.py"]
    assert conflict["status"] == "conflict"
    assert conflict["onDiskChanged"] is True
    assert conflict["sourceChanged"] is True
    assert conflict["guidance"]["action"] == "resolve_conflict"
    raw_origin = next(origin for origin in conflict["origins"] if origin["type"] == "raw_action")
    assert raw_origin["id"] == seeded["raw_action_id"]
    assert raw_origin["testCaseId"] == seeded["case_id"]

    obsolete = by_path["tests/test_obsolete.py"]
    assert obsolete["status"] == "obsolete"
    assert obsolete["exists"] is False
    assert obsolete["guidance"]["action"] == "audit_only"

    with Session(database.engine) as session:
        rows = {
            row.relative_path: row.status
            for row in session.exec(select(GeneratedFile).where(GeneratedFile.project_id == project_id)).all()
        }
    assert rows["tests/test_edited.py"] == "edited"
    assert rows["flows/stale_flow.py"] == "stale"
    assert rows["pages/conflict.py"] == "conflict"


def test_generated_file_status_api_rejects_unknown_project(client) -> None:
    response = client.get("/projects/not-a-project/generated-files/status")

    assert response.status_code == 404
