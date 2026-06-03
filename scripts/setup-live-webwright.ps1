# Installs the vendored or external Microsoft Webwright source for live validation.

param(
    [string]$InstallRoot = "",
    [string]$Python = "python",
    [string]$WebwrightRepo = "https://github.com/microsoft/Webwright.git",
    [string]$WebwrightRef = "",
    [string]$SettingsPath = "",
    [string]$OutputRoot = "",
    [string]$PlaywrightBrowsersPath = "",
    [string]$WebwrightShell = "",
    [switch]$SkipWindowsPatch,
    [switch]$UpdateSettings
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot

function Set-JsonProperty {
    param(
        [object]$Object,
        [string]$Name,
        [object]$Value
    )
    if ($Object.PSObject.Properties[$Name]) {
        $Object.$Name = $Value
    } else {
        $Object | Add-Member -MemberType NoteProperty -Name $Name -Value $Value
    }
}

function Find-WebwrightShell {
    if ($WebwrightShell) {
        return $WebwrightShell
    }
    $cmd = Get-Command bash.exe -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }
    $candidates = @(
        "C:\Program Files\Git\bin\bash.exe",
        "C:\Program Files\Git\usr\bin\bash.exe",
        "C:\Program Files (x86)\Git\bin\bash.exe",
        "C:\Program Files (x86)\Git\usr\bin\bash.exe"
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            return $candidate
        }
    }
    return ""
}

function Apply-WebwrightWindowsPatch {
    param([string]$Root)

    if (-not $IsWindows -and $env:OS -ne "Windows_NT") {
        return
    }
    if ($SkipWindowsPatch) {
        Write-Host "Skipping local Webwright Windows patch."
        return
    }

    $basePy = Join-Path $Root "src\webwright\models\base.py"
    $workspacePy = Join-Path $Root "src\webwright\environments\local_workspace.py"
    if (-not (Test-Path $basePy) -or -not (Test-Path $workspacePy)) {
        throw "Cannot apply Windows patch; Webwright source files are missing."
    }

    $baseText = Get-Content $basePy -Raw
    if ($baseText -notmatch "import sys") {
        $baseText = $baseText -replace "import subprocess`r?`n", "import subprocess`r`nimport sys`r`n"
    }
    if ($baseText -notmatch 'sys\.platform == "win32"') {
        $baseText = $baseText -replace "def _validate_bash_command\(command: str\) -> None:`r?`n", "def _validate_bash_command(command: str) -> None:`r`n    if sys.platform == `"win32`":`r`n        return`r`n"
    }
    Set-Content $basePy $baseText -Encoding UTF8

    $workspaceText = Get-Content $workspacePy -Raw
    if ($workspaceText -notmatch "import shutil") {
        $workspaceText = $workspaceText -replace "import re`r?`n", "import re`r`nimport shutil`r`n"
    }
    if ($workspaceText -notmatch "import sys") {
        $workspaceText = $workspaceText -replace "import subprocess`r?`n", "import subprocess`r`nimport sys`r`n"
    }
    if ($workspaceText -notmatch "def _resolve_windows_shell") {
        $browserEnv = @'
    def _resolve_windows_shell(self) -> str | None:
        shell = str(self.config.shell or "")
        shell_name = Path(shell).name.lower()
        if shell_name not in {"bash", "bash.exe", "sh", "sh.exe"}:
            return None

        candidate = Path(shell)
        if candidate.exists():
            return str(candidate)

        discovered = shutil.which("bash.exe") or shutil.which("sh.exe")
        if discovered:
            return discovered

        for common in (
            Path(r"C:\Program Files\Git\bin\bash.exe"),
            Path(r"C:\Program Files\Git\usr\bin\bash.exe"),
            Path(r"C:\Program Files (x86)\Git\bin\bash.exe"),
            Path(r"C:\Program Files (x86)\Git\usr\bin\bash.exe"),
        ):
            if common.exists():
                return str(common)
        return None

'@
        $workspaceText = $workspaceText -replace "    def execute\(self, action: dict\[str, Any\], cwd: str = `"`"\) -> dict\[str, Any\]:", "$browserEnv    def execute(self, action: dict[str, Any], cwd: str = `"`") -> dict[str, Any]:"
    }
    if ($workspaceText -notmatch "windows_shell = self\._resolve_windows_shell") {
        $old = @'
            result = subprocess.run(
                command,
                shell=True,
                executable=self.config.shell,
                text=True,
                cwd=resolved_cwd,
                env=command_env,
                timeout=self.config.command_timeout_seconds,
                encoding="utf-8",
                errors="replace",
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
'@
        $new = @'
            windows_shell = self._resolve_windows_shell() if sys.platform == "win32" else None
            if windows_shell:
                result = subprocess.run(
                    [windows_shell, "-lc", command],
                    shell=False,
                    text=True,
                    cwd=resolved_cwd,
                    env=command_env,
                    timeout=self.config.command_timeout_seconds,
                    encoding="utf-8",
                    errors="replace",
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                )
            else:
                result = subprocess.run(
                    command,
                    shell=True,
                    executable=self.config.shell,
                    text=True,
                    cwd=resolved_cwd,
                    env=command_env,
                    timeout=self.config.command_timeout_seconds,
                    encoding="utf-8",
                    errors="replace",
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                )
'@
        $workspaceText = $workspaceText.Replace($old, $new)
    }
    Set-Content $workspacePy $workspaceText -Encoding UTF8
    Write-Host "Applied local Webwright Windows shell patch."
}

if (-not $InstallRoot) {
    $VendoredRoot = Join-Path $RepoRoot "third_party\webwright"
    if (Test-Path $VendoredRoot) {
        $InstallRoot = $VendoredRoot
    } else {
        $InstallRoot = Join-Path $RepoRoot ".runtime\webwright"
    }
}
if (-not $SettingsPath) {
    $SettingsPath = Join-Path $RepoRoot ".data\settings.json"
}
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $RepoRoot ".data\webwright-runs"
}
$ResolvedWebwrightShell = Find-WebwrightShell

