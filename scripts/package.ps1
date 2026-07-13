[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$message = "Release packaging belongs to M6. M0 intentionally fails here "
$message += "to avoid claiming that installer or portable artifacts exist."
Write-Error $message
