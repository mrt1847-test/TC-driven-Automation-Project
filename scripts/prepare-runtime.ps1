# Stages embedded Python runtime assets for electron-builder (Windows x64).
# Live product builds use vendored Webwright by default, or an explicit pinned source/package.
# Dev/mock builds must opt in with -WebwrightMode mock.

param(
    [string]$StagingRoot = "",
    [string]$PythonVersion = "3.11.9",
    [ValidateSet("live", "mock")]
    [string]$WebwrightMode = "",
    [string]$WebwrightSource = "",
    [string]$WebwrightSourceVersion = "",
    [string]$WebwrightPipPackage = "",
    [string]$WebwrightConfigSource = "",
    [string]$BaseConfig = "base.yaml",
    [string]$ModelConfig = "model_openai.yaml",
    [switch]$ValidateOnly
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
if (-not $StagingRoot) {
    $StagingRoot = Join-Path $RepoRoot "runtime-staging"
}
if (-not $WebwrightMode) {
    $WebwrightMode = if ($env:WEBWRIGHT_MODE) { $env:WEBWRIGHT_MODE } else { "live" }
}
if ($WebwrightMode -notin @("live", "mock")) {
    throw "WEBWRIGHT_MODE must be 'live' or 'mock'."
}
if (-not $WebwrightSource) {
    $WebwrightSource = $env:WEBWRIGHT_SOURCE
}
if (-not $WebwrightSourceVersion) {
    $WebwrightSourceVersion = $env:WEBWRIGHT_SOURCE_VERSION
}
if (-not $WebwrightPipPackage) {
    $WebwrightPipPackage = $env:WEBWRIGHT_PIP_PACKAGE
}
if (-not $WebwrightConfigSource) {
    $WebwrightConfigSource = $env:WEBWRIGHT_CONFIG_SOURCE
}

$VendoredWebwrightSource = Join-Path $RepoRoot "third_party\webwright"
if ($WebwrightMode -eq "live" -and -not $WebwrightSource -and -not $WebwrightPipPackage -and (Test-Path $VendoredWebwrightSource)) {
    $WebwrightSource = $VendoredWebwrightSource
    $VersionFile = Join-Path $VendoredWebwrightSource "VENDORED_VERSION.txt"
    if (-not $WebwrightSourceVersion -and (Test-Path $VersionFile)) {
        $WebwrightSourceVersion = ((Get-Content $VersionFile | Where-Object { $_ -match "^commit=" } | Select-Object -First 1) -replace "^commit=", "").Trim()
    }
    if (-not $WebwrightSourceVersion) {
        $WebwrightSourceVersion = "vendored"
    }
}

function Test-PinnedPipSpec {
    param([string]$Spec)
    if (-not $Spec) {
        return $false
    }
    if ($Spec -match "==[^=]+$") {
        return $true
    }
    if ($Spec -match "@\s*git\+.+@[A-Za-z0-9._-]{7,}") {
        return $true
    }
    if ($Spec -match "@\s*https?://.+\.(whl|tar\.gz|zip)$") {
        return $true
    }
    return $false
}

function Assert-WebwrightPackagingPolicy {
    if ($WebwrightMode -eq "mock") {
        Write-Host "Webwright mock staging selected explicitly."
        return
    }

    if (-not $WebwrightSource -and -not $WebwrightPipPackage) {
        throw "Live runtime staging requires vendored third_party/webwright, WEBWRIGHT_SOURCE plus WEBWRIGHT_SOURCE_VERSION, or a pinned WEBWRIGHT_PIP_PACKAGE. Use -WebwrightMode mock only for dev/mock staging."
    }

    if ($WebwrightSource) {
        if (-not (Test-Path $WebwrightSource)) {
            throw "WEBWRIGHT_SOURCE does not exist: $WebwrightSource"
        }
        if (-not $WebwrightSourceVersion) {
            throw "WEBWRIGHT_SOURCE_VERSION is required for live source staging. Use a commit SHA, tag, or pinned release identifier."
        }
    }

    if ($WebwrightPipPackage -and -not (Test-PinnedPipSpec $WebwrightPipPackage)) {
        throw "WEBWRIGHT_PIP_PACKAGE must be pinned, for example 'webwright==1.2.3' or 'webwright @ git+https://...@<commit>'."
    }

    if ($WebwrightPipPackage -and -not $WebwrightSource -and -not $WebwrightConfigSource) {
        throw "Pinned WEBWRIGHT_PIP_PACKAGE staging also requires WEBWRIGHT_CONFIG_SOURCE so $BaseConfig and $ModelConfig are available under the Webwright root."
    }

    if ($WebwrightConfigSource -and -not (Test-Path $WebwrightConfigSource)) {
        throw "WEBWRIGHT_CONFIG_SOURCE does not exist: $WebwrightConfigSource"
    }
}

function Assert-WebwrightSourceLicense {
    param(
        [string]$SourceRoot,
        [switch]$RequireVersionMarker
    )
    $licensePath = Join-Path $SourceRoot "LICENSE"
    if (-not (Test-Path $licensePath)) {
        throw "Webwright source is missing LICENSE: $licensePath"
    }
    $licenseText = Get-Content $licensePath -Raw
    if ($licenseText -notmatch "MIT License" -or $licenseText -notmatch "Microsoft Corporation") {
        throw "Webwright LICENSE does not match expected Microsoft MIT license text: $licensePath"
    }
    if ($RequireVersionMarker) {
        $versionPath = Join-Path $SourceRoot "VENDORED_VERSION.txt"
        if (-not (Test-Path $versionPath)) {
            throw "Vendored Webwright source is missing VENDORED_VERSION.txt: $versionPath"
        }
    }
}

function Assert-WebwrightConfigFiles {
    param([string]$Root)
    $missing = @()
    foreach ($config in @($BaseConfig, $ModelConfig)) {
        $rootConfig = Join-Path $Root $config
        $sourceConfig = Join-Path (Join-Path $Root "src\webwright\config") $config
        if (-not (Test-Path $rootConfig) -and -not (Test-Path $sourceConfig)) {
            $missing += $config
        }
    }
    if ($missing.Count -gt 0) {
        throw "Live Webwright staging is missing config file(s): $($missing -join ', ')"
    }
}

function Write-ThirdPartyNotices {
    param(
        [string]$OutputPath,
        [string]$PythonExe,
        [string]$PythonDir,
        [string]$RepoRoot
    )

    $noticeParts = New-Object System.Collections.Generic.List[string]
    $noticeParts.Add("TC Automation Studio Third-Party Notices")
    $noticeParts.Add("=========================================")
    $noticeParts.Add("")

    $thirdPartyNotice = Join-Path $RepoRoot "third_party\NOTICE.md"
    if (Test-Path $thirdPartyNotice) {
        $noticeParts.Add((Get-Content $thirdPartyNotice -Raw))
        $noticeParts.Add("")
    }

    $webwrightLicense = Join-Path $RepoRoot "third_party\webwright\LICENSE"
    if (Test-Path $webwrightLicense) {
        $noticeParts.Add("Microsoft Webwright MIT License (full text)")
        $noticeParts.Add("---------------------------------------------")
        $noticeParts.Add((Get-Content $webwrightLicense -Raw))
        $noticeParts.Add("")
    }

    $pythonLicense = Join-Path $PythonDir "LICENSE.txt"
    if (Test-Path $pythonLicense) {
        $noticeParts.Add("Bundled Python License")
        $noticeParts.Add("----------------------")
        $noticeParts.Add((Get-Content $pythonLicense -Raw))
        $noticeParts.Add("")
    } else {
        $noticeParts.Add("Bundled Python")
        $noticeParts.Add("--------------")
        $noticeParts.Add("Python is staged from the official Windows embeddable distribution. Include the PSF License notice if the embeddable archive layout changes and LICENSE.txt is not present.")
        $noticeParts.Add("")
    }

    $packageScript = @'
import importlib.metadata as md

rows = []
for dist in md.distributions():
    meta = dist.metadata
    name = meta.get("Name") or "unknown"
    version = meta.get("Version") or ""
    license_value = (meta.get("License") or "").strip()
    classifiers = [
        value.replace("License :: ", "")
        for value in meta.get_all("Classifier") or []
        if value.startswith("License :: ")
    ]
    license_text = license_value or "; ".join(classifiers) or "license metadata unavailable"
    rows.append((name.lower(), f"- {name} {version}: {license_text}"))

for _, row in sorted(rows):
    print(row)
'@
    $packageSummary = & $PythonExe -c $packageScript
    $noticeParts.Add("Bundled Python Package License Metadata")
    $noticeParts.Add("---------------------------------------")
    $noticeParts.Add("Generated from installed package metadata during runtime staging. Package license files, when shipped by the package, remain in the staged Python environment.")
    $noticeParts.Add("")
    foreach ($line in $packageSummary) {
        $noticeParts.Add($line)
    }
    $noticeParts.Add("")

    $noticeParts.Add("Playwright Browser Assets")
    $noticeParts.Add("-------------------------")
    $noticeParts.Add("Playwright browser binaries are installed into runtime-staging/ms-playwright during packaging. Browser-specific license files and notices should be preserved from the downloaded Playwright browser distribution when present.")

    $noticeParts -join "`r`n" | Set-Content $OutputPath -Encoding UTF8
}

Assert-WebwrightPackagingPolicy

if ($WebwrightMode -eq "live" -and $WebwrightSource -and (Test-Path $WebwrightSource)) {
    $isVendored = ($WebwrightSource -eq $VendoredWebwrightSource)
    Assert-WebwrightSourceLicense -SourceRoot $WebwrightSource -RequireVersionMarker:$isVendored
}

if ($ValidateOnly) {
    $repoNotice = Join-Path $RepoRoot "third_party\NOTICE.md"
    if (-not (Test-Path $repoNotice)) {
        throw "Missing third_party/NOTICE.md"
    }
    Write-Host "Runtime staging policy validation passed for WebwrightMode=$WebwrightMode"
    return
}

Write-Host "Staging runtime to $StagingRoot"
if (Test-Path $StagingRoot) {
    Remove-Item -Recurse -Force $StagingRoot
}
New-Item -ItemType Directory -Path $StagingRoot | Out-Null

$TemplateSrc = Join-Path $RepoRoot "packages\generated-template"
$TemplateDst = Join-Path $StagingRoot "generated-template"
Copy-Item -Recurse $TemplateSrc $TemplateDst

$WebwrightDst = Join-Path $StagingRoot "webwright"
New-Item -ItemType Directory -Path $WebwrightDst | Out-Null

if ($WebwrightMode -eq "mock") {
    @"
# Mock/dev Webwright root.
# This placeholder is never valid for live product runtime readiness.
"@ | Set-Content (Join-Path $WebwrightDst "base.yaml")
    @"
# Mock/dev Webwright model config placeholder.
"@ | Set-Content (Join-Path $WebwrightDst "model_openai.yaml")
} else {
    if ($WebwrightSource) {
        Write-Host "Copying Webwright source from $WebwrightSource ($WebwrightSourceVersion)"
        Copy-Item -Recurse (Join-Path $WebwrightSource "*") $WebwrightDst -Force
    }
    if ($WebwrightConfigSource) {
        Write-Host "Copying Webwright config from $WebwrightConfigSource"
        Copy-Item -Recurse (Join-Path $WebwrightConfigSource "*") $WebwrightDst -Force
    }
    Assert-WebwrightConfigFiles $WebwrightDst
    if ($WebwrightSource) {
        Assert-WebwrightSourceLicense -SourceRoot $WebwrightDst
    }
}

$PythonDir = Join-Path $StagingRoot "python"
$EmbedZip = Join-Path $env:TEMP "python-embed-$PythonVersion.zip"
$EmbedUrl = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"

if (-not (Test-Path (Join-Path $PythonDir "python.exe"))) {
    Write-Host "Downloading embeddable Python $PythonVersion"
    Invoke-WebRequest -Uri $EmbedUrl -OutFile $EmbedZip
    Expand-Archive -Path $EmbedZip -DestinationPath $PythonDir -Force
    Remove-Item $EmbedZip -Force
    $pth = Get-ChildItem $PythonDir -Filter "python*._pth" | Select-Object -First 1
    if ($pth) {
        (Get-Content $pth.FullName) -replace '#import site', 'import site' | Set-Content $pth.FullName
    }
}

$PythonExe = Join-Path $PythonDir "python.exe"
& $PythonExe -m pip install --upgrade pip
$WorkerReq = Join-Path $RepoRoot "apps\worker\requirements.txt"
& $PythonExe -m pip install -r $WorkerReq
& $PythonExe -m pip install playwright pytest-playwright
$TemplateReq = Join-Path $TemplateSrc "requirements.txt"
if (Test-Path $TemplateReq) {
    & $PythonExe -m pip install -r $TemplateReq
}

if ($WebwrightMode -eq "live") {
    if ($WebwrightSource -and ((Test-Path (Join-Path $WebwrightDst "pyproject.toml")) -or (Test-Path (Join-Path $WebwrightDst "setup.py")))) {
        Write-Host "Installing copied Webwright source into bundled Python"
        & $PythonExe -m pip install $WebwrightDst
    }

    if ($WebwrightPipPackage) {
        Write-Host "Installing pinned Webwright package $WebwrightPipPackage"
        & $PythonExe -m pip install $WebwrightPipPackage
    }
}

$BrowsersDir = Join-Path $StagingRoot "ms-playwright"
$env:PLAYWRIGHT_BROWSERS_PATH = $BrowsersDir
& $PythonExe -m playwright install chromium

Write-ThirdPartyNotices `
    -OutputPath (Join-Path $StagingRoot "THIRD_PARTY_NOTICES.txt") `
    -PythonExe $PythonExe `
    -PythonDir $PythonDir `
    -RepoRoot $RepoRoot

if ($WebwrightMode -eq "live") {
    Push-Location $WebwrightDst
    try {
        & $PythonExe -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('webwright.run.cli') else 1)"
        if ($LASTEXITCODE -ne 0) {
            throw "webwright.run.cli import probe failed after staging"
        }
    } finally {
        Pop-Location
    }
}

$Manifest = @{
    webwrightMode = $WebwrightMode
    webwrightSource = $WebwrightSource
    webwrightSourceVersion = $WebwrightSourceVersion
    webwrightPipPackage = $WebwrightPipPackage
    webwrightConfigSource = $WebwrightConfigSource
    baseConfig = $BaseConfig
    modelConfig = $ModelConfig
    pythonVersion = $PythonVersion
}
$Manifest | ConvertTo-Json -Depth 3 | Set-Content (Join-Path $StagingRoot "runtime-manifest.json")

Write-Host "Runtime staging complete: $StagingRoot"