if (-not (Test-Path $InstallRoot)) {
    Write-Host "Cloning Webwright to $InstallRoot"
    git clone $WebwrightRepo $InstallRoot
}

if ($WebwrightRef) {
    if (-not (Test-Path (Join-Path $InstallRoot ".git"))) {
        throw "Cannot checkout WebwrightRef on a non-git Webwright source: $InstallRoot"
    }
    Write-Host "Checking out pinned Webwright ref $WebwrightRef"
    git -C $InstallRoot fetch --all --tags
    git -C $InstallRoot checkout $WebwrightRef
}

$VersionFile = Join-Path $InstallRoot "VENDORED_VERSION.txt"
if (Test-Path (Join-Path $InstallRoot ".git")) {
    $ResolvedRef = (git -C $InstallRoot rev-parse HEAD).Trim()
} elseif (Test-Path $VersionFile) {
    $ResolvedRef = ((Get-Content $VersionFile | Where-Object { $_ -match "^commit=" } | Select-Object -First 1) -replace "^commit=", "").Trim()
} else {
    $ResolvedRef = "external-non-git"
}
Write-Host "Using Webwright ref $ResolvedRef"

Apply-WebwrightWindowsPatch $InstallRoot

Write-Host "Installing Webwright into Python: $Python"
& $Python -m pip install -e $InstallRoot
if ($LASTEXITCODE -ne 0) {
    throw "pip install -e failed"
}

if ($PlaywrightBrowsersPath) {
    $env:PLAYWRIGHT_BROWSERS_PATH = $PlaywrightBrowsersPath
}

Write-Host "Installing Playwright Chromium"
& $Python -m playwright install chromium
if ($LASTEXITCODE -ne 0) {
    throw "playwright install chromium failed"
}

Push-Location $InstallRoot
try {
    & $Python -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('webwright.run.cli') else 1)"
    if ($LASTEXITCODE -ne 0) {
        throw "webwright.run.cli import probe failed"
    }
} finally {
    Pop-Location
}

$BaseConfig = Join-Path $InstallRoot "src\webwright\config\base.yaml"
$ModelConfig = Join-Path $InstallRoot "src\webwright\config\model_openai.yaml"
if (-not (Test-Path $BaseConfig)) {
    throw "Missing Webwright base config: $BaseConfig"
}
if (-not (Test-Path $ModelConfig)) {
    throw "Missing Webwright model config: $ModelConfig"
}

if ($UpdateSettings) {
    if (-not (Test-Path $SettingsPath)) {
        throw "settings.json does not exist: $SettingsPath"
    }

    $settings = Get-Content $SettingsPath -Raw | ConvertFrom-Json
    if (-not $settings.runtime) {
        $settings | Add-Member -MemberType NoteProperty -Name runtime -Value ([pscustomobject]@{})
    }

    Set-JsonProperty $settings.runtime "mode" "custom"
    Set-JsonProperty $settings.runtime "python" $Python
    Set-JsonProperty $settings.runtime "webwrightPython" $Python
    if ($PlaywrightBrowsersPath) {
        Set-JsonProperty $settings.runtime "playwrightBrowsersPath" $PlaywrightBrowsersPath
    }

    Set-JsonProperty $settings.webwright "executionMode" "native"
    Set-JsonProperty $settings.webwright "root" $InstallRoot
    Set-JsonProperty $settings.webwright "python" $Python
    Set-JsonProperty $settings.webwright "baseConfig" "base.yaml"
    Set-JsonProperty $settings.webwright "modelConfig" "model_openai.yaml"
    Set-JsonProperty $settings.webwright "apiProvider" "openai"
    Set-JsonProperty $settings.webwright "stepLimit" 30
    Set-JsonProperty $settings.webwright "runTimeoutSeconds" 180
    if ($ResolvedWebwrightShell) {
        Set-JsonProperty $settings.webwright "shell" $ResolvedWebwrightShell
    }
    Set-JsonProperty $settings.webwright "outputRoot" $OutputRoot

    $settings | ConvertTo-Json -Depth 20 | Set-Content $SettingsPath -Encoding UTF8
    Write-Host "Updated settings: $SettingsPath"
}

Write-Host "Webwright live runtime is installed."
Write-Host "Root: $InstallRoot"
Write-Host "Python: $Python"
if ($ResolvedWebwrightShell) {
    Write-Host "Shell: $ResolvedWebwrightShell"
}
Write-Host "Pinned ref: $ResolvedRef"
Write-Host "Next: python -m pytest tests/e2e/test_live_webwright_runtime.py -q (from apps/worker)"
