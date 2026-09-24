$ErrorActionPreference = 'Stop'
$script:RepoRoot = Split-Path -Parent $PSScriptRoot
$env:UV_CACHE_DIR = Join-Path $script:RepoRoot '.local\uv-cache'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $script:RepoRoot '.local\python'
$env:PIP_CACHE_DIR = Join-Path $script:RepoRoot '.local\pip-cache'

function Invoke-Checked {
    param([string]$Exe, [string[]]$Arguments)
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed ($LASTEXITCODE): $Exe" }
}

function Update-ProcessPath {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User') + ';' + $env:Path
}

function Install-WingetPackage([string]$Id) {
    if (-not (Get-Command winget.exe -ErrorAction SilentlyContinue)) {
        throw "winget is required to install $Id. Install Windows App Installer, then retry."
    }
    Invoke-Checked winget.exe @('install', '--id', $Id, '--exact', '--accept-package-agreements', '--accept-source-agreements')
    Update-ProcessPath
}

function Initialize-SyncPython {
    $venvPython = Join-Path $script:RepoRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path $venvPython)) {
        $pythonCommand = $null
        foreach ($candidate in @('python.exe', 'py.exe')) {
            if (Get-Command $candidate -ErrorAction SilentlyContinue) {
                $savedPreference = $ErrorActionPreference
                $ErrorActionPreference = 'Continue'
                $candidatePath = & $candidate -c 'import sys; print(sys.executable if sys.version_info >= (3,11) else str())' 2>$null
                $ErrorActionPreference = $savedPreference
                if ($LASTEXITCODE -eq 0 -and $candidatePath -and (Test-Path $candidatePath)) { $pythonCommand = $candidatePath; break }
            }
        }
        if (-not $pythonCommand) {
            Install-WingetPackage 'Python.Python.3.12'
            foreach ($path in @("$env:LOCALAPPDATA\Programs\Python\Python312\python.exe", "$env:ProgramFiles\Python312\python.exe")) {
                if (Test-Path $path) { $pythonCommand = $path; break }
            }
            if (-not $pythonCommand) { throw 'Python installed. Open a new terminal and retry setup.ps1.' }
        }
        Invoke-Checked $pythonCommand @('-m', 'venv', (Join-Path $script:RepoRoot '.venv'))
    }
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try { $hash = [BitConverter]::ToString($sha.ComputeHash([IO.File]::ReadAllBytes((Join-Path $script:RepoRoot 'requirements.txt')))).Replace('-', '') }
    finally { $sha.Dispose() }
    $stamp = Join-Path $script:RepoRoot '.venv\requirements.sha256'
    if (-not (Test-Path $stamp) -or (Get-Content $stamp -Raw).Trim() -ne $hash) {
        Invoke-Checked $venvPython @('-m', 'pip', 'install', '-r', (Join-Path $script:RepoRoot 'requirements.txt'))
        Set-Content -LiteralPath $stamp -Value $hash -Encoding ASCII
    }
    $script:SyncPython = $venvPython
}

function Invoke-SyncPython([string[]]$Arguments) {
    Invoke-Checked $script:SyncPython (@((Join-Path $script:RepoRoot 'scripts\mcp_sync.py')) + $Arguments)
}

function Set-GitHubProcessCredential {
    # Process-scoped only; never store tokens in Git remote URLs or command arguments.
    if (-not $env:GH_TOKEN -and $env:GITHUB_PAT_TOKEN) { $env:GH_TOKEN = $env:GITHUB_PAT_TOKEN }
    if ($env:GH_TOKEN) {
        $count = 0
        if ($env:GIT_CONFIG_COUNT) { $count = [int]$env:GIT_CONFIG_COUNT }
        $slot = $count
        $key = 'http.https://github.com/.extraheader'
        for ($i = 0; $i -lt $count; $i++) {
            if ([Environment]::GetEnvironmentVariable("GIT_CONFIG_KEY_$i", 'Process') -eq $key) { $slot = $i; break }
        }
        $basic = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes('x-access-token:' + $env:GH_TOKEN))
        [Environment]::SetEnvironmentVariable("GIT_CONFIG_KEY_$slot", $key, 'Process')
        [Environment]::SetEnvironmentVariable("GIT_CONFIG_VALUE_$slot", ('Authorization: Basic ' + $basic), 'Process')
        if ($slot -eq $count) { $env:GIT_CONFIG_COUNT = [string]($count + 1) }
    }
}
