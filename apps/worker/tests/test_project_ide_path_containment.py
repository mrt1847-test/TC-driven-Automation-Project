from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _generated_root(client: TestClient, project_id: str) -> Path:
    response = client.get(f"/projects/{project_id}")
    assert response.status_code == 200
    project = response.json()
    root = Path(project.get("generated_project_path") or project.get("generatedProjectPath"))
    root.mkdir(parents=True, exist_ok=True)
    return root


def test_generated_file_api_allows_nested_files(client: TestClient, project_id: str) -> None:
    root = _generated_root(client, project_id)

    created = client.post(
        f"/projects/{project_id}/generated-files/create",
        json={"path": "nested/ok.py", "content": "print('ok')\n"},
    )
    assert created.status_code == 200
    assert (root / "nested" / "ok.py").read_text(encoding="utf-8") == "print('ok')\n"

    updated = client.put(
        f"/projects/{project_id}/generated-files/content",
        json={"path": "nested/ok.py", "content": "print('updated')\n"},
    )
    assert updated.status_code == 200

    content = client.get(
        f"/projects/{project_id}/generated-files/content",
        params={"path": "nested/ok.py"},
    )
    assert content.status_code == 200
    assert content.json()["content"] == "print('updated')\n"

    search = client.get(f"/projects/{project_id}/search", params={"q": "updated"})
    assert search.status_code == 200
    assert any(item.get("path") == "nested/ok.py" for item in search.json())

    renamed = client.post(
        f"/projects/{project_id}/generated-files/rename",
        json={"old_path": "nested/ok.py", "new_path": "nested/renamed.py"},
    )
    assert renamed.status_code == 200
    assert not (root / "nested" / "ok.py").exists()
    assert (root / "nested" / "renamed.py").exists()

    deleted = client.delete(
        f"/projects/{project_id}/generated-files",
        params={"path": "nested/renamed.py"},
    )
    assert deleted.status_code == 200
    assert not (root / "nested" / "renamed.py").exists()


def test_generated_file_api_rejects_traversal_and_absolute_mutations(
    client: TestClient,
    project_id: str,
) -> None:
    root = _generated_root(client, project_id)
    outside = root.parent / "outside.txt"
    outside.write_text("outside original\n", encoding="utf-8")
    sibling = root.parent / f"{root.name}_evil"
    sibling.mkdir()
    sibling_file = sibling / "outside.txt"
    sibling_file.write_text("sibling original\n", encoding="utf-8")

    invalid_requests = [
        ("get", "../outside.txt", None),
        ("put", "../outside.txt", "mutated\n"),
        ("post", str(outside), "absolute\n"),
        ("post", "C:drive-qualified.txt", "drive\n"),
        ("post", r"\\server\share\evil.py", "unc\n"),
        ("put", f"../{sibling.name}/outside.txt", "sibling mutated\n"),
    ]

    for method, path, content in invalid_requests:
        if method == "get":
            response = client.get(
                f"/projects/{project_id}/generated-files/content",
                params={"path": path},
            )
        elif method == "put":
            response = client.put(
                f"/projects/{project_id}/generated-files/content",
                json={"path": path, "content": content},
            )
        else:
            response = client.post(
                f"/projects/{project_id}/generated-files/create",
                json={"path": path, "content": content},
            )
        assert response.status_code == 400, path

    assert outside.read_text(encoding="utf-8") == "outside original\n"
    assert sibling_file.read_text(encoding="utf-8") == "sibling original\n"
    assert not (root / "drive-qualified.txt").exists()


def test_generated_file_api_rejects_rename_and_recursive_delete_escapes(
    client: TestClient,
    project_id: str,
) -> None:
    root = _generated_root(client, project_id)
    inside = root / "nested" / "safe.py"
    inside.parent.mkdir(parents=True)
    inside.write_text("safe\n", encoding="utf-8")
    outside_dir = root.parent / "outside_dir"
    outside_dir.mkdir()
    outside_file = outside_dir / "victim.py"
    outside_file.write_text("victim\n", encoding="utf-8")

    rename_out = client.post(
        f"/projects/{project_id}/generated-files/rename",
        json={"old_path": "nested/safe.py", "new_path": "../outside_rename.py"},
    )
    assert rename_out.status_code == 400
    assert inside.exists()
    assert not (root.parent / "outside_rename.py").exists()

    rename_in = client.post(
        f"/projects/{project_id}/generated-files/rename",
        json={"old_path": "../outside_dir/victim.py", "new_path": "nested/victim.py"},
    )
    assert rename_in.status_code == 400
    assert outside_file.read_text(encoding="utf-8") == "victim\n"
    assert not (root / "nested" / "victim.py").exists()

    delete_escape = client.delete(
        f"/projects/{project_id}/generated-files",
        params={"path": "../outside_dir"},
    )
    assert delete_escape.status_code == 400
    assert outside_file.exists()


def test_generated_file_api_rejects_symlink_escape_when_supported(
    client: TestClient,
    project_id: str,
) -> None:
    root = _generated_root(client, project_id)
    outside_dir = root.parent / "symlink_target"
    outside_dir.mkdir()
    outside_file = outside_dir / "needle.py"
    outside_file.write_text("# needle outside\n", encoding="utf-8")
    link = root / "linked_out"
    try:
        link.symlink_to(outside_dir, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"Symlink creation is not available: {exc}")

    response = client.put(
        f"/projects/{project_id}/generated-files/content",
        json={"path": "linked_out/pwned.py", "content": "pwned\n"},
    )
    assert response.status_code == 400
    assert not (outside_dir / "pwned.py").exists()

    search = client.get(f"/projects/{project_id}/search", params={"q": "needle outside"})
    assert search.status_code == 200
    assert all("linked_out" not in item.get("path", "") for item in search.json())

    files = client.get(f"/projects/{project_id}/generated-files")
    assert files.status_code == 200
    assert all("linked_out" not in item.get("path", "") for item in files.json())


def test_generated_file_mutations_return_404_for_missing_project(client: TestClient) -> None:
    response = client.post(
        "/projects/missing/generated-files/create",
        json={"path": "safe.py", "content": ""},
    )
    assert response.status_code == 404
