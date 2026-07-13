[CmdletBinding()]
param(
    [ValidateSet("Smoke", "P0")]
    [string]$Profile = "Smoke",
    [int[]]$Rows = @(),
    [string]$OutputDir = "build\benchmarks\reports",
    [string]$WorkspaceDir = "build\benchmarks\workspace",
    [switch]$SkipChart,
    [switch]$CleanupCache
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    Write-Error ".venv was not found. Run .\scripts\setup_dev.ps1 first."
}

$arguments = @(
    "-m", "quick_insight.benchmarks",
    "--profile", $Profile.ToLowerInvariant(),
    "--output-dir", $OutputDir,
    "--workspace-dir", $WorkspaceDir
)
foreach ($rowCount in $Rows) {
    $arguments += @("--rows", [string]$rowCount)
}
if ($SkipChart) {
    $arguments += "--skip-chart"
}
if ($CleanupCache) {
    $arguments += "--cleanup-cache"
}

& $python @arguments
