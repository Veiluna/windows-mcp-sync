[CmdletBinding()]
param(
    [ValidateSet('push', 'pull', 'export', 'check')][string]$Action = 'pull',
    [string]$Message = 'Sync MCP configuration',
    [string]$Target,
    [switch]$NonInteractive
)
. "$PSScriptRoot\scripts\common.ps1"
Initialize-SyncPython
$arguments = @('--root', $PSScriptRoot)
if ($Target) { $arguments += @('--target', $Target) }
if ($Action -eq 'check') { Invoke-SyncPython (@('check') + $arguments); return }
if ($Action -eq 'export') { Invoke-SyncPython (@('export') + $arguments); return }
if (-not (Test-Path (Join-Path $PSScriptRoot '.git'))) { throw 'This folder is not an initialized Git repository.' }
Set-GitHubProcessCredential
$gitArguments = @('-C', $PSScriptRoot)
if ($env:GH_TOKEN -and (Get-Command gh.exe -ErrorAction SilentlyContinue)) {
    $gitArguments += @('-c', 'credential.helper=', '-c', 'credential.helper=!gh auth git-credential')
}
if ($Action -eq 'push') {
    Invoke-SyncPython (@('export') + $arguments)
    Invoke-SyncPython (@('check') + $arguments)
    # Explicit tracked deliverables only. Never git add . (device secrets are excluded).
    Invoke-Checked git ($gitArguments + @('add', '--', 'config.toml', 'settings.json', 'setup.ps1', 'sync.ps1', 'publish.ps1', 'requirements.txt', 'scripts', 'tests', 'README.md', '.gitignore'))
    & git @gitArguments diff --cached --quiet
    if ($LASTEXITCODE -eq 1) { Invoke-Checked git ($gitArguments + @('commit', '-m', $Message)) }
    elseif ($LASTEXITCODE -ne 0) { throw 'Could not inspect staged changes.' }
    # No auto-rebase: divergence is visible and never overwrites another device.
    Invoke-Checked git ($gitArguments + @('push', '-u', 'origin', 'HEAD'))
    Invoke-SyncPython (@('record') + $arguments)
    Write-Host 'Uploaded. Run setup.ps1 to apply shared edits on this device.'
} else {
    $dirty = & git @gitArguments status --porcelain
    if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect Git status.' }
    if ($dirty) { throw 'Uncommitted repository edits found. Commit/push them before pulling.' }
    # Preflight device drift before changing the checkout.
    Invoke-SyncPython (@('check-local') + $arguments)
    Invoke-Checked git ($gitArguments + @('pull', '--ff-only'))
    $setupArguments = @{ NonInteractive = $NonInteractive }
    if ($Target) { $setupArguments.Target = $Target }
    & "$PSScriptRoot\setup.ps1" @setupArguments
}
