[CmdletBinding()]
param(
    [string]$DistDir = "dist",
    [string]$BuildDir = "build\package",
    [double]$SmokeSeconds = 2,
    [switch]$SkipBuild,
    [switch]$SkipSmoke,
    [switch]$SkipInstaller
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    Write-Error ".venv was not found. Run .\scripts\setup_dev.ps1 first."
}

$argsList = @(
    "-m", "quick_insight.release_packaging",
    "--root", $repoRoot,
    "--dist-dir", $DistDir,
    "--build-dir", $BuildDir,
    "--smoke-seconds", $SmokeSeconds.ToString([Globalization.CultureInfo]::InvariantCulture)
)
if ($SkipBuild) {
    $argsList += "--skip-build"
}
if ($SkipSmoke) {
    $argsList += "--skip-smoke"
}
if ($SkipInstaller) {
    $argsList += "--skip-installer"
}

& $python @argsList
exit $LASTEXITCODE
