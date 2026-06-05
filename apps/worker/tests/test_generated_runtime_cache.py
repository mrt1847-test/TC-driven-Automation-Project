from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

from sqlmodel import SQLModel, Session, create_engine, select

from worker.models.db import GeneratedRuntimeInstallState, Project
from worker.services import generated_runtime
from worker.services.generated_runtime import ensure_generated_runtime


def _profile(*, python: str = "python-a", browsers_path: str = "cache-a") -> SimpleNamespace:
    return SimpleNamespace(
        mode="custom",
        python=python,
        playwright_browsers_path=browsers_path,
        template_path="template-a",
        subprocess_env=lambda extra=None: extra or {},
    )


def _write_generated_project(root: Path, *, requirements: str = "pytest\n", manifest: str = "{}\n") -> None:
    (root / "runner").mkdir(parents=True, exist_ok=True)
    (root / "mappings").mkdir(parents=True, exist_ok=True)
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "requirements.txt").write_text(requirements, encoding="utf-8")
    (root / "runner" / "cli.py").write_text("print('runner')\n", encoding="utf-8")
    (root / "mappings" / "cases.yaml").write_text("cases: []\n", encoding="utf-8")
    (root / "config" / "runtime-manifest.json").write_text(manifest, encoding="utf-8")


def _session(tmp_path: Path) -> Session:
    engine = create_engine(f"sqlite:///{tmp_path / 'studio.db'}")
    SQLModel.metadata.create_all(engine)
    session = Session(engine)
    session.add(Project(id="proj_runtime", name="Runtime Project", root_path=str(tmp_path)))
    session.commit()
    return session


def _fake_command(calls: list[list[str]], *, pip_ok: bool = True, playwright_ok: bool = True, browser_ok: bool = True):
    def run(command: list[str], cwd: Path | None = None, env: dict | None = None):
        calls.append(command)
        if command[1:4] == ["-m", "pip", "install"]:
            return subprocess.CompletedProcess(command, 0 if pip_ok else 1, "pip ok", "pip failed")
        if command[1:4] == ["-m", "playwright", "install"]:
            return subprocess.CompletedProcess(command, 0 if playwright_ok else 1, "playwright ok", "playwright failed")
        if len(command) > 1 and command[1] == "-c":
            return subprocess.CompletedProcess(command, 0 if browser_ok else 1, "browser ok", "browser missing")
        return subprocess.CompletedProcess(command, 0, "", "")

    return run


def _command_count(calls: list[list[str]], marker: list[str]) -> int:
    return sum(1 for command in calls if command[1:1 + len(marker)] == marker)


def test_generated_runtime_cache_hit_skips_redundant_install_commands(monkeypatch, tmp_path: Path) -> None:
    generated = tmp_path / "generated"
    _write_generated_project(generated)
    monkeypatch.setattr(generated_runtime, "resolve_runtime", lambda: _profile())
    calls: list[list[str]] = []
    monkeypatch.setattr(generated_runtime, "_run_command", _fake_command(calls))

    with _session(tmp_path) as session:
        first = ensure_generated_runtime(generated, install=True, session=session, project_id="proj_runtime")

        assert first["ok"] is True
        assert first["cache"]["status"] == "stored"
        assert _command_count(calls, ["-m", "pip", "install"]) == 1
        assert _command_count(calls, ["-m", "playwright", "install"]) == 1

        calls.clear()
        second = ensure_generated_runtime(generated, install=True, session=session, project_id="proj_runtime")

        assert second["ok"] is True
        assert second["cache"]["status"] == "hit"
        assert second["message"] == "Generated runtime is ready (cached)"
        assert _command_count(calls, ["-m", "pip", "install"]) == 0
        assert _command_count(calls, ["-m", "playwright", "install"]) == 0
        assert _command_count(calls, ["-c"]) == 1

        states = session.exec(select(GeneratedRuntimeInstallState)).all()
        assert len(states) == 1
        assert states[0].status == "ready"


def test_generated_runtime_cache_invalidates_on_runtime_inputs(monkeypatch, tmp_path: Path) -> None:
    generated = tmp_path / "generated"
    _write_generated_project(generated)
    profile_state = {"python": "python-a", "browsers_path": "cache-a"}
    monkeypatch.setattr(
        generated_runtime,
        "resolve_runtime",
        lambda: _profile(python=profile_state["python"], browsers_path=profile_state["browsers_path"]),
    )
    calls: list[list[str]] = []
    monkeypatch.setattr(generated_runtime, "_run_command", _fake_command(calls))

    with _session(tmp_path) as session:
        assert ensure_generated_runtime(generated, install=True, session=session, project_id="proj_runtime")["ok"] is True

        calls.clear()
        _write_generated_project(generated, requirements="pytest\nplaywright\n")
        requirements_changed = ensure_generated_runtime(generated, install=True, session=session, project_id="proj_runtime")
        assert requirements_changed["ok"] is True
        assert requirements_changed["cache"]["installReason"] == "stale"
        assert "requirementsHash" in requirements_changed["cache"]["staleFields"]
        assert _command_count(calls, ["-m", "pip", "install"]) == 1

        calls.clear()
        profile_state["python"] = "python-b"
        profile_changed = ensure_generated_runtime(generated, install=True, session=session, project_id="proj_runtime")
        assert profile_changed["ok"] is True
        assert "runtimeProfileHash" in profile_changed["cache"]["staleFields"]
        assert "pythonPath" in profile_changed["cache"]["staleFields"]
        assert _command_count(calls, ["-m", "pip", "install"]) == 1

        calls.clear()
        profile_state["browsers_path"] = "cache-b"
        browser_cache_changed = ensure_generated_runtime(generated, install=True, session=session, project_id="proj_runtime")
        assert browser_cache_changed["ok"] is True
        assert "browserCachePath" in browser_cache_changed["cache"]["staleFields"]
        assert _command_count(calls, ["-m", "playwright", "install"]) == 1


def test_generated_runtime_failed_installs_are_not_cached_as_ready(monkeypatch, tmp_path: Path) -> None:
    generated = tmp_path / "generated"
    _write_generated_project(generated)
    monkeypatch.setattr(generated_runtime, "resolve_runtime", lambda: _profile())
    calls: list[list[str]] = []
    monkeypatch.setattr(generated_runtime, "_run_command", _fake_command(calls, pip_ok=False))

    with _session(tmp_path) as session:
        failed = ensure_generated_runtime(generated, install=True, session=session, project_id="proj_runtime")

        assert failed["ok"] is False
        assert failed["message"] == "pip install failed"
        assert session.exec(select(GeneratedRuntimeInstallState)).all() == []

        calls.clear()
        monkeypatch.setattr(generated_runtime, "_run_command", _fake_command(calls))
        recovered = ensure_generated_runtime(generated, install=True, session=session, project_id="proj_runtime")

        assert recovered["ok"] is True
        assert recovered["cache"]["status"] == "stored"
        assert _command_count(calls, ["-m", "pip", "install"]) == 1
