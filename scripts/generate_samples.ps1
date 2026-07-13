[CmdletBinding()]
param(
    [string]$OutputDir = "samples"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    Write-Error ".venv was not found. Run .\scripts\setup_dev.ps1 first."
}

$env:QI_SAMPLE_OUTPUT = $OutputDir
$script = @'
import os
from pathlib import Path

from quick_insight.resources.samples import generate_samples

for path in generate_samples(Path(os.environ["QI_SAMPLE_OUTPUT"])):
    print(path)
'@
& $python -c $script
