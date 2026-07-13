[CmdletBinding()]
param(
    [double]$SmokeSeconds = 0,
    [ValidateSet("light", "dark")]
    [string]$Theme
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    Write-Error ".venv was not found. Run .\scripts\setup_dev.ps1 first."
}

$argsList = @("-m", "quick_insight")
if ($SmokeSeconds -gt 0) {
    $secondsText = $SmokeSeconds.ToString([Globalization.CultureInfo]::InvariantCulture)
    $argsList += @("--smoke-seconds", $secondsText)
}
if (-not [string]::IsNullOrWhiteSpace($Theme)) {
    $argsList += @("--theme", $Theme)
}

& $python @argsList
exit $LASTEXITCODE
