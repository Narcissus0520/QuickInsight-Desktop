[CmdletBinding()]
param(
    [string]$DistDir = "dist",
    [string]$BuildDir = "build\package",
    [double]$SmokeSeconds = 2,
    [switch]$SkipInstaller
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

& (Join-Path $PSScriptRoot "test.ps1")
if ($LASTEXITCODE -ne 0) {
    throw "Test gates failed; build stopped."
}

& (Join-Path $PSScriptRoot "security_review.ps1") -OutputDir "build\security-review\build-gate"
if ($LASTEXITCODE -ne 0) {
    throw "Security review failed; build stopped."
}

$packageArgs = @(
    "-DistDir", $DistDir,
    "-BuildDir", $BuildDir,
    "-SmokeSeconds", $SmokeSeconds
)
if ($SkipInstaller) {
    $packageArgs += "-SkipInstaller"
}

& (Join-Path $PSScriptRoot "package.ps1") @packageArgs
exit $LASTEXITCODE
