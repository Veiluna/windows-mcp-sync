[CmdletBinding()]
param(
    [string]$Target,
    [switch]$Plan,
    [switch]$NonInteractive,
    [switch]$SkipInstall,
    [switch]$Force
)
. "$PSScriptRoot\scripts\common.ps1"
Initialize-SyncPython
$arguments = @('--root', $PSScriptRoot)
if ($Target) { $arguments += @('--target', $Target) }
if ($Plan) {
    Invoke-SyncPython (@('plan') + $arguments)
    return
}
if (-not $SkipInstall) {
    $needsNode = & $script:SyncPython (Join-Path $PSScriptRoot 'scripts\mcp_sync.py') needs-node
    if ($LASTEXITCODE -ne 0) { throw 'Cannot read shared config.' }
    if ($needsNode -eq '1' -and -not (Get-Command npx.cmd -ErrorAction SilentlyContinue)) { Install-WingetPackage 'OpenJS.NodeJS.LTS' }
    $arguments += '--install'
}
if (-not $NonInteractive) { $arguments += '--interactive' }
if ($Force) { $arguments += '--force' }
Invoke-SyncPython (@('apply') + $arguments)
