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
    shell: RuntimeCheck

    @property
    def live_ok(self) -> bool:
        return self.root.ok and self.python.ok and self.config.ok and self.cli.ok and self.shell.ok


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
    api_provider: str
    model_name: str | None
    webwright_shell: str | None
    webwright_step_limit: int | None
    webwright_run_timeout_seconds: int

    def subprocess_env(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        env = {**_dotenv_env(self.webwright_root), **os.environ, **(extra or {})}
        env["TC_STUDIO_PYTHON"] = self.python
        webwright_python_dir = str(Path(self.webwright_python).parent) if self.webwright_python else ""
        if webwright_python_dir and Path(webwright_python_dir).exists():
            existing_path = env.get("PATH", "")
            env["PATH"] = webwright_python_dir + (os.pathsep + existing_path if existing_path else "")
            env.setdefault("VIRTUAL_ENV", str(Path(webwright_python_dir).parent))
        env.setdefault("PYTHONUTF8", "1")
        env.setdefault("PYTHONIOENCODING", "utf-8")
        if self.webwright_shell:
            env["TC_WEBWRIGHT_SHELL"] = self.webwright_shell
        _map_generic_api_key(env, self.api_provider, self.model_config)
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
        shell = self._check_webwright_shell()
        return WebwrightReadiness(root=root, python=python, config=config, cli=cli, shell=shell)

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
        resolved: list[str] = []
        for config_name in [self.base_config, self.model_config]:
            if not config_name:
                missing.append("<empty config path>")
                continue
            config_path = _resolve_webwright_config(root, config_name)
            if not config_path.exists():
                missing.append(config_name)
            else:
                resolved.append(str(config_path))

        if missing:
            return RuntimeCheck(False, "Missing Webwright config: " + ", ".join(missing))
        return RuntimeCheck(True, "Webwright config files exist", "; ".join(resolved))

    def _check_webwright_cli_import(self) -> RuntimeCheck:
        if not self.webwright_root or not Path(self.webwright_root).exists():
            return RuntimeCheck(False, "Webwright root is required before CLI validation")

        root = str(Path(self.webwright_root).resolve())
        script = (
            "import importlib.util\n"
            "from pathlib import Path\n"
            f"root = Path({root!r})\n"
            "spec = importlib.util.find_spec('webwright.run.cli')\n"
            "if not spec or not spec.origin:\n"
            "    raise SystemExit(1)\n"
            "origin = Path(spec.origin).resolve()\n"
            "try:\n"
            "    origin.relative_to(root)\n"
            "except ValueError:\n"
            "    raise SystemExit(1)\n"
            "raise SystemExit(0)\n"
        )
        return _check_command(
            [self.webwright_python, "-c", script],
            cwd=self.webwright_root,
            env=self.subprocess_env(),
            success_message="webwright.run.cli import probe passed",
            failure_message="webwright.run.cli is not importable",
        )

    def _check_webwright_shell(self) -> RuntimeCheck:
        if self.execution_mode == "wsl":
            return RuntimeCheck(True, "WSL supplies the Webwright shell")
        if sys.platform != "win32":
            return RuntimeCheck(True, "Native POSIX shell expected")
        shell = self.webwright_shell or _detect_windows_bash()
        if not shell:
            return RuntimeCheck(False, "Windows native Webwright requires Git Bash or a bundled bash")
        path = Path(shell)
        if not path.exists():
            return RuntimeCheck(False, "Configured Webwright shell does not exist", shell)
        result = _check_command(
            [shell, "-lc", "echo OK"],
            env=self.subprocess_env(),
            success_message="Webwright shell probe passed",
            failure_message="Webwright shell probe failed",
        )
        return RuntimeCheck(result.ok, result.message, shell)


def _check_command(
    cmd: list[str],
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 30,
    success_message: str | None = None,
    failure_message: str | None = None,
) -> RuntimeCheck:
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=cwd,
            env=env,
        )
    except Exception as exc:
        return RuntimeCheck(False, str(exc))

    output = (result.stdout or result.stderr or "").strip()
    if result.returncode == 0:
        return RuntimeCheck(True, success_message or output or "Command succeeded")
    return RuntimeCheck(False, failure_message or output or f"Command failed with exit code {result.returncode}")


