[CmdletBinding()]
param(
    [switch]$NoUi
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    Write-Error ".venv was not found. Run .\scripts\setup_dev.ps1 first."
}

if ([string]::IsNullOrWhiteSpace($env:QT_QPA_PLATFORM)) {
    $env:QT_QPA_PLATFORM = "offscreen"
}
$testTempRoot = Join-Path $repoRoot "build\test-temp"
New-Item -ItemType Directory -Force -Path $testTempRoot | Out-Null
$pytestTemp = Join-Path $testTempRoot ("pytest-" + [Guid]::NewGuid().ToString("N"))
$pytestCacheRoot = Join-Path $repoRoot "build\pytest-cache"
New-Item -ItemType Directory -Force -Path $pytestCacheRoot | Out-Null
$pytestCache = Join-Path $pytestCacheRoot ("cache-" + [Guid]::NewGuid().ToString("N"))

$results = New-Object System.Collections.Generic.List[string]

function Invoke-Gate {
    param(
        [string]$Name,
        [string[]]$Arguments
    )
    Write-Host "== $Name =="
    & $python @Arguments
    if ($LASTEXITCODE -ne 0) {
        $results.Add("${Name}: FAIL")
        throw "$Name failed with exit code $LASTEXITCODE"
    }
    $results.Add("${Name}: PASS")
}

try {
    Invoke-Gate -Name "ruff" -Arguments @("-m", "ruff", "check", ".")
    Invoke-Gate -Name "mypy" -Arguments @("-m", "mypy", "src")
    $pytestArgs = @(
        "-m", "pytest",
        "--basetemp", $pytestTemp,
        "-o", "cache_dir=$pytestCache"
    )
    if ($NoUi) {
        $pytestArgs += @("tests/unit")
    }
    Invoke-Gate -Name "pytest" -Arguments $pytestArgs
}
finally {
    Write-Host "== Summary =="
    foreach ($result in $results) {
        Write-Host $result
    }
}
