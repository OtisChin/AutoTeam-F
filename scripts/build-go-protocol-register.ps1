$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$OutDir = Join-Path $Root 'bin'
New-Item -ItemType Directory -Force $OutDir | Out-Null
Push-Location (Join-Path $Root 'go/protocol-register')
try {
  go test ./...
  go build -o (Join-Path $OutDir 'protocol-registerd.exe') ./cmd/protocol-registerd
} finally {
  Pop-Location
}
Write-Host "Built $OutDir\protocol-registerd.exe"
