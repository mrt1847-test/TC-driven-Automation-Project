# Validates vendored third_party compliance before release or prepare-runtime.
param(
    [switch]$Strict,
    [string]$RuntimeRoot = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$Failures = New-Object System.Collections.Generic.List[string]
if (-not $RuntimeRoot) {
    $RuntimeRoot = Join-Path $RepoRoot "runtime-staging"
}

function Add-Failure {
    param([string]$Message)
    $Failures.Add($Message) | Out-Null
    Write-Host "FAIL: $Message"
}

function Assert-File {
    param([string]$Path, [string]$Label)
    if (-not (Test-Path $Path)) {
        Add-Failure "$Label missing: $Path"
        return $false
    }
    Write-Host "OK: $Label"
    return $true
}

function Assert-TextContains {
    param(
        [string]$Text,
        [string]$Phrase,
        [string]$Label
    )
    if ($Text -notmatch [regex]::Escape($Phrase)) {
        Add-Failure "$Label missing expected text: $Phrase"
    }
}

function Get-VendoredCommit {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        return ""
    }
    $line = Get-Content $Path | Where-Object { $_ -match "^commit=" } | Select-Object -First 1
    return ($line -replace "^commit=", "").Trim()
}

function Assert-NoticeFreshness {
    param(
        [string]$NoticePath,
        [string[]]$SourcePaths,
        [string]$Label
    )
    if (-not (Test-Path $NoticePath)) {
        return
    }
    $noticeItem = Get-Item $NoticePath
    foreach ($sourcePath in $SourcePaths) {
        if (-not (Test-Path $sourcePath)) {
            continue
        }
        $sourceItem = Get-Item $sourcePath
        if ($sourceItem.LastWriteTimeUtc -gt $noticeItem.LastWriteTimeUtc) {
            Add-Failure "$Label is older than source file: $sourcePath. Re-run npm run prepare-runtime."
        }
    }
}

function Assert-RuntimeNotices {
    param(
        [string]$Root,
        [string]$Label,
        [bool]$Required,
        [string[]]$FreshnessSources,
        [string]$VendoredCommit
    )

    if (-not (Test-Path $Root)) {
        if ($Required) {
            Add-Failure "$Label runtime root missing: $Root. Run npm run prepare-runtime first."
        } else {
            Write-Host "SKIP: $Label runtime root not found"
        }
        return
    }

    $noticePath = Join-Path $Root "THIRD_PARTY_NOTICES.txt"
    if (-not (Assert-File $noticePath "$Label THIRD_PARTY_NOTICES.txt")) {
        return
    }

    $noticeText = Get-Content $noticePath -Raw
    foreach ($phrase in @(
        "TC Automation Studio Third-Party Notices",
        "Third-party Notice",
        "Microsoft Webwright",
        "Microsoft Webwright MIT License",
        "MIT License",
        "Microsoft Corporation",
        "Bundled Python",
        "Bundled Python Package License Metadata",
        "Playwright Browser Assets"
    )) {
        Assert-TextContains $noticeText $phrase "$Label THIRD_PARTY_NOTICES.txt"
    }
    if ($VendoredCommit) {
        Assert-TextContains $noticeText $VendoredCommit "$Label THIRD_PARTY_NOTICES.txt"
    }

    $manifestPath = Join-Path $Root "runtime-manifest.json"
    if (Assert-File $manifestPath "$Label runtime manifest") {
        try {
            $manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json
            if ($Strict -and $manifest.webwrightMode -ne "live") {
                Add-Failure "$Label runtime-manifest.json must be live for release validation; found '$($manifest.webwrightMode)'"
            }
            if ($VendoredCommit -and $manifest.webwrightSource -match "third_party[\\/]webwright" -and $manifest.webwrightSourceVersion -ne $VendoredCommit) {
                Add-Failure "$Label runtime-manifest.json webwrightSourceVersion '$($manifest.webwrightSourceVersion)' does not match vendored commit '$VendoredCommit'"
            }
        } catch {
            Add-Failure "$Label runtime-manifest.json could not be parsed: $($_.Exception.Message)"
        }
    }

    Assert-NoticeFreshness -NoticePath $noticePath -SourcePaths $FreshnessSources -Label "$Label THIRD_PARTY_NOTICES.txt"
}

