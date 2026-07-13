[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot
$buildDir = Join-Path $repoRoot "build"
New-Item -ItemType Directory -Force -Path $buildDir | Out-Null

& (Join-Path $PSScriptRoot "test.ps1")
if ($LASTEXITCODE -ne 0) {
    throw "Test gates failed; build stopped."
}

$report = @"
# M0 Build Report

Generated: $(Get-Date -Format o)

- M0 gates ran through scripts/test.ps1.
- Full installer/portable packaging is intentionally deferred to M6.
- No release artifact was produced by this M0 script.
"@
$report | Set-Content -LiteralPath (Join-Path $buildDir "M0-build-report.md") -Encoding utf8
Write-Host "M0 build check completed. Report: build\M0-build-report.md"
