param(
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 8787,
    [string]$ExePath = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Resolve-AutoTeamExe {
    param([string]$RequestedPath)

    if ($RequestedPath) {
        $resolved = Resolve-Path -LiteralPath $RequestedPath -ErrorAction Stop
        return $resolved.Path
    }

    $scriptDir = $PSScriptRoot
    $parentDir = Split-Path -Parent $scriptDir
    $candidates = @(
        (Join-Path $scriptDir "autoteam.exe"),
        (Join-Path $scriptDir "dist\autoteam.exe"),
        (Join-Path $parentDir "dist\autoteam.exe")
    )

    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }

    throw "autoteam.exe was not found. Build it first with scripts\build-exe.ps1, or pass -ExePath."
}

$exe = Resolve-AutoTeamExe -RequestedPath $ExePath
$runDir = Split-Path -Parent $exe
Set-Location $runDir

$dataDir = Join-Path $runDir "data"
if (-not (Test-Path -LiteralPath $dataDir)) {
    New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
}

$envExample = Join-Path $runDir ".env.example"
$envFile = Join-Path $runDir ".env"
if (-not (Test-Path -LiteralPath $envFile) -and (Test-Path -LiteralPath $envExample)) {
    Copy-Item -LiteralPath $envExample -Destination $envFile
    Write-Host "Created .env from .env.example. You can finish setup in the web panel."
}

Write-Host "Starting AutoTeam-F: http://$HostAddress`:$Port"
& $exe api --host $HostAddress --port $Port
exit $LASTEXITCODE
