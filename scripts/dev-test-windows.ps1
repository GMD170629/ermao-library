[CmdletBinding()]
param(
    [ValidateSet("Manager", "Api", "Worker", "Web", "Gateway")]
    [string]$Component = "Manager"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RootDirectory = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$ApiDirectory = Join-Path $RootDirectory "apps\api-python"
$PythonExecutable = Join-Path $ApiDirectory ".venv-windows\Scripts\python.exe"
$NodeExecutable = Join-Path $env:ProgramFiles "nodejs\node.exe"
$CorepackExecutable = Join-Path $env:ProgramFiles "nodejs\corepack.cmd"
$GatewayScript = Join-Path $RootDirectory "scripts\unified-http-gateway.mjs"
$RuntimeDirectory = Join-Path $RootDirectory ".tmp\windows-dev"
$StatePath = Join-Path $RuntimeDirectory "service-processes.json"

$env:STORAGE_ROOT = Join-Path $RootDirectory "storage"
$env:SESSION_SECRET = "dev-test-session-secret-change-me-at-least-32-chars"
$env:MONITOR_REFRESH_INTERVAL_MS = "10000"
$env:GATEWAY_HOST = "0.0.0.0"
$env:GATEWAY_PORT = "3000"
$env:API_HOST = "127.0.0.1"
$env:API_PORT = "8000"
$env:WEB_UPSTREAM_HOST = "127.0.0.1"
$env:WEB_UPSTREAM_PORT = "3001"

function Invoke-Pnpm {
    & $CorepackExecutable pnpm @args
}

if ($Component -ne "Manager") {
    switch ($Component) {
        "Api" {
            Set-Location $ApiDirectory
            & $PythonExecutable -m uvicorn app.main:app --host 127.0.0.1 --port 8000
        }
        "Worker" {
            Set-Location $ApiDirectory
            & $PythonExecutable -m app.worker.main
        }
        "Web" {
            Set-Location $RootDirectory
            Invoke-Pnpm --filter "@shuku/web" exec next dev --webpack -H 127.0.0.1 -p 3001
        }
        "Gateway" {
            Set-Location $RootDirectory
            & $NodeExecutable $GatewayScript
        }
    }
    exit $LASTEXITCODE
}

foreach ($requiredFile in @($PythonExecutable, $NodeExecutable, $CorepackExecutable, $GatewayScript)) {
    if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) {
        throw "Required runtime file is missing: $requiredFile"
    }
}

& $PythonExecutable -c "import sqlalchemy, uvicorn"
if ($LASTEXITCODE -ne 0) {
    throw "Windows Python is unavailable; the previous service was not stopped. See docs/python-backend-runtime.md for environment setup."
}

New-Item -ItemType Directory -Path $RuntimeDirectory -Force | Out-Null
New-Item -ItemType Directory -Path $env:STORAGE_ROOT -Force | Out-Null

if (Test-Path -LiteralPath $StatePath) {
    $previous = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json
    if ([System.IO.Path]::GetFullPath([string]$previous.rootDirectory) -eq $RootDirectory) {
        $previousProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $([int]$previous.managerPid)" -ErrorAction SilentlyContinue
        if ($null -ne $previousProcess -and [string]$previousProcess.CommandLine -like "*dev-test-windows.ps1*") {
            Write-Host "Stopping the previous Windows service..."
            & taskkill.exe /PID ([int]$previous.managerPid) /T /F *> $null
        }
    }
    Remove-Item -LiteralPath $StatePath -Force
}

$portDeadline = [DateTime]::UtcNow.AddSeconds(15)
do {
    $listeners = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
        Where-Object { $_.LocalPort -in @(3000, 3001, 8000) }
    if (-not $listeners) { break }
    Start-Sleep -Milliseconds 250
} while ([DateTime]::UtcNow -lt $portDeadline)
if ($listeners) {
    throw "Ports 3000, 3001, or 8000 are already in use."
}

Write-Host "Running database prestart check..."
Push-Location $ApiDirectory
try {
    & $PythonExecutable -m app.bootstrap.prestart
    if ($LASTEXITCODE -ne 0) { throw "Database prestart failed with exit code $LASTEXITCODE." }
}
finally {
    Pop-Location
}

Write-Host "Preparing the PDF.js worker..."
Push-Location $RootDirectory
try {
    Invoke-Pnpm --filter "@shuku/web" exec node scripts/prepare-pdfjs-worker.mjs
    if ($LASTEXITCODE -ne 0) { throw "PDF.js worker preparation failed with exit code $LASTEXITCODE." }
}
finally {
    Pop-Location
}

$logDirectory = Join-Path $RuntimeDirectory ("logs\" + (Get-Date -Format "yyyyMMdd-HHmmss"))
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null

function Start-Component {
    param([Parameter(Mandatory = $true)][string]$Name)

    $powerShellExecutable = (Get-Process -Id $PID).Path
    $arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Component $Name"
    Start-Process -FilePath $powerShellExecutable -ArgumentList $arguments `
        -WorkingDirectory $RootDirectory -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logDirectory "$($Name.ToLower()).stdout.log") `
        -RedirectStandardError (Join-Path $logDirectory "$($Name.ToLower()).stderr.log") `
        -PassThru
}

function Wait-ForUrl {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)]$Process
    )

    $deadline = [DateTime]::UtcNow.AddSeconds(60)
    do {
        if ($Process.HasExited) { throw "A service exited before $Url became ready. See $logDirectory." }
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -lt 500) { return }
        }
        catch {
            Start-Sleep -Milliseconds 500
        }
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "Timed out waiting for $Url. See $logDirectory."
}

$processes = @()
try {
    $processes += Start-Component "Api"
    Wait-ForUrl "http://127.0.0.1:8000/api/health" $processes[0]
    $processes += Start-Component "Worker"
    $processes += Start-Component "Web"
    $processes += Start-Component "Gateway"

    [pscustomobject]@{
        rootDirectory = $RootDirectory
        managerPid = $PID
        processes = @($processes | ForEach-Object { $_.Id })
        logDirectory = $logDirectory
    } | ConvertTo-Json | Set-Content -LiteralPath $StatePath -Encoding UTF8

    Wait-ForUrl "http://127.0.0.1:3000/api/health" $processes[3]
    Wait-ForUrl "http://127.0.0.1:3000/" $processes[3]

    Write-Host ""
    Write-Host "Windows test service is ready: http://localhost:3000"
    Write-Host "Logs: $logDirectory"
    Write-Host "Press Ctrl+C to stop. Run start-windows.cmd again to restart."

    while ($true) {
        foreach ($process in $processes) {
            if ($process.HasExited) { throw "A service exited unexpectedly. See $logDirectory." }
        }
        Start-Sleep -Seconds 2
    }
}
finally {
    foreach ($process in $processes) {
        if (-not $process.HasExited) { & taskkill.exe /PID $process.Id /T /F *> $null }
    }
    if (Test-Path -LiteralPath $StatePath) { Remove-Item -LiteralPath $StatePath -Force }
}
