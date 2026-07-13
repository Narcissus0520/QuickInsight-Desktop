[CmdletBinding()]
param(
    [string]$OutputDir = "build\security-review"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    Write-Error ".venv was not found. Run .\scripts\setup_dev.ps1 first."
}

& $python -m quick_insight.security_review --root $repoRoot --output-dir $OutputDir
exit $LASTEXITCODE
