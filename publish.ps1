[CmdletBinding()]
param([string]$Name = 'windows-mcp-sync')
. "$PSScriptRoot\scripts\common.ps1"
Initialize-SyncPython
Invoke-SyncPython @('check')
Set-GitHubProcessCredential
if (-not (Get-Command gh.exe -ErrorAction SilentlyContinue)) { Install-WingetPackage 'GitHub.cli' }
if (-not (Get-Command git.exe -ErrorAction SilentlyContinue)) { Install-WingetPackage 'Git.Git' }
Invoke-Checked gh @('api', 'user', '--jq', '.login')
if (-not (Test-Path "$PSScriptRoot\.git")) { Invoke-Checked git @('-C', $PSScriptRoot, 'init', '-b', 'master') }
Invoke-Checked git @('-C', $PSScriptRoot, 'add', '--', 'config.toml', 'settings.json', 'setup.ps1', 'sync.ps1', 'publish.ps1', 'requirements.txt', 'scripts', 'tests', 'README.md', '.gitignore')
& git -C $PSScriptRoot diff --cached --quiet
if ($LASTEXITCODE -eq 1) { Invoke-Checked git @('-C', $PSScriptRoot, 'commit', '-m', 'Add portable Windows MCP configuration and setup') }
elseif ($LASTEXITCODE -ne 0) { throw 'Could not inspect staged changes.' }
Invoke-Checked gh @('repo', 'create', $Name, '--private', '--source', $PSScriptRoot, '--remote', 'origin')
Invoke-Checked git @('-C', $PSScriptRoot, 'push', '-u', 'origin', 'master')
Invoke-Checked gh @('repo', 'view', $Name, '--json', 'url,isPrivate', '--jq', '{url,isPrivate}')
