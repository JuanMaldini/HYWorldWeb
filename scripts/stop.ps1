<#
================================================================
 HYWorld — Stop
 Baja los contenedores y el frontend.
================================================================
#>

[CmdletBinding()]
param(
    [switch]$KeepWeb,   # deja el frontend corriendo
    [switch]$Quiet      # sin pausa final (lo usa preflight.ps1 antes de arrancar)
)

$ErrorActionPreference = 'Continue'

$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$Repo        = Split-Path -Parent $ScriptDir
$ComposeFile = Join-Path $ScriptDir 'docker-compose.yml'

function Say { param([string]$m, [string]$c = 'White') Write-Host "[$((Get-Date).ToString('HH:mm:ss'))] $m" -ForegroundColor $c }

Say 'Deteniendo contenedores...' 'Cyan'
# --profile local para que alcance tambien al PocketBase local
& docker compose -f $ComposeFile --profile local down 2>&1 | Out-Null

# Red de seguridad por si quedo algo huerfano de una corrida vieja
foreach ($name in @('hyworld_ml', 'hyworld_assets', 'hyworld_pb')) {
    $exists = (& docker ps -aq --filter "name=^$name$" 2>$null)
    if ($exists) {
        Say "  Forzando $name..." 'Yellow'
        & docker rm -f $name 2>&1 | Out-Null
    }
}
Say 'Contenedores detenidos.' 'Green'

if (-not $KeepWeb) {
    Say 'Deteniendo frontend (:5173)...' 'Cyan'
    $conns = Get-NetTCPConnection -LocalPort 5173 -State Listen -ErrorAction SilentlyContinue
    foreach ($c in $conns) {
        try { Stop-Process -Id $c.OwningProcess -Force -ErrorAction Stop } catch { }
    }
    Say 'Frontend detenido.' 'Green'
}

if (-not $Quiet) {
    Say "Listo. Para reiniciar: $Repo\start.bat" 'Cyan'
    Start-Sleep -Seconds 2
}
