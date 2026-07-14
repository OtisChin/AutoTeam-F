[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$scriptRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$sourceRoot = Join-Path $scriptRoot 'src'
$outputPath = Join-Path $scriptRoot 'pplink.exe'
$temporaryPath = Join-Path $scriptRoot '.pplink-build.exe'
$environmentNames = @('CGO_ENABLED', 'GOOS', 'GOARCH', 'GOAMD64', 'GOWORK', 'GOFLAGS', 'SOURCE_DATE_EPOCH')
$previousEnvironment = @{}
$pushed = $false

foreach ($name in $environmentNames) {
    $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}

try {
    $env:CGO_ENABLED = '0'
    $env:GOOS = 'windows'
    $env:GOARCH = 'amd64'
    $env:GOAMD64 = 'v1'
    $env:GOWORK = 'off'
    $env:GOFLAGS = ''
    $env:SOURCE_DATE_EPOCH = '0'

    if (Test-Path -LiteralPath $temporaryPath) {
        Remove-Item -LiteralPath $temporaryPath -Force
    }

    Push-Location -LiteralPath $sourceRoot
    $pushed = $true
    $goArgs = @(
        'build'
        '-mod=readonly'
        '-trimpath'
        '-buildvcs=false'
        '-tags=netgo,osusergo'
        '-ldflags=-s -w -buildid='
        '-o'
        $temporaryPath
        './cmd/pplink'
    )
    & go @goArgs
    if ($LASTEXITCODE -ne 0) {
        throw "go build failed with exit code $LASTEXITCODE"
    }
    Pop-Location
    $pushed = $false

    Move-Item -LiteralPath $temporaryPath -Destination $outputPath -Force
    $file = Get-Item -LiteralPath $outputPath
    $hash = Get-FileHash -LiteralPath $outputPath -Algorithm SHA256
    Write-Output ("Built {0} ({1} bytes)" -f $file.FullName, $file.Length)
    Write-Output ("SHA256 {0}" -f $hash.Hash)
}
finally {
    if ($pushed) {
        Pop-Location
    }
    if (Test-Path -LiteralPath $temporaryPath) {
        Remove-Item -LiteralPath $temporaryPath -Force
    }
    foreach ($name in $environmentNames) {
        $previous = $previousEnvironment[$name]
        if ($null -eq $previous) {
            Remove-Item -LiteralPath ("Env:{0}" -f $name) -ErrorAction SilentlyContinue
        }
        else {
            Set-Item -LiteralPath ("Env:{0}" -f $name) -Value $previous
        }
    }
}
