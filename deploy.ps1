[CmdletBinding()]
param(
    [switch]$Help,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ($Help) {
    Write-Host @'
Usage: powershell -ExecutionPolicy Bypass -File .\deploy.ps1 [-DryRun]

Apply migrations, create the initial administrator, synchronize app packages,
and start the frontend, backend, execution workers and connectors on Windows.
Requires backend\venv, Node.js, and installed frontend dependencies.

Environment variables (same as deploy.sh):
  BACKEND_HOST                Default: 0.0.0.0
  BACKEND_PORT                Default: 8080
  FRONTEND_PORT               Default: 3030
  VITE_PROXY_TARGET           Default: http://127.0.0.1:<BACKEND_PORT>
  EXECUTION_WORKERS_ENABLED   Default: True; False for a relay-only server
  REMOTE_ACCESS_HOST_ENABLED  Default: True; False for a relay-only server
  REMOTE_CONNECTOR_LOCAL_URL  Default: http://127.0.0.1:<BACKEND_PORT>
  DJANGO_SUPERUSER_USERNAME / PASSWORD / EMAIL (each with DJANGO_SUPERUSER_ prefix)
                             Optional non-interactive administrator creation

Django configuration is read from the environment and backend\.env.
-DryRun checks prerequisites and prints the plan without changing the database.
Service output is written to backend\logs\deploy-<timestamp>-<pid>.
Keep this terminal open; Ctrl+C stops all managed service process trees.
This launcher is for local development, not a production Windows service.
'@
    exit 0
}

$backendDir = Join-Path $PSScriptRoot 'backend'
$frontendDir = Join-Path $PSScriptRoot 'frontend'
$pythonBin = Join-Path $backendDir 'venv\Scripts\python.exe'
$viteEntry = Join-Path $frontendDir 'node_modules\vite\bin\vite.js'
$services = [System.Collections.Generic.List[object]]::new()

function Get-Setting([string]$Name, [string]$Default) {
    $value = [Environment]::GetEnvironmentVariable($Name)
    if ([string]::IsNullOrEmpty($value)) { return $Default }
    return $value
}

function Test-Enabled([string]$Value) {
    return $Value -in @('True', '1', 'yes')
}

function Invoke-Manage([string[]]$CommandArguments) {
    & $pythonBin manage.py @CommandArguments
    if ($LASTEXITCODE -ne 0) {
        throw "manage.py $($CommandArguments[0]) failed (exit $LASTEXITCODE)."
    }
}

function Start-ManagedService([string]$Name, [string]$Executable, [string[]]$CommandArguments, [string]$Directory) {
    # Start-Process joins ArgumentList into a command line on Windows. Quote each
    # argument explicitly so checkout paths containing spaces remain intact.
    $quotedArguments = foreach ($argument in $CommandArguments) {
        if ($argument.Contains('"')) { throw 'Unexpected quote in service argument.' }
        '"' + $argument + '"'
    }
    $stdout = Join-Path $logDir "$Name.stdout.log"
    $stderr = Join-Path $logDir "$Name.stderr.log"
    $process = Start-Process -FilePath $Executable -ArgumentList $quotedArguments `
        -WorkingDirectory $Directory -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    $services.Add([pscustomobject]@{ Name = $Name; Process = $process; Stderr = $stderr })
    Write-Host "Started $Name (PID $($process.Id))."
}

$savedEnvironment = @{}
$locationPushed = $false
try {
    if (-not (Test-Path -LiteralPath $pythonBin -PathType Leaf)) {
        throw 'Backend virtual environment missing. Run .\install-dependencies.ps1 first.'
    }
    $nodeBin = (Get-Command node.exe -CommandType Application -ErrorAction Stop).Source
    if (-not (Test-Path -LiteralPath $viteEntry -PathType Leaf)) {
        throw 'Frontend dependencies missing. Run .\install-dependencies.ps1 first.'
    }

    $backendHost = Get-Setting 'BACKEND_HOST' '0.0.0.0'
    $backendPort = Get-Setting 'BACKEND_PORT' '8080'
    $frontendPort = Get-Setting 'FRONTEND_PORT' '3030'
    foreach ($port in @($backendPort, $frontendPort)) {
        $number = 0
        if (-not [int]::TryParse($port, [ref]$number) -or $number -lt 1 -or $number -gt 65535) {
            throw "Invalid port: $port (expected 1-65535)."
        }
    }
    if ([int]$backendPort -eq [int]$frontendPort) { throw 'Frontend and backend ports must differ.' }

    $workerEnabled = Test-Enabled (Get-Setting 'EXECUTION_WORKERS_ENABLED' 'True')
    $hostEnabled = Get-Setting 'REMOTE_ACCESS_HOST_ENABLED' 'True'
    $processEnvironment = @{
        VITE_PROXY_TARGET = Get-Setting 'VITE_PROXY_TARGET' "http://127.0.0.1:$backendPort"
        REMOTE_ACCESS_HOST_ENABLED = $hostEnabled
        REMOTE_CONNECTOR_LOCAL_URL = Get-Setting 'REMOTE_CONNECTOR_LOCAL_URL' "http://127.0.0.1:$backendPort"
        PYTHONUNBUFFERED = '1'
    }

    Write-Host "Backend: http://${backendHost}:$backendPort; frontend: http://localhost:$frontendPort"
    Write-Host "Execution workers: $workerEnabled; remote connector: $(Test-Enabled $hostEnabled)"
    if ($DryRun) {
        Write-Host 'Plan: migrate; ensure administrator; sync study-with-method, my-computer, wechat-assistant.'
        Write-Host 'Then start Vite, Django, enabled workers/remote connector, and the WeChat connector.'
        return
    }

    foreach ($name in $processEnvironment.Keys) {
        $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name)
        [Environment]::SetEnvironmentVariable($name, $processEnvironment[$name], 'Process')
    }
    Push-Location $backendDir
    $locationPushed = $true
    Invoke-Manage @('migrate', '--noinput')

    $query = @'
import os
from django.contrib.auth import get_user_model
filters = {'is_superuser': True}
if os.environ.get('DJANGO_SUPERUSER_USERNAME'):
    filters['username'] = os.environ['DJANGO_SUPERUSER_USERNAME']
print('STUDIO_SUPERUSER_EXISTS=' + str(get_user_model().objects.filter(**filters).exists()))
'@
    $result = & $pythonBin manage.py shell -c $query
    if ($LASTEXITCODE -ne 0) { throw 'Failed to check the administrator account.' }
    if ($result -contains 'STUDIO_SUPERUSER_EXISTS=True') {
        Write-Host 'Administrator already exists; skipping creation.'
    } elseif ($result -contains 'STUDIO_SUPERUSER_EXISTS=False') {
        if ($env:DJANGO_SUPERUSER_USERNAME) {
            if (-not $env:DJANGO_SUPERUSER_PASSWORD -or -not $env:DJANGO_SUPERUSER_EMAIL) {
                throw 'Set DJANGO_SUPERUSER_PASSWORD and DJANGO_SUPERUSER_EMAIL for non-interactive creation.'
            }
            Invoke-Manage @('createsuperuser', '--noinput')
        } else {
            if ([Console]::IsInputRedirected) {
                throw 'No administrator exists. Set DJANGO_SUPERUSER_USERNAME, DJANGO_SUPERUSER_PASSWORD and DJANGO_SUPERUSER_EMAIL.'
            }
            Invoke-Manage @('createsuperuser')
        }
    } else {
        throw 'Unexpected administrator check output.'
    }
    foreach ($package in @('study-with-method', 'my-computer', 'wechat-assistant')) {
        Invoke-Manage @('sync_app_center', '--package', $package)
    }

    $logDir = Join-Path $backendDir ("logs\deploy-{0}-{1}" -f (Get-Date -Format 'yyyyMMdd-HHmmss'), $PID)
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    Write-Host "Service logs: $logDir"
    # Launch Node directly to avoid npm.cmd/cmd.exe quoting and extra process layers.
    Start-ManagedService 'frontend' $nodeBin @($viteEntry, '--host', '0.0.0.0', '--port', $frontendPort, '--strictPort') $frontendDir
    Start-ManagedService 'backend' $pythonBin @('manage.py', 'runserver', "${backendHost}:$backendPort", '--noreload') $backendDir
    if ($workerEnabled) {
        Start-ManagedService 'worker' $pythonBin @('manage.py', 'run_execution_coordinator', '--worker-pool', 'all') $backendDir
    }
    if (Test-Enabled $hostEnabled) {
        Start-ManagedService 'remote-connector' $pythonBin @('manage.py', 'run_remote_connector') $backendDir
    }
    Start-ManagedService 'wechat-connector' $pythonBin @('manage.py', 'run_wechat_connector') $backendDir
    Write-Host 'Services launched. Check the logs for readiness. Press Ctrl+C to stop.'
    while ($true) {
        foreach ($service in $services) {
            if ($service.Process.HasExited) {
                throw "$($service.Name) exited (code $($service.Process.ExitCode)). See $($service.Stderr)"
            }
        }
        Start-Sleep -Seconds 1
    }
} finally {
    foreach ($service in $services) {
        try {
            if (-not $service.Process.HasExited) {
                Write-Host "Stopping $($service.Name)."
                & "$env:SystemRoot\System32\taskkill.exe" /PID $service.Process.Id /T /F 2>&1 | Out-Null
                if ($LASTEXITCODE -ne 0 -and -not $service.Process.HasExited) {
                    Write-Warning "Could not stop $($service.Name) (PID $($service.Process.Id))."
                }
            }
        } catch {
            Write-Warning "Could not stop $($service.Name): $_"
        } finally {
            $service.Process.Dispose()
        }
    }
    if ($locationPushed) { Pop-Location }
    foreach ($name in $savedEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($name, $savedEnvironment[$name], 'Process')
    }
}
