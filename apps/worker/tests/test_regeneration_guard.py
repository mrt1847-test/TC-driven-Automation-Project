from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlmodel import Session, select

from worker.models.db import (
    CaseActionMapping,
    CaseActionMappingAction,
    GeneratedFile,
    PageObjectMethod,
    Project,
    RawAction,
    TestCase as DbTestCase,
    TestCaseStatus as DbTestCaseStatus,
    WebwrightRun,
)
from worker.services.generated_file_status import hash_file
from worker.services.project_generator import GenerationConflictError, generate_project


def _patch_template(monkeypatch, tmp_path: Path) -> Path:
    import worker.services.project_generator as project_generator

    template = tmp_path / "guard-template"
    (template / "runner").mkdir(parents=True)
    (template / "runner" / "cli.py").write_text("# runtime\n", encoding="utf-8")
    (template / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    monkeypatch.setattr(project_generator, "load_settings", lambda: None)
    monkeypatch.setattr(
        project_generator,
        "resolve_runtime",
        lambda _settings: SimpleNamespace(template_path=str(template)),
    )
    return template


def _manifest_profile(template: Path, *, browsers_path: str = "C:/ms-playwright") -> SimpleNamespace:
    return SimpleNamespace(
        mode="custom",
        python="C:/Python311/python.exe",
        webwright_python="C:/Python311/python.exe",
        webwright_root="C:/Webwright",
        playwright_browsers_path=browsers_path,
        template_path=str(template),
        webwright_output_root="C:/tc-studio/webwright-runs",
        execution_mode="native",
        base_config="base.yaml",
        model_config="model_openai.yaml",
        api_provider="openai",
        model_name="gpt-5-mini",
        webwright_shell="C:/Program Files/Git/bin/bash.exe",
        webwright_step_limit=30,
        webwright_run_timeout_seconds=180,
    )


def _seed_case(
    session: Session,
    *,
    project_id: str,
    case: DbTestCase,
    suffix: str,
) -> None:
    run_id = f"ww_guard_{suffix}"
    action_id = f"raw_guard_{suffix}"
    mapping_id = f"map_guard_{suffix}"
    case.status = DbTestCaseStatus.mapped.value
    session.add(case)
    session.add(WebwrightRun(
        id=run_id,
        project_id=project_id,
        test_case_id=case.id,
        automation_key=case.automation_key,
        status="completed",
    ))
    session.add(RawAction(
        id=action_id,
        webwright_run_id=run_id,
        automation_key=case.automation_key,
        order_index=1,
        type="click",
        selector=f"page.locator('#{suffix}')",
    ))
    session.add(CaseActionMapping(
        id=mapping_id,
        test_case_id=case.id,
        raw_action_id=action_id,
        tc_step_index=1,
        normalized_step_id=f"flow_{suffix}",
        normalized_step_name=f"click_{suffix}",
        pom_method_name=f"click_{suffix}",
        status="mapped",
    ))
    session.add(CaseActionMappingAction(
        mapping_id=mapping_id,
        raw_action_id=action_id,
        order_index=0,
    ))


def _change_first_method_selector(session: Session, selector: str) -> None:
    method = session.exec(select(PageObjectMethod)).first()
    assert method is not None
    plan = json.loads(method.body_plan_json)
    plan[0]["selector"] = selector
    method.selector = selector
    method.body_plan_json = json.dumps(plan, sort_keys=True, separators=(",", ":"))
    session.add(method)


def _hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hash_file(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _replace_protected_region(content: str, name: str, body: str) -> str:
    begin = f'# <tc-protected name="{name}">'
    end = "# </tc-protected>"
    begin_index = content.index(begin)
    body_start = content.index("\n", begin_index) + 1
    end_index = content.index(end, body_start)
    end_line_start = content.rfind("\n", 0, end_index) + 1
    return content[:body_start] + body + content[end_line_start:]


def test_full_regeneration_is_byte_stable_when_inputs_are_unchanged(
    monkeypatch,
    tmp_path,
    project_id: str,
    imported_case: dict,
) -> None:
    import worker.core.database as database

    _patch_template(monkeypatch, tmp_path)
    project_root = tmp_path / "stable-full"

    with Session(database.engine) as session:
        case = session.get(DbTestCase, imported_case["id"])
        _seed_case(session, project_id=project_id, case=case, suffix="stable")
        session.commit()

        first = generate_project(session, project_id, project_root, mode="full")
        before_hashes = _hashes(first.output)
        first_rows = {
            row.relative_path: row.content_hash
            for row in session.exec(select(GeneratedFile).where(GeneratedFile.project_id == project_id)).all()
        }

        second = generate_project(session, project_id, project_root, mode="full")
        after_hashes = _hashes(second.output)
        second_rows = {
            row.relative_path: row.content_hash
            for row in session.exec(select(GeneratedFile).where(GeneratedFile.project_id == project_id)).all()
        }

        assert before_hashes == after_hashes
        assert first_rows == second_rows
        assert second.changed_files == []
        assert second.conflict_files == []
        assert second.edited_files == []


def test_full_generation_writes_git_ready_ignore_and_skips_template_run_artifacts(
    monkeypatch,
    tmp_path,
    project_id: str,
    imported_case: dict,
) -> None:
    import worker.core.database as database

    template = _patch_template(monkeypatch, tmp_path)
    (template / ".pytest_cache").mkdir()
    (template / ".pytest_cache" / "README.md").write_text("cache\n", encoding="utf-8")
    (template / "__pycache__").mkdir()
    (template / "__pycache__" / "runtime.pyc").write_text("cache\n", encoding="utf-8")
    (template / ".env").write_text("OPENAI_API_KEY=should_not_copy\n", encoding="utf-8")
    (template / "config").mkdir()
    (template / "config" / "env.stg.secret.json").write_text('{"apiKey": "should_not_copy"}\n', encoding="utf-8")
    (template / "config" / "storage-state.json").write_text('{"cookies": []}\n', encoding="utf-8")
    (template / "artifacts" / "runs" / "stale").mkdir(parents=True)
    (template / "artifacts" / "runs" / "stale" / "results.json").write_text("{}\n", encoding="utf-8")

    with Session(database.engine) as session:
        case = session.get(DbTestCase, imported_case["id"])
        _seed_case(session, project_id=project_id, case=case, suffix="gitignore")
        session.commit()

        generated = generate_project(session, project_id, tmp_path / "git-ready-output", mode="full")

        gitignore = (generated.output / ".gitignore").read_text(encoding="utf-8")
        assert "# TC Automation Studio generated project" in gitignore
        assert "artifacts/runs/*" in gitignore
        assert "!artifacts/runs/.gitkeep" in gitignore
        assert ".pytest_cache/" in gitignore
        assert ".venv/" in gitignore
        assert "config/*.secret.json" in gitignore
        assert "config/storage-state*.json" in gitignore
        assert "playwright-report/" in gitignore
        assert "*.log" in gitignore
        assert (generated.output / "artifacts" / "runs" / ".gitkeep").exists()
        assert not (generated.output / ".pytest_cache").exists()
        assert not (generated.output / "__pycache__").exists()
        assert not (generated.output / ".env").exists()
        assert not (generated.output / "config" / "env.stg.secret.json").exists()
        assert not (generated.output / "config" / "storage-state.json").exists()
        assert not (generated.output / "artifacts" / "runs" / "stale" / "results.json").exists()


def test_generation_writes_runtime_manifest_contract_and_tracks_metadata(
    monkeypatch,
    tmp_path,
    project_id: str,
    imported_case: dict,
) -> None:
    import worker.core.database as database
    import worker.services.project_generator as project_generator

    template = _patch_template(monkeypatch, tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "value-visible-only-via-env-123456789")
    (template / "requirements.txt").write_text(
        "playwright>=1.49.0\n"
        "pytest>=8.3.0\n"
        "# local comments stay out of manifest package list\n"
        "pytest-playwright>=0.6.0\n",
        encoding="utf-8",
    )
    settings = SimpleNamespace(runner={"defaultBrowser": "chromium", "defaultEnv": "qa", "headless": False})
    monkeypatch.setattr(project_generator, "load_settings", lambda: settings)
    monkeypatch.setattr(project_generator, "resolve_runtime", lambda _settings: _manifest_profile(template))

    with Session(database.engine) as session:
        case = session.get(DbTestCase, imported_case["id"])
        _seed_case(session, project_id=project_id, case=case, suffix="manifest")
        session.commit()

        first = generate_project(session, project_id, tmp_path / "manifest-output", mode="full")
        manifest_path = first.output / "config" / "runtime-manifest.json"
        manifest_bytes = manifest_path.read_bytes()
        manifest_text = manifest_path.read_text(encoding="utf-8")
        manifest = json.loads(manifest_text)

        assert manifest["schema"] == "tc-studio.generated-runtime-manifest"
        assert manifest["manifestVersion"] == 1
        assert manifest["compatibility"] == {"standalone": True, "studio": True}
        assert manifest["packages"]["file"] == "requirements.txt"
        assert manifest["packages"]["requirements"] == [
            "playwright>=1.49.0",
            "pytest>=8.3.0",
            "pytest-playwright>=0.6.0",
        ]
        assert manifest["playwright"]["defaultBrowser"] == "chromium"
        assert manifest["playwright"]["browserCache"]["studioDefault"] == "C:/ms-playwright"
        assert manifest["fixturePolicy"]["version"] == "B3-04"
        assert manifest["runnerDefaults"] == {"browser": "chromium", "env": "qa", "headless": False}
        assert "python -m runner.cli run --env qa --browser chromium --all" in manifest["commands"]["standalone"]
        assert manifest["commands"]["studio"]["runtimeProfilePython"] == "C:/Python311/python.exe"
        assert "generatedAt" not in manifest
        assert "value-visible-only-via-env-123456789" not in manifest_text
        assert "OPENAI_API_KEY" not in manifest_text

        row = session.exec(
            select(GeneratedFile).where(
                GeneratedFile.project_id == project_id,
                GeneratedFile.relative_path == "config/runtime-manifest.json",
            )
        ).one()
        assert row.automation_key is None
        assert row.source_type is None
        assert row.content_hash == hash_file(manifest_path)

        second = generate_project(session, project_id, tmp_path / "manifest-output", mode="full")
        assert manifest_path.read_bytes() == manifest_bytes
        assert second.changed_files == []


def test_selected_generation_updates_runtime_manifest_only_for_runtime_input_changes_and_blocks_edits(
    monkeypatch,
    tmp_path,
    project_id: str,
    imported_case: dict,
) -> None:
    import worker.core.database as database
    import worker.services.project_generator as project_generator

    template = _patch_template(monkeypatch, tmp_path)
    profile_state = {"browsers_path": "C:/ms-playwright"}
    monkeypatch.setattr(
        project_generator,
        "resolve_runtime",
        lambda _settings: _manifest_profile(template, browsers_path=profile_state["browsers_path"]),
    )

    with Session(database.engine) as session:
        case = session.get(DbTestCase, imported_case["id"])
        _seed_case(session, project_id=project_id, case=case, suffix="manifest_selected")
        session.commit()

        full = generate_project(session, project_id, tmp_path / "manifest-selected-output", mode="full")
        manifest_path = full.output / "config" / "runtime-manifest.json"
        original_manifest = manifest_path.read_bytes()

        selected_same_runtime = generate_project(session, project_id, tmp_path / "manifest-selected-output", [case.id])
        assert manifest_path.read_bytes() == original_manifest
        assert "config/runtime-manifest.json" not in selected_same_runtime.affected_files
        assert "config/runtime-manifest.json" not in selected_same_runtime.changed_files

        profile_state["browsers_path"] = "D:/ms-playwright"
        selected_changed_runtime = generate_project(
            session,
            project_id,
            tmp_path / "manifest-selected-output",
            [case.id],
        )
        assert "config/runtime-manifest.json" in selected_changed_runtime.affected_files
        assert "config/runtime-manifest.json" in selected_changed_runtime.changed_files
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["runtimeProfileDefaults"]["playwrightBrowsersPath"] == "D:/ms-playwright"

        edited_manifest = manifest_path.read_text(encoding="utf-8") + "\n# user edit\n"
        manifest_path.write_text(edited_manifest, encoding="utf-8")

        with pytest.raises(GenerationConflictError) as exc_info:
            generate_project(session, project_id, tmp_path / "manifest-selected-output", [case.id])

        blocked_files = exc_info.value.edited_files + exc_info.value.conflict_files
        assert "config/runtime-manifest.json" in blocked_files
        assert manifest_path.read_text(encoding="utf-8") == edited_manifest


def test_protected_region_edits_survive_selected_regeneration(
    monkeypatch,
    tmp_path,
    project_id: str,
    imported_case: dict,
) -> None:
    import worker.core.database as database

    _patch_template(monkeypatch, tmp_path)
    project_root = tmp_path / "protected-region-output"

    with Session(database.engine) as session:
        case = session.get(DbTestCase, imported_case["id"])
        _seed_case(session, project_id=project_id, case=case, suffix="protected")
        session.commit()
        generated = generate_project(session, project_id, project_root, mode="full")
        page_path = generated.output / "pages" / "generated_page.py"
        helper_body = (
            "    def manual_helper(self):\n"
            "        return \"kept across regeneration\"\n"
        )
        page_path.write_text(
            _replace_protected_region(
                page_path.read_text(encoding="utf-8"),
                "generated-page-helpers",
                helper_body,
            ),
            encoding="utf-8",
        )

        _change_first_method_selector(session, "page.locator('#protected-refresh')")
        session.commit()

        result = generate_project(session, project_id, project_root, [case.id])

        assert "pages/generated_page.py" in result.stale_files
        assert result.edited_files == []
        assert result.conflict_files == []
        page_content = page_path.read_text(encoding="utf-8")
        assert helper_body in page_content
        assert "protected-refresh" in page_content
        row = session.exec(
            select(GeneratedFile).where(
                GeneratedFile.project_id == project_id,
                GeneratedFile.relative_path == "pages/generated_page.py",
            )
        ).first()
        assert row.status == "generated"
        assert row.content_hash == hash_file(page_path)


def test_full_and_selected_generation_preserve_existing_git_metadata(
    monkeypatch,
    tmp_path,
    project_id: str,
    imported_case: dict,
) -> None:
    import worker.core.database as database

    _patch_template(monkeypatch, tmp_path)
    project_root = tmp_path / "git-preserved-output"

    with Session(database.engine) as session:
        case = session.get(DbTestCase, imported_case["id"])
        _seed_case(session, project_id=project_id, case=case, suffix="gitmeta")
        session.commit()
        first = generate_project(session, project_id, project_root, mode="full")

        git_dir = first.output / ".git"
        git_dir.mkdir()
        (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        (git_dir / "config").write_text("[core]\n\trepositoryformatversion = 0\n", encoding="utf-8")
        (first.output / ".gitattributes").write_text("*.py text eol=lf\n", encoding="utf-8")
        (first.output / ".gitmodules").write_text("[submodule]\n", encoding="utf-8")
        (first.output / "scratch.txt").write_text("remove me\n", encoding="utf-8")

        second = generate_project(session, project_id, project_root, mode="full")

        assert (second.output / ".git" / "HEAD").read_text(encoding="utf-8") == "ref: refs/heads/main\n"
        assert (second.output / ".git" / "config").read_text(encoding="utf-8").startswith("[core]")
        assert (second.output / ".gitattributes").read_text(encoding="utf-8") == "*.py text eol=lf\n"
        assert (second.output / ".gitmodules").read_text(encoding="utf-8") == "[submodule]\n"
        assert not (second.output / "scratch.txt").exists()
        assert ".git/HEAD" not in second.affected_files
        assert ".gitattributes" not in second.affected_files
        assert second.changed_files == []

        selected = generate_project(session, project_id, project_root, [case.id])

        assert (selected.output / ".git" / "HEAD").read_text(encoding="utf-8") == "ref: refs/heads/main\n"
        assert (selected.output / ".gitattributes").read_text(encoding="utf-8") == "*.py text eol=lf\n"
        assert ".git/HEAD" not in selected.preserved_files


def test_full_regeneration_blocks_edited_tracked_delete_before_rmtree(
    monkeypatch,
    tmp_path,
    project_id: str,
    imported_case: dict,
) -> None:
    import worker.core.database as database

    _patch_template(monkeypatch, tmp_path)
    project_root = tmp_path / "blocked-full-delete"

    with Session(database.engine) as session:
        selected = session.get(DbTestCase, imported_case["id"])
        unrelated = DbTestCase(
            id="tc_guard_unrelated",
            project_id=project_id,
            source_type="excel",
            source_case_id="TC-GUARD-UNRELATED",
            title="Guard unrelated",
            automation_key="guard_unrelated",
        )
        _seed_case(session, project_id=project_id, case=selected, suffix="selected_delete")
        _seed_case(session, project_id=project_id, case=unrelated, suffix="unrelated_delete")
        session.commit()
        generated = generate_project(session, project_id, project_root, mode="full")

        selected_path = f"tests/test_{selected.automation_key}.py"
        unrelated_path = f"tests/test_{unrelated.automation_key}.py"
        selected_file = generated.output / selected_path
        unrelated_file = generated.output / unrelated_path
        selected_content = selected_file.read_text(encoding="utf-8") + "\n# user edit\n"
        selected_file.write_text(selected_content, encoding="utf-8")
        unrelated_content = unrelated_file.read_text(encoding="utf-8")
        selected.status = DbTestCaseStatus.deleted.value
        session.add(selected)
        session.commit()

        with pytest.raises(GenerationConflictError) as exc_info:
            generate_project(session, project_id, project_root, mode="full")

        assert selected_path in exc_info.value.conflict_files
        assert selected_file.read_text(encoding="utf-8") == selected_content
        assert unrelated_file.read_text(encoding="utf-8") == unrelated_content
        assert generated.output.exists()
        assert session.exec(
            select(GeneratedFile).where(
                GeneratedFile.project_id == project_id,
                GeneratedFile.relative_path == selected_path,
            )
        ).first().status == "conflict"


def test_selected_generation_api_returns_conflict_summary_before_writes(
    monkeypatch,
    tmp_path,
    client,
    project_id: str,
    imported_case: dict,
) -> None:
    import worker.core.database as database
    import worker.routers.generation as generation_router

    _patch_template(monkeypatch, tmp_path)
    monkeypatch.setattr(generation_router, "ensure_generated_runtime", lambda _path, install, **_kwargs: {"ok": True})

    with Session(database.engine) as session:
        project = session.get(Project, project_id)
        case = session.get(DbTestCase, imported_case["id"])
        _seed_case(session, project_id=project_id, case=case, suffix="api_conflict")
        session.commit()
        generated = generate_project(session, project_id, Path(project.root_path), mode="full")
        page_path = generated.output / "pages" / "generated_page.py"
        page_content = page_path.read_text(encoding="utf-8") + "\n# user edit\n"
        page_path.write_text(page_content, encoding="utf-8")
        _change_first_method_selector(session, "page.locator('#changed-api-conflict')")
        session.commit()

    response = client.post(
        f"/projects/{project_id}/generate/selected",
        json={"caseIds": [imported_case["id"]]},
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "pages/generated_page.py" in detail["conflictFiles"]
    assert "pages/generated_page.py" in detail["affectedFiles"]
    assert page_path.read_text(encoding="utf-8") == page_content