def _resolve_webwright_config(root: Path, config_name: str) -> Path:
    config_path = Path(config_name)
    if config_path.is_absolute():
        return config_path

    candidates = [
        root / config_name,
        root / "src" / "webwright" / "config" / config_name,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _dotenv_env(webwright_root: str) -> dict[str, str]:
    env: dict[str, str] = {}
    for path in [
        _repo_root() / ".env",
        Path(webwright_root) / ".env" if webwright_root else None,
    ]:
        if not path or not path.exists():
            continue
        env.update(_parse_dotenv(path))
    return env


def _parse_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key:
            values[key] = value
    return values


def _map_generic_api_key(env: dict[str, str], api_provider: str, model_config: str) -> None:
    generic_key = env.get("API_KEY")
    if not generic_key:
        return

    provider = (api_provider or "").lower()
    model = (model_config or "").lower()
    if "claude" in model or provider in {"anthropic", "claude"}:
        env.setdefault("ANTHROPIC_API_KEY", generic_key)
    elif "openrouter" in model or provider == "openrouter":
        env.setdefault("OPENROUTER_API_KEY", generic_key)
    elif "openai" in model or provider == "openai":
        env.setdefault("OPENAI_API_KEY", generic_key)


def _detect_windows_bash() -> str | None:
    if sys.platform != "win32":
        return None
    discovered = shutil.which("bash.exe") or shutil.which("sh.exe")
    if discovered:
        return discovered
    for candidate in [
        Path(r"C:\Program Files\Git\bin\bash.exe"),
        Path(r"C:\Program Files\Git\usr\bin\bash.exe"),
        Path(r"C:\Program Files (x86)\Git\bin\bash.exe"),
        Path(r"C:\Program Files (x86)\Git\usr\bin\bash.exe"),
    ]:
        if candidate.exists():
            return str(candidate)
    return None


def _optional_int(value: Any) -> int | None:
    if value in {None, ""}:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _positive_int(value: Any, default: int) -> int:
    parsed = _optional_int(value)
    return parsed or default


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


def _vendored_webwright_root() -> Path | None:
    candidate = _repo_root() / "third_party" / "webwright"
    if (candidate / "src" / "webwright" / "run" / "cli.py").exists():
        return candidate
    return None


def _default_webwright_root() -> str:
    vendored = _vendored_webwright_root()
    return str(vendored) if vendored else ""


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
            api_provider=webwright_cfg.get("apiProvider", ""),
            model_name=webwright_cfg.get("modelName") or None,
            webwright_shell=webwright_cfg.get("shell") or os.environ.get("TC_WEBWRIGHT_SHELL") or _detect_windows_bash(),
            webwright_step_limit=_optional_int(webwright_cfg.get("stepLimit")),
            webwright_run_timeout_seconds=_positive_int(webwright_cfg.get("runTimeoutSeconds"), 300),
        )

    python = (
        runtime_cfg.get("python")
        or webwright_cfg.get("python")
        or os.environ.get("TC_STUDIO_PYTHON")
        or shutil.which("python")
        or sys.executable
    )
    webwright_python = webwright_cfg.get("python") or python
    webwright_root = (
        webwright_cfg.get("root")
        or runtime_cfg.get("webwrightRoot")
        or os.environ.get("TC_LIVE_WEBWRIGHT_ROOT")
        or _default_webwright_root()
    )
    browsers = runtime_cfg.get("playwrightBrowsersPath") or os.environ.get("TC_STUDIO_PLAYWRIGHT_BROWSERS_PATH")
    template = generator_cfg.get("templatePath") or str(_default_template_path())
    output_root = webwright_cfg.get("outputRoot") or str(get_data_dir() / "webwright-runs")

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
        api_provider=webwright_cfg.get("apiProvider", ""),
        model_name=webwright_cfg.get("modelName") or None,
        webwright_shell=webwright_cfg.get("shell") or os.environ.get("TC_WEBWRIGHT_SHELL") or _detect_windows_bash(),
        webwright_step_limit=_optional_int(webwright_cfg.get("stepLimit")),
        webwright_run_timeout_seconds=_positive_int(webwright_cfg.get("runTimeoutSeconds"), 300),
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
    if profile.webwright_root and not settings.webwright.get("root"):
        settings.webwright["root"] = profile.webwright_root
    if profile.webwright_shell and not settings.webwright.get("shell"):
        settings.webwright["shell"] = profile.webwright_shell
    return settings
