[CmdletBinding()]
param(
    [string]$Python = 'python',
    [switch]$Development,
    [switch]$SystemDeps,
    [switch]$WithCreationMaster,
    [switch]$WithMobile,
    [switch]$WithCodex,
    [switch]$SkipSubmodules,
    [string[]]$App = @(),
    [switch]$ListApps,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$venvPython = Join-Path $PSScriptRoot 'backend\venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
    if ($ListApps) {
        $listArguments = @('--list-apps')
        foreach ($application in $App) { $listArguments += @('--app', $application) }
        & $Python (Join-Path $PSScriptRoot 'deploy\install_dependencies.py') @listArguments
        if ($LASTEXITCODE -ne 0) { throw 'Failed to list application dependencies.' }
        exit 0
    }
    if ($DryRun) {
        Write-Host "Would create backend\venv using $Python. Run without -DryRun to bootstrap it."
        exit 0
    }
    # The host interpreter is used only to bootstrap the project virtual environment.
    & $Python -m venv (Join-Path $PSScriptRoot 'backend\venv')
    if ($LASTEXITCODE -ne 0) { throw 'Failed to create backend\venv. Install Python 3.11+ first.' }
}
$installerArguments = @()
if ($Development) { $installerArguments += '--development' }
if ($SystemDeps) { $installerArguments += '--system-deps' }
if ($WithCreationMaster) { $installerArguments += '--with-creation-master' }
if ($WithMobile) { $installerArguments += '--with-mobile' }
if ($WithCodex) { $installerArguments += '--with-codex' }
if ($SkipSubmodules) { $installerArguments += '--skip-submodules' }
foreach ($application in $App) { $installerArguments += @('--app', $application) }
if ($ListApps) { $installerArguments += '--list-apps' }
if ($DryRun) { $installerArguments += '--dry-run' }
& $venvPython (Join-Path $PSScriptRoot 'deploy\install_dependencies.py') @installerArguments
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed (exit $LASTEXITCODE)." }
