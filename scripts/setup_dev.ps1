[CmdletBinding()]
param(
    [switch]$RefreshLock,
    [string]$PythonExe
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-PythonInfo {
    param(
        [string]$Executable,
        [string[]]$Arguments
    )
    $script = @"
import json
import platform
import sys
print(json.dumps({
    'executable': sys.executable,
    'major': sys.version_info.major,
    'minor': sys.version_info.minor,
    'micro': sys.version_info.micro,
    'bits': platform.architecture()[0],
}))
"@
    try {
        $output = & $Executable @Arguments -c $script 2>$null
        if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($output)) {
            return $null
        }
        return $output | ConvertFrom-Json
    }
    catch {
        return $null
    }
}

function Resolve-Python313 {
    $candidates = @()
    if (-not [string]::IsNullOrWhiteSpace($PythonExe)) {
        $candidates += [pscustomobject]@{ Exe = $PythonExe; Args = @() }
    }
    $candidates += [pscustomobject]@{ Exe = "py"; Args = @("-3.13") }
    $candidates += [pscustomobject]@{ Exe = "python"; Args = @() }

    foreach ($candidate in $candidates) {
        $info = Get-PythonInfo -Executable $candidate.Exe -Arguments $candidate.Args
        if ($null -eq $info) {
            continue
        }
        if ($info.major -eq 3 -and $info.minor -eq 13 -and $info.bits -eq "64bit") {
            return [pscustomobject]@{
                Exe = $candidate.Exe
                Args = $candidate.Args
                Info = $info
            }
        }
        $versionText = "$($info.executable) -> $($info.major).$($info.minor).$($info.micro)"
        Write-Host "Skipping Python: $versionText $($info.bits)"
    }
    return $null
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

$python = Resolve-Python313
if ($null -eq $python) {
    $message = "CPython 3.13 x64 was not found. Install Python 3.13 x64 "
    $message += "and ensure 'py -3.13' or -PythonExe points to it."
    Write-Error $message
}

Write-Host "Using Python: $($python.Info.executable)"
& $python.Exe @($python.Args + @("-m", "venv", ".venv"))
if ($LASTEXITCODE -ne 0) {
    throw "Failed to create the virtual environment."
}

$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    throw "Failed to upgrade pip."
}

& $venvPython -m pip install -r requirements.lock
if ($LASTEXITCODE -ne 0) {
    throw "Failed to install locked dependencies."
}

& $venvPython -m pip install --no-deps -e .
if ($LASTEXITCODE -ne 0) {
    throw "Failed to install the local package."
}

if ($RefreshLock) {
    $freeze = & $venvPython -m pip freeze --exclude-editable
    $freeze | Set-Content -LiteralPath "requirements.lock" -Encoding utf8
    Write-Host "requirements.lock refreshed."
}

Write-Host "Development environment is ready."
