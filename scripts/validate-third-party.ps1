# Validates vendored third_party compliance before release or prepare-runtime.
param(
    [switch]$Strict
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$Failures = New-Object System.Collections.Generic.List[string]

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

$Notice = Join-Path $RepoRoot "third_party\NOTICE.md"
$Readme = Join-Path $RepoRoot "third_party\README.md"
$LegalDoc = Join-Path $RepoRoot "docs\THIRD_PARTY_LEGAL.md"
$WebwrightRoot = Join-Path $RepoRoot "third_party\webwright"
$License = Join-Path $WebwrightRoot "LICENSE"
$VersionFile = Join-Path $WebwrightRoot "VENDORED_VERSION.txt"

Assert-File $Notice "third_party notice" | Out-Null
Assert-File $Readme "third_party readme" | Out-Null
Assert-File $LegalDoc "legal doc" | Out-Null
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

if ($Strict) {
    Write-Host "Running prepare-runtime policy validation (live)..."
    & $PrepareScript -ValidateOnly -WebwrightMode live
}

if ($Failures.Count -gt 0) {
    Write-Host ""
    Write-Host "Third-party validation failed with $($Failures.Count) issue(s)."
    exit 1
}

Write-Host ""
Write-Host "Third-party validation passed."
exit 0
