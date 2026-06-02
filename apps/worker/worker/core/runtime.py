from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from worker.models.schemas import AppSettings


@dataclass(frozen=True)
class RuntimeCheck:
    ok: bool
    message: str
    path: str | None = None

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"ok": self.ok, "message": self.message}
        if self.path is not None:
            data["path"] = self.path
        return data


@dataclass(frozen=True)
class WebwrightReadiness:
    root: RuntimeCheck
    python: RuntimeCheck
    config: RuntimeCheck
    cli: RuntimeCheck

    @property
    def live_ok(self) -> bool:
        return self.root.ok and self.python.ok and self.config.ok and self.cli.ok


@dataclass(frozen=True)
class RuntimeProfile:
    mode: str
    python: str
    webwright_python: str
    webwright_root: str
    playwright_browsers_path: str | None
    template_path: str
    webwright_output_root: str
    execution_mode: str
    base_config: str
    model_config: str

    def subprocess_env(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        env = {**os.environ, **(extra or {})}
        env["TC_STUDIO_PYTHON"] = self.python
        if self.playwright_browsers_path:
            env["PLAYWRIGHT_BROWSERS_PATH"] = self.playwright_browsers_path
        return env

    @property
    def has_webwright_cli(self) -> bool:
        return self.check_webwright_readiness().live_ok

    def check_webwright_readiness(self) -> WebwrightReadiness:
        root = self._check_webwright_root()
        python = _check_command([self.webwright_python, "--version"], env=self.subprocess_env())
        config = self._check_webwright_config()
        cli = self._check_webwright_cli_import()
        return WebwrightReadiness(root=root, python=python, config=config, cli=cli)

    def _check_webwright_root(self) -> RuntimeCheck:
        if not self.webwright_root:
            return RuntimeCheck(False, "Webwright root is not configured")
        root = Path(self.webwright_root)
        if not root.exists():
            return RuntimeCheck(False, "Webwright root does not exist", str(root))
        if not root.is_dir():
            return RuntimeCheck(False, "Webwright root is not a directory", str(root))
        return RuntimeCheck(True, "Webwright root exists", str(root))

    def _check_webwright_config(self) -> RuntimeCheck:
        root = Path(self.webwright_root) if self.webwright_root else None
        if not root or not root.exists():
            return RuntimeCheck(False, "Webwright root is required before config validation")

        missing: list[str] = []
        for config_name in [self.base_config, self.model_config]:
            if not config_name:
                missing.append("<empty config path>")
                continue
            config_path = Path(config_name)
            if not config_path.is_absolute():
                config_path = root / config_name
            if not config_path.exists():
                missing.append(str(config_path))

        if missing:
            return RuntimeCheck(False, "Missing Webwright config: " + ", ".join(missing))
        return RuntimeCheck(True, "Webwright config files exist", str(root))

    def _check_webwright_cli_import(self) -> RuntimeCheck:
        if not self.webwright_root or not Path(self.webwright_root).exists():
            return RuntimeCheck(False, "Webwright root is required before CLI validation")

        script = (
            "import importlib.util\n"
            "spec = importlib.util.find_spec('webwright.run.cli')\n"
            "raise SystemExit(0 if spec else 1)\n"
        )
        return _check_command(
            [self.webwright_python, "-c", script],
            cwd=self.webwright_root,
            env=self.subprocess_env(),
            success_message="webwright.run.cli import probe passed",
            failure_message="webwright.run.cli is not importable",
        )


def _check_command(
    cmd: list[str],
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 30,
    success_message: str | None = None,
    failure_message: str | None = None,
) -> RuntimeCheck:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd, env=env)
    except Exception as exc:
        return RuntimeCheck(False, str(exc))

    output = (result.stdout or result.stderr or "").strip()
    if result.returncode == 0:
        return RuntimeCheck(True, success_message or output or "Command succeeded")
    return RuntimeCheck(False, failure_message or output or f"Command failed with exit code {result.returncode}")


def _bundled_resources_root() -> Path | None:
    explicit = os.environ.get("TC_STUDIO_RESOURCES")
    if explicit:
        path = Path(explicit)
        return path if path.exists() else None
    for candidate in [
        Path(__file__).resolve().parents[3] / "runtime-staging",
        Path(__file__).resolve().parents[5] / "runtime-staging",
    ]:
        if (candidate / "python").exists() or (candidate / "generated-template").exists():
            return candidate
    return None