$Notice = Join-Path $RepoRoot "third_party\NOTICE.md"
$WebwrightRoot = Join-Path $RepoRoot "third_party\webwright"
$License = Join-Path $WebwrightRoot "LICENSE"
$VersionFile = Join-Path $WebwrightRoot "VENDORED_VERSION.txt"
$VendoredCommit = Get-VendoredCommit $VersionFile

Assert-File $Notice "third_party notice" | Out-Null
Assert-File $License "Webwright LICENSE" | Out-Null
Assert-File $VersionFile "Webwright VENDORED_VERSION" | Out-Null

if (Test-Path $License) {
    $licenseText = Get-Content $License -Raw
    if ($licenseText -notmatch "MIT License" -or $licenseText -notmatch "Microsoft Corporation") {
        Add-Failure "Webwright LICENSE does not look like the expected Microsoft MIT license"
    } else {
        Write-Host "OK: Webwright LICENSE content"
    }
}

if (Test-Path $VersionFile) {
    $versionText = Get-Content $VersionFile -Raw
    foreach ($key in @("upstream=", "commit=", "license=MIT")) {
        if ($versionText -notmatch [regex]::Escape($key)) {
            Add-Failure "VENDORED_VERSION.txt missing required field: $key"
        }
    }
    if ($Failures.Count -eq 0 -or ($Failures | Where-Object { $_ -like "*VENDORED*" }).Count -eq 0) {
        Write-Host "OK: VENDORED_VERSION.txt fields"
    }
}

if (Test-Path $Notice) {
    $noticeText = Get-Content $Notice -Raw
    foreach ($phrase in @(
        "not an official Microsoft product",
        "third_party/webwright",
        "734bc60ea73653498215694d0cc4bc96fbc09e9c"
    )) {
        if ($noticeText -notmatch [regex]::Escape($phrase)) {
            Add-Failure "third_party/NOTICE.md missing expected text: $phrase"
        }
    }
}

$PrepareScript = Join-Path $RepoRoot "scripts\prepare-runtime.ps1"
if (Test-Path $PrepareScript) {
    $prepareText = Get-Content $PrepareScript -Raw
    if ($prepareText -notmatch "Write-ThirdPartyNotices") {
        Add-Failure "prepare-runtime.ps1 must generate THIRD_PARTY_NOTICES.txt"
    } else {
        Write-Host "OK: prepare-runtime notice generator"
    }
}

$BuilderConfig = Join-Path $RepoRoot "apps\desktop\electron-builder.json"
if (Assert-File $BuilderConfig "electron-builder config") {
    $builderText = Get-Content $BuilderConfig -Raw
    Assert-TextContains $builderText "../../runtime-staging" "electron-builder runtime resources"
    Assert-TextContains $builderText '"to": "runtime"' "electron-builder runtime resources"
}

$FreshnessSources = @($Notice, $License, $VersionFile, $PrepareScript)

if ($Strict) {
    Write-Host "Running prepare-runtime policy validation (live)..."
    & $PrepareScript -ValidateOnly -WebwrightMode live

    Assert-RuntimeNotices `
        -Root $RuntimeRoot `
        -Label "staged" `
        -Required $true `
        -FreshnessSources $FreshnessSources `
        -VendoredCommit $VendoredCommit

    $PackagedRuntimeRoot = Join-Path $RepoRoot "apps\desktop\release\win-unpacked\resources\runtime"
    if (Test-Path (Split-Path -Parent $PackagedRuntimeRoot)) {
        Assert-RuntimeNotices `
            -Root $PackagedRuntimeRoot `
            -Label "packaged win-unpacked" `
            -Required $true `
            -FreshnessSources $FreshnessSources `
            -VendoredCommit $VendoredCommit
    } else {
        Write-Host "SKIP: packaged win-unpacked runtime not present; staged notices were validated"
    }
} elseif (Test-Path $RuntimeRoot) {
    Assert-RuntimeNotices `
        -Root $RuntimeRoot `
        -Label "staged" `
        -Required $false `
        -FreshnessSources $FreshnessSources `
        -VendoredCommit $VendoredCommit
}

if ($Failures.Count -gt 0) {
    Write-Host ""
    Write-Host "Third-party validation failed with $($Failures.Count) issue(s)."
    exit 1
}

Write-Host ""
Write-Host "Third-party validation passed."
exit 0
