[CmdletBinding()]
param(
    [double[]]$Scale = @(),
    [string]$OutputDir = "build\dpi-sweep",
    [ValidateSet("light", "dark")]
    [string]$Theme = "light",
    [double]$TimeoutSeconds = 60
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
    "-m", "quick_insight.dpi_sweep",
    "--output-dir", $OutputDir,
    "--theme", $Theme,
    "--timeout-seconds",
    $TimeoutSeconds.ToString([Globalization.CultureInfo]::InvariantCulture)
)
foreach ($scaleFactor in $Scale) {
    $arguments += @(
        "--scale",
        $scaleFactor.ToString([Globalization.CultureInfo]::InvariantCulture)
    )
}

& $python @arguments
exit $LASTEXITCODE