def _bundled_python(resources: Path) -> str:
    win = resources / "python" / "python.exe"
    if win.exists():
        return str(win)
    for name in ("python3", "python"):
        candidate = resources / "python" / "bin" / name
        if candidate.exists():
            return str(candidate)
    return shutil.which("python") or sys.executable


def _default_template_path() -> Path:
    bundled = _bundled_resources_root()
    if bundled:
        tpl = bundled / "generated-template"
        if tpl.exists():
            return tpl
    monorepo = Path(__file__).resolve().parents[4] / "packages" / "generated-template"
    return monorepo


def resolve_runtime(settings: AppSettings | None = None) -> RuntimeProfile:
    from worker.core.config import get_data_dir, load_settings

    settings = settings or load_settings()
    runtime_cfg: dict[str, Any] = getattr(settings, "runtime", None) or {}
    webwright_cfg = settings.webwright
    generator_cfg = settings.generator

    mode = runtime_cfg.get("mode") or os.environ.get("TC_STUDIO_RUNTIME_MODE", "custom")
    resources = _bundled_resources_root()

    if mode == "bundled" and resources:
        python = runtime_cfg.get("python") or _bundled_python(resources)
        webwright_root = runtime_cfg.get("webwrightRoot") or str(resources / "webwright")
        browsers = runtime_cfg.get("playwrightBrowsersPath") or str(resources / "ms-playwright")
        template = runtime_cfg.get("templatePath") or str(resources / "generated-template")
        output_root = webwright_cfg.get("outputRoot") or str(get_data_dir() / "webwright-runs")
        return RuntimeProfile(
            mode="bundled",
            python=python,
            webwright_python=runtime_cfg.get("webwrightPython") or webwright_cfg.get("python") or python,
            webwright_root=webwright_root,
            playwright_browsers_path=browsers if Path(browsers).exists() else None,
            template_path=template,
            webwright_output_root=output_root,
            execution_mode=webwright_cfg.get("executionMode", "native"),
            base_config=webwright_cfg.get("baseConfig", "base.yaml"),
            model_config=webwright_cfg.get("modelConfig", "model_openai.yaml"),
        )

    python = (
        runtime_cfg.get("python")
        or webwright_cfg.get("python")
        or os.environ.get("TC_STUDIO_PYTHON")
        or shutil.which("python")
        or sys.executable
    )
    webwright_python = webwright_cfg.get("python") or python
    webwright_root = webwright_cfg.get("root", "")
    browsers = runtime_cfg.get("playwrightBrowsersPath") or os.environ.get("TC_STUDIO_PLAYWRIGHT_BROWSERS_PATH")
    template = generator_cfg.get("templatePath") or str(_default_template_path())
    output_root = webwright_cfg.get("outputRoot") or str(Path.home() / "webwright-runs")

    return RuntimeProfile(
        mode="custom",
        python=python,
        webwright_python=webwright_python,
        webwright_root=webwright_root,
        playwright_browsers_path=browsers,
        template_path=template,
        webwright_output_root=output_root,
        execution_mode=webwright_cfg.get("executionMode", "native"),
        base_config=webwright_cfg.get("baseConfig", "base.yaml"),
        model_config=webwright_cfg.get("modelConfig", "model_openai.yaml"),
    )


def apply_runtime_defaults(settings: AppSettings) -> AppSettings:
    """Seed generator/runtime paths when settings are first created."""
    if os.environ.get("TC_STUDIO_RUNTIME_MODE") == "bundled":
        settings.runtime["mode"] = "bundled"
    profile = resolve_runtime(settings)
    if not settings.generator.get("templatePath"):
        settings.generator["templatePath"] = profile.template_path
    if not settings.runtime.get("mode"):
        settings.runtime["mode"] = profile.mode
    if profile.mode == "bundled":
        settings.runtime.setdefault("python", profile.python)
        settings.runtime.setdefault("webwrightRoot", profile.webwright_root)
        settings.runtime.setdefault("templatePath", profile.template_path)
        if profile.playwright_browsers_path:
            settings.runtime.setdefault("playwrightBrowsersPath", profile.playwright_browsers_path)
    elif not settings.webwright.get("python"):
        settings.webwright["python"] = profile.python
    return settings
