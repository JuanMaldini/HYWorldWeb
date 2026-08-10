<#
================================================================
 HYWorld — Preflight + Start
================================================================
 Reemplaza a las ~260 lineas de start.bat. Hace TODOS los chequeos
 antes de arrancar, arma la configuracion sola y recien al final
 valida que el proyecto responda de verdad en localhost.

 Dos modos, resueltos solos a partir del .env del repo:
   LOCAL  (.env vacio o incompleto) -> PocketBase propio en :8092,
          colecciones y cuentas creadas automaticamente. No hace
          falta tocar nada.
   REMOTO (.env con PB_URL + cuenta de servicio) -> usa esa instancia.

 Todo el estado local vive en <repo>\.data
================================================================
#>

[CmdletBinding()]
param(
    [switch]$Web,        # solo frontend, sin contenedores
    [switch]$Rebuild,    # fuerza rebuild de las imagenes
    [switch]$NoBrowser,  # no abre el navegador al final
    [switch]$SkipPull    # no hace git pull de los repos ML
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# ── Rutas base ────────────────────────────────────────────────
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Repo      = Split-Path -Parent $ScriptDir
$RootEnv   = Join-Path $Repo '.env'
$ComposeFile = Join-Path $ScriptDir 'docker-compose.yml'
$LegacyData  = 'C:\HyWorldWebData'

# ── Estado compartido entre fases ─────────────────────────────
$script:LogFile = $null
$script:DevMail = ''
$script:DevPass = ''
$script:WorkerMail = ''
$script:WorkerPass = ''
$script:AdminMail = ''
$script:AdminPass = ''
function Write-Log {
    param([string]$Message, [ValidateSet('INFO','OK','WARN','ERROR','STEP')][string]$Level = 'INFO')
    $stamp = (Get-Date).ToString('HH:mm:ss')
    $line  = "[$stamp] $Message"
    switch ($Level) {
        'STEP'  { Write-Host ''; Write-Host $line -ForegroundColor Cyan }
        'OK'    { Write-Host "$line" -ForegroundColor Green }
        'WARN'  { Write-Host "$line" -ForegroundColor Yellow }
        'ERROR' { Write-Host "$line" -ForegroundColor Red }
        default { Write-Host $line }
    }
    if ($script:LogFile) { Add-Content -Path $script:LogFile -Value "[$Level] $line" -Encoding utf8 }
}

function Fail {
    param([string]$Message, [string]$Hint)
    Write-Log $Message 'ERROR'
    if ($Hint) { Write-Log "  -> $Hint" 'WARN' }
    if ($script:LogFile) { Write-Log "  Log completo: $script:LogFile" }
    Write-Host ''
    Read-Host 'Enter para cerrar'
    exit 1
}

function Invoke-Logged {
    <# Corre un comando externo mandando su salida al log. Devuelve $true si exit 0. #>
    param([string]$File, [string[]]$Arguments)
    $out = & $File @Arguments 2>&1
    $ok  = ($LASTEXITCODE -eq 0)
    if ($script:LogFile -and $out) { Add-Content -Path $script:LogFile -Value $out -Encoding utf8 }
    return $ok
}

# ── Manejo del .env (formato KEY=VALUE) ───────────────────────
function Read-EnvFile {
    param([string]$Path)
    $map = @{}
    if (-not (Test-Path $Path)) { return $map }
    foreach ($line in Get-Content $Path -Encoding utf8) {
        $t = $line.Trim()
        if ($t -eq '' -or $t.StartsWith('#')) { continue }
        $i = $t.IndexOf('=')
        if ($i -lt 1) { continue }
        # Split solo en el PRIMER '=': los valores pueden contener '='
        # (los JWT terminan en padding '='), que es donde se rompia el
        # parseo con `for /f delims==` del start.bat viejo.
        $map[$t.Substring(0, $i).Trim()] = $t.Substring($i + 1).Trim()
    }
    return $map
}

function Set-EnvValue {
    param([string]$Path, [string]$Key, [string]$Value)
    $lines = @()
    if (Test-Path $Path) { $lines = @(Get-Content $Path -Encoding utf8) }
    $found = $false
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match "^\s*$([regex]::Escape($Key))\s*=") {
            $lines[$i] = "$Key=$Value"; $found = $true; break
        }
    }
    if (-not $found) { $lines += "$Key=$Value" }
    Set-Content -Path $Path -Value $lines -Encoding utf8
}

function New-Secret {
    param([int]$Length = 24)
    $chars = 'abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789'.ToCharArray()
    -join (1..$Length | ForEach-Object { $chars | Get-Random })
}

function Wait-Until {
    <# Espera a que un scriptblock devuelva $true. $false si se agota. #>
    param([scriptblock]$Condition, [int]$TimeoutSec = 60, [int]$IntervalSec = 2)
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        try { if (& $Condition) { return $true } } catch { }
        Start-Sleep -Seconds $IntervalSec
    }
    return $false
}

function Get-ContainerHealth {
    param([string]$Name)
    $s = (& docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' $Name 2>$null)
    if ($LASTEXITCODE -ne 0) { return 'missing' }
    return "$s".Trim()
}

# =================================================================
#  FASE 1 — Chequeos del entorno
# =================================================================
function Find-DockerDesktop {
    $candidates = @(
        (Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'Docker\Docker\Docker Desktop.exe'),
        (Join-Path $env:LOCALAPPDATA 'Docker\Docker Desktop.exe')
    )
    foreach ($c in $candidates) { if ($c -and (Test-Path $c)) { return $c } }
    return $null
}

function Install-DockerDesktop {
    <# Ultimo recurso: instalar con winget. Si no hay winget, damos el link. #>
    $link = 'https://www.docker.com/products/docker-desktop/'
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Fail 'Docker Desktop no esta instalado y winget no esta disponible.' "Descargalo de $link"
    }
    Write-Log '  Docker Desktop no esta instalado. Instalando con winget...' 'WARN'
    Write-Log '  (puede pedirte permisos de administrador)'
    $ok = Invoke-Logged 'winget' @('install', '--id', 'Docker.DockerDesktop', '-e',
                                   '--accept-package-agreements', '--accept-source-agreements')
    if (-not $ok) { Fail 'La instalacion con winget fallo.' "Instalalo a mano desde $link" }
    Write-Log '  Docker Desktop instalado.' 'OK'
    Write-Log '  Puede hacer falta reiniciar Windows antes del primer uso.' 'WARN'
}

function Initialize-Docker {
    <# Deja el daemon de Docker listo: lo instala si falta, lo abre si esta
       apagado y espera a que responda. #>
    $exe = Find-DockerDesktop
    if (-not (Get-Command docker -ErrorAction SilentlyContinue) -and -not $exe) {
        Install-DockerDesktop
        $exe = Find-DockerDesktop
    }

    & docker info *> $null
    if ($LASTEXITCODE -eq 0) { Write-Log '  Docker: OK' 'OK'; return }

    if (-not $exe) {
        Fail 'Docker no responde y no encuentro Docker Desktop.' 'Abrilo a mano y reintenta.'
    }
    Write-Log '  Docker esta apagado - abriendo Docker Desktop...' 'WARN'
    Start-Process -FilePath $exe | Out-Null
    Write-Log '  Esperando al daemon (hasta 3 min)...'
    $up = Wait-Until { & docker info *> $null; $LASTEXITCODE -eq 0 } -TimeoutSec 180 -IntervalSec 5
    if (-not $up) {
        Fail 'Docker Desktop no termino de arrancar.' 'Abrilo a mano, espera a que diga "Engine running" y reintenta.'
    }
    Write-Log '  Docker: OK (arrancado automaticamente)' 'OK'
}

function Test-Prerequisites {
    Write-Log 'FASE 1/8 — Chequeos del entorno' 'STEP'

    Initialize-Docker

    & docker compose version *> $null
    if ($LASTEXITCODE -ne 0) { Fail 'No esta disponible "docker compose" (v2).' 'Actualizar Docker Desktop.' }

    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        Fail 'git no esta instalado.' 'Instalar Git for Windows.'
    }
    Write-Log '  git: OK' 'OK'

    if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) {
        Fail 'pnpm no esta instalado.' 'npm install -g pnpm'
    }
    Write-Log '  pnpm: OK' 'OK'

    # GPU: aviso, no bloqueo (el contenedor valida de verdad al arrancar)
    if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
        $gpu = (& nvidia-smi --query-gpu=name --format=csv,noheader 2>$null | Select-Object -First 1)
        if ($gpu) { Write-Log "  GPU: $($gpu.Trim())" 'OK' }
    } else {
        Write-Log '  AVISO: nvidia-smi no encontrado - el worker puede no arrancar.' 'WARN'
    }
}

# =================================================================
#  FASE 2 — Configuracion y carpeta de datos
# =================================================================
function Initialize-Config {
    Write-Log 'FASE 2/8 — Configuracion y datos' 'STEP'

    if (-not (Test-Path $RootEnv)) {
        Copy-Item (Join-Path $Repo '.env.example') $RootEnv
        Write-Log '  .env creado desde .env.example (modo local por defecto)' 'OK'
    }
    $cfg = Read-EnvFile $RootEnv

    # --- Carpeta de datos --------------------------------------
    # Interna: el usuario no la elige. Vive siempre en <repo>\.data
    # asi no hay rutas absolutas en el repo y el borrado del clon
    # limpia todo.
    $script:DataDir = Join-Path $Repo '.data'

    # El log arranca ANTES de la migracion: si algo sale mal ahi, tiene que
    # quedar registrado (antes esto se perdia porque LogFile se seteaba despues).
    if (-not (Test-Path (Join-Path $dataDir 'logs'))) {
        New-Item -ItemType Directory -Path (Join-Path $dataDir 'logs') -Force | Out-Null
    }
    $script:LogFile = Join-Path $dataDir 'logs\start_log.txt'

    # --- Migracion desde el layout viejo (C:\HyWorldWebData) ---
    # Se dispara si el layout viejo tiene datos y el nuevo todavia no,
    # aunque .data ya exista: mirar solo "existe .data" fallaba cuando una
    # corrida previa lo habia creado vacio.
    if (Test-Path $LegacyData) {
        $payload = @('models', 'Hunyuan3D-2', 'projects', 'repo')
        $legacyHas = @($payload | Where-Object {
            $src = Join-Path $LegacyData $_
            (Test-Path $src) -and (@(Get-ChildItem $src -Force -ErrorAction SilentlyContinue).Count -gt 0)
        })
        $pending = @($legacyHas | Where-Object {
            $dst = Join-Path $dataDir $_
            -not ((Test-Path $dst) -and (@(Get-ChildItem $dst -Force -ErrorAction SilentlyContinue).Count -gt 0))
        })
        if ($pending.Count -gt 0) {
            $sz = [math]::Round(((Get-ChildItem $LegacyData -Recurse -File -Force -ErrorAction SilentlyContinue |
                    Measure-Object Length -Sum).Sum / 1GB), 1)
            Write-Log "  Encontrado el layout viejo en $LegacyData ($sz GB)." 'WARN'
            Write-Log "  Por migrar: $($pending -join ', ')"
            Write-Log "  Mover evita re-descargar los modelos."
            $ans = Read-Host '  Mover ahora? [S/n]'
            if ($ans -eq '' -or $ans -match '^[sSyY]') {
                foreach ($item in $pending) {
                    Write-Log "  Moviendo $item... (C: -> D: copia, puede tardar)"
                    $dst = Join-Path $dataDir $item
                    if (Test-Path $dst) { Remove-Item $dst -Recurse -Force }
                    Move-Item -Path (Join-Path $LegacyData $item) -Destination $dst -Force
                }
                Write-Log '  Datos migrados.' 'OK'
            } else {
                Write-Log '  Migracion salteada.' 'WARN'
            }
        }
    }

    foreach ($sub in @('models', 'repo', 'projects', 'logs', 'pocketbase')) {
        $p = Join-Path $dataDir $sub
        if (-not (Test-Path $p)) { New-Item -ItemType Directory -Path $p -Force | Out-Null }
    }
    Write-Log "  Datos en: $dataDir" 'OK'

    # --- Modelos ------------------------------------------------
    # Interna: cuelga de DataDir/models. La cache de HuggingFace vive
    # adentro, asi un solo volumen cubre todo.
    $script:ModelsDir = Join-Path $script:DataDir 'models'
    if (-not (Test-Path $script:ModelsDir)) { New-Item -ItemType Directory -Path $script:ModelsDir -Force | Out-Null }
    Write-Log "  Modelos en: $($script:ModelsDir)" 'OK'

    # --- Espacio en disco --------------------------------------
    try {
        $drive = (Get-Item $script:DataDir).PSDrive
        $freeGB = [math]::Round($drive.Free / 1GB, 1)
        if ($freeGB -lt 30) {
            Write-Log "  AVISO: quedan $freeGB GB libres en $($drive.Name): - los modelos necesitan mas." 'WARN'
        } else {
            Write-Log "  Espacio libre: $freeGB GB" 'OK'
        }
    } catch { }

    $pbUrl = ''
    if ($cfg.ContainsKey('PB_URL')) { $pbUrl = $cfg['PB_URL'] }
    $pbUrl = $pbUrl.Trim().TrimEnd('/')

    if ([string]::IsNullOrWhiteSpace($pbUrl)) {
        $script:Mode        = 'local'
        $script:PbUrlHost   = 'http://localhost:8092'
        $script:PbUrlWorker = 'http://pocketbase:8090'
        Write-Log '  Modo: LOCAL (PocketBase propio en :8092)' 'OK'
    } else {
        $alive = $false
        try {
            $r = Invoke-WebRequest -Uri "$pbUrl/api/health" -UseBasicParsing -TimeoutSec 5
            $alive = ($r.StatusCode -eq 200)
        } catch { $alive = $false }
        if (-not $alive) {
            Write-Log "  PB_URL=$pbUrl no responde. Cayendo a MODO LOCAL." 'WARN'
            $script:Mode        = 'local'
            $script:PbUrlHost   = 'http://localhost:8092'
            $script:PbUrlWorker = 'http://pocketbase:8090'
        } else {
            $script:Mode        = 'remote'
            $script:PbUrlHost   = $pbUrl
            $script:PbUrlWorker = $pbUrl
            Write-Log "  Modo: REMOTO ($pbUrl)" 'OK'
        }
    }

    $script:Cfg = $cfg
}

# =================================================================
#  FASE 3 — Repos ML
# =================================================================
function Sync-Repos {
    Write-Log 'FASE 3/8 — Repos ML' 'STEP'
    $repos = @(
        @{ Name = 'HY-World-2.0'; Url = 'https://github.com/Tencent-Hunyuan/HY-World-2.0'; Path = (Join-Path $script:DataDir 'repo') },
        @{ Name = 'Hunyuan3D-2';  Url = 'https://github.com/Tencent-Hunyuan/Hunyuan3D-2';  Path = (Join-Path $script:DataDir 'Hunyuan3D-2') }
    )
    foreach ($r in $repos) {
        if (Test-Path (Join-Path $r.Path '.git')) {
            if ($SkipPull) { Write-Log "  $($r.Name): sin cambios (--SkipPull)"; continue }
            Write-Log "  $($r.Name): git pull..."
            if (-not (Invoke-Logged 'git' @('-C', $r.Path, 'pull', '--ff-only'))) {
                Write-Log "  AVISO: git pull de $($r.Name) fallo - se sigue con la copia local." 'WARN'
            }
        } else {
            Write-Log "  $($r.Name): clonando (puede tardar)..."
            if (-not (Invoke-Logged 'git' @('clone', '--depth=1', $r.Url, $r.Path))) {
                Fail "No se pudo clonar $($r.Name)." 'Revisar conexion / proxy.'
            }
        }
        Write-Log "  $($r.Name): OK" 'OK'
    }
}

# =================================================================
#  FASE 4 — Config resuelta para compose (scripts/.env)
# =================================================================
function Write-ComposeEnv {
    Write-Log 'FASE 4/8 — Generando configuracion de compose' 'STEP'

    # Arquitectura CUDA real (antes estaba fijo en 8.6 = RTX 30xx)
    $arch = '8.6'
    if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
        $cap = (& nvidia-smi --query-gpu=compute_cap --format=csv,noheader 2>$null | Select-Object -First 1)
        if ($cap -and $cap.Trim() -match '^\d+\.\d+$') { $arch = $cap.Trim() }
    }
    Write-Log "  TORCH_CUDA_ARCH_LIST: $arch" 'OK'

    # Cuenta del worker: vive en .env (PB_WORKER_EMAIL/PASSWORD).
    # start.bat NO pregunta nada: si estan vacias se autogeneran y
    # persisten en .env. El worker es un user comun de hyworld_user,
    # nunca un _superusers.
    $workerMail = 'worker@hyworld.local'
    $workerPass = New-Secret 24
    Write-Log '  Generando credenciales del worker...' 'OK'
    $script:WorkerMail = $workerMail
    $script:WorkerPass = $workerPass

    $dataFwd   = $script:DataDir.Replace('\', '/')
    $modelsFwd = $script:ModelsDir.Replace('\', '/')
    $authColl = 'hyworld_user'; $dataColl = 'hyworld_data'
    if ($script:Cfg.ContainsKey('PB_AUTH_COLLECTION') -and $script:Cfg['PB_AUTH_COLLECTION']) { $authColl = $script:Cfg['PB_AUTH_COLLECTION'] }
    if ($script:Cfg.ContainsKey('PB_DATA_COLLECTION') -and $script:Cfg['PB_DATA_COLLECTION']) { $dataColl = $script:Cfg['PB_DATA_COLLECTION'] }

    $lines = @(
        "HYWORLD_DATA=$dataFwd",
        "MODELS_DIR=$modelsFwd",
        "TORCH_CUDA_ARCH_LIST=$arch",
        "HYWORLD_MODE=$($script:Mode)",
        "PB_URL=$($script:PbUrlWorker)",
        "PB_AUTH_COLLECTION=$authColl",
        "PB_DATA_COLLECTION=$dataColl",
        "PB_WORKER_EMAIL=$workerMail",
        "PB_WORKER_PASSWORD=$workerPass"
    )
    Set-Content -Path (Join-Path $ScriptDir '.env') -Value $lines -Encoding utf8
    Write-Log '  scripts/.env generado' 'OK'
    $script:DataCollection = $dataColl
    $script:AuthCollection = $authColl
}

# =================================================================
#  FASE 5 — Imagenes Docker
# =================================================================
function Build-Images {
    Write-Log 'FASE 5/8 — Imagenes Docker' 'STEP'

    $trigger = Join-Path $script:DataDir 'build_trigger.txt'
    $files = @('Dockerfile', 'Dockerfile.assets', 'entrypoint.sh', 'entrypoint_assets.sh') |
             ForEach-Object { Join-Path $ScriptDir $_ }
    $hash = ($files | Where-Object { Test-Path $_ } |
             ForEach-Object { (Get-FileHash $_ -Algorithm MD5).Hash }) -join ''
    $prev = ''
    if (Test-Path $trigger) { $prev = (Get-Content $trigger -Raw).Trim() }

    $need = $Rebuild -or ($hash -ne $prev)
    & docker image inspect hyworld_ml:latest *> $null
    if ($LASTEXITCODE -ne 0) { $need = $true }
    & docker image inspect hyworld_assets:latest *> $null
    if ($LASTEXITCODE -ne 0) { $need = $true }

    if (-not $need) { Write-Log '  Imagenes OK (sin cambios)' 'OK'; return }

    # Orden obligatorio: Dockerfile.assets hereda de hyworld_ml:latest
    Write-Log '  Construyendo worker (la primera vez puede tardar 20+ min)...'
    if (-not (Invoke-Logged 'docker' @('compose', '-f', $ComposeFile, 'build', 'worker'))) {
        Fail 'Build del worker fallo.' "Ver $script:LogFile"
    }
    Write-Log '  Construyendo asset server...'
    if (-not (Invoke-Logged 'docker' @('compose', '-f', $ComposeFile, 'build', 'assets'))) {
        Fail 'Build del asset server fallo.' "Ver $script:LogFile"
    }
    Set-Content -Path $trigger -Value $hash -Encoding utf8
    Write-Log '  Imagenes construidas' 'OK'
}

# =================================================================
#  FASE 6 — Contenedores + provision de PocketBase
# =================================================================
function Start-Containers {
    Write-Log 'FASE 6/8 — Contenedores' 'STEP'

    $profileArgs = @()
    if ($script:Mode -eq 'local') { $profileArgs = @('--profile', 'local') }

    Write-Log '  Bajando contenedores previos...'
    Invoke-Logged 'docker' (@('compose', '-f', $ComposeFile) + $profileArgs + @('down')) | Out-Null

    if ($script:Mode -eq 'local') {
        if (-not $script:AdminMail) { $script:AdminMail = 'admin@hyworld.local' }
        if (-not $script:AdminPass) { $script:AdminPass = New-Secret 24 }

        Write-Log '  Provisionando admin interno de PocketBase...'
        $sub = @('superuser', 'upsert', $script:AdminMail, $script:AdminPass, '--dir', '/pb_data')
        $base = @('compose', '-f', $ComposeFile, 'run', '--rm', '--no-deps')
        $done = Invoke-Logged 'docker' ($base + @('pocketbase') + $sub)
        if (-not $done) {
            Write-Log '  Reintentando con entrypoint explicito...' 'WARN'
            $done = Invoke-Logged 'docker' ($base + @('--entrypoint', '/usr/local/bin/pocketbase', 'pocketbase') + $sub)
        }
        if (-not $done) {
            Write-Log '  AVISO: no se pudo crear el admin interno. La provision de colecciones se saltea.' 'WARN'
        } else {
            Write-Log '  Admin interno OK' 'OK'
        }
    }

    # "assets" se CREA pero no se arranca.
    $upServices = @('worker')
    if ($script:Mode -eq 'local') { $upServices += 'pocketbase' }
    Write-Log "  Levantando: $($upServices -join ', ') ..."
    if (-not (Invoke-Logged 'docker' (@('compose', '-f', $ComposeFile) + $profileArgs + @('up', '-d') + $upServices))) {
        Fail 'docker compose up fallo.' "Ver $script:LogFile"
    }
    Write-Log '  Preparando asset server (on-demand, sin arrancar)...'
    if (-not (Invoke-Logged 'docker' (@('compose', '-f', $ComposeFile) + $profileArgs + @('create', 'assets')))) {
        Write-Log '  AVISO: no se pudo pre-crear el asset server.' 'WARN'
    }

    if ($script:Mode -eq 'local') {
        Write-Log '  Esperando a PocketBase...'
        if (-not (Wait-Until { (Get-ContainerHealth 'hyworld_pb') -eq 'healthy' } -TimeoutSec 90)) {
            Write-Log '  AVISO: PocketBase no llego a healthy. Provision de colecciones se saltea.' 'WARN'
        } else {
            Write-Log '  PocketBase: healthy' 'OK'
            Initialize-PocketBaseSchema
        }
    }
}

function Initialize-PocketBaseSchema {
    <# Crea las colecciones y sus API rules si no existen. Idempotente. #>
    Write-Log '  Provisionando colecciones...'
    $base = $script:PbUrlHost
    $auth = Invoke-RestMethod -Method Post -Uri "$base/api/collections/_superusers/auth-with-password" `
            -ContentType 'application/json' `
            -Body (@{ identity = $script:AdminMail; password = $script:AdminPass } | ConvertTo-Json)
    $hdr = @{ Authorization = $auth.token }

    $existing = @()
    try {
        $list = Invoke-RestMethod -Uri "$base/api/collections?perPage=200" -Headers $hdr
        $existing = @($list.items | ForEach-Object { $_.name })
    } catch { }

    if ($existing -notcontains $script:AuthCollection) {
        $body = @{
            name = $script:AuthCollection
            type = 'auth'
            fields = @(@{ name = 'name'; type = 'text' })
            listRule = '@request.auth.id = id'; viewRule = '@request.auth.id = id'
            createRule = ''; updateRule = '@request.auth.id = id'; deleteRule = $null
        } | ConvertTo-Json -Depth 6
        Invoke-RestMethod -Method Post -Uri "$base/api/collections" -Headers $hdr -ContentType 'application/json' -Body $body | Out-Null
        Write-Log "    $($script:AuthCollection): creada" 'OK'
    } else { Write-Log "    $($script:AuthCollection): ya existe" 'OK' }

    if ($existing -notcontains $script:DataCollection) {
        $body = @{
            name = $script:DataCollection
            type = 'base'
            fields = @(
                @{ name = 'json';  type = 'text' },
                @{ name = 'files'; type = 'file'; maxSelect = 99; maxSize = 524288000 }
            )
            listRule = ''; viewRule = ''
            createRule = '@request.auth.id != ""'
            updateRule = '@request.auth.id != ""'
            deleteRule = '@request.auth.id != ""'
        } | ConvertTo-Json -Depth 6
        Invoke-RestMethod -Method Post -Uri "$base/api/collections" -Headers $hdr -ContentType 'application/json' -Body $body | Out-Null
        Write-Log "    $($script:DataCollection): creada" 'OK'
    } else { Write-Log "    $($script:DataCollection): ya existe" 'OK' }

    $devMail = 'dev@hyworld.local'
    $devPass = ''
    if ($script:Cfg.ContainsKey('DEV_USER_PASSWORD')) { $devPass = $script:Cfg['DEV_USER_PASSWORD'] }
    if ([string]::IsNullOrWhiteSpace($devPass)) { $devPass = New-Secret 16 }
    try {
        $body = @{ email = $devMail; password = $devPass; passwordConfirm = $devPass; verified = $true } | ConvertTo-Json
        Invoke-RestMethod -Method Post -Uri "$base/api/collections/$($script:AuthCollection)/records" `
            -Headers $hdr -ContentType 'application/json' -Body $body | Out-Null
        Write-Log "    usuario dev creado: $devMail" 'OK'
    } catch {
        try {
            $rec = Invoke-RestMethod -Uri "$base/api/collections/$($script:AuthCollection)/records?filter=(email='$devMail')" -Headers $hdr
            if ($rec.items.Count -gt 0) {
                $body = @{ password = $devPass; passwordConfirm = $devPass } | ConvertTo-Json
                Invoke-RestMethod -Method Patch -Uri "$base/api/collections/$($script:AuthCollection)/records/$($rec.items[0].id)" `
                    -Headers $hdr -ContentType 'application/json' -Body $body | Out-Null
            }
        } catch { Write-Log '    AVISO: no se pudo asegurar el usuario dev.' 'WARN' }
    }
    Set-EnvValue $RootEnv 'DEV_USER_EMAIL' $devMail
    Set-EnvValue $RootEnv 'DEV_USER_PASSWORD' $devPass
    $script:DevMail = $devMail
    $script:DevPass = $devPass

    try {
        $body = @{ email = $script:WorkerMail; password = $script:WorkerPass; passwordConfirm = $script:WorkerPass; verified = $true } | ConvertTo-Json
        Invoke-RestMethod -Method Post -Uri "$base/api/collections/$($script:AuthCollection)/records" `
            -Headers $hdr -ContentType 'application/json' -Body $body | Out-Null
        Write-Log "    usuario worker creado: $($script:WorkerMail)" 'OK'
    } catch {
        try {
            $rec = Invoke-RestMethod -Uri "$base/api/collections/$($script:AuthCollection)/records?filter=(email='$($script:WorkerMail)')" -Headers $hdr
            if ($rec.items.Count -gt 0) {
                $body = @{ password = $script:WorkerPass; passwordConfirm = $script:WorkerPass } | ConvertTo-Json
                Invoke-RestMethod -Method Patch -Uri "$base/api/collections/$($script:AuthCollection)/records/$($rec.items[0].id)" `
                    -Headers $hdr -ContentType 'application/json' -Body $body | Out-Null
                Write-Log "    usuario worker actualizado: $($script:WorkerMail)" 'OK'
            }
        } catch { Write-Log '    AVISO: no se pudo asegurar el usuario worker.' 'WARN' }
    }
}

# =================================================================
#  FASE 7 — Frontend
# =================================================================
function Start-Frontend {
    Write-Log 'FASE 7/8 — Frontend' 'STEP'
    $fe = Join-Path $Repo 'frontend'
    if (-not (Test-Path (Join-Path $fe 'node_modules'))) {
        Write-Log '  Instalando dependencias (pnpm install)...'
        Push-Location $fe
        try {
            if (-not (Invoke-Logged 'pnpm' @('install'))) { Fail 'pnpm install fallo.' "Ver $script:LogFile" }
        } finally { Pop-Location }
    }
    # En modo local el frontend tiene que pegarle al PocketBase de :8092
    Set-Content -Path (Join-Path $fe '.env.local') -Encoding utf8 -Value @(
        '# Generado por preflight.ps1 - NO editar a mano.',
        "VITE_PB_URL=$($script:PbUrlHost)"
    )
    Write-Log "  PocketBase del frontend: $($script:PbUrlHost)" 'OK'
    # Sin ventana de cmd: Vite corre oculto y su salida va a un log.
    $viteLog = Join-Path $script:DataDir 'logs\vite.log'
    Write-Log '  Iniciando Vite en http://localhost:5173 ...'
    Start-Process -FilePath 'cmd.exe' `
        -ArgumentList '/c', "cd /d `"$fe`" && pnpm run dev > `"$viteLog`" 2>&1" `
        -WindowStyle Hidden | Out-Null
    Write-Log "  Log del frontend: $viteLog"
}

# =================================================================
#  FASE 8 — Validacion real en localhost
# =================================================================
function Test-Deployment {
    Write-Log 'FASE 8/8 — Validando el proyecto en localhost' 'STEP'
    $results = @()
    function Add-Check { param([string]$Name, [bool]$Ok, [string]$Detail)
        $script:AllOk = $script:AllOk -and $Ok
        $mark = if ($Ok) { 'OK  ' } else { 'FALLA' }
        $lvl  = if ($Ok) { 'OK' } else { 'ERROR' }
        Write-Log ("  [{0}] {1}{2}" -f $mark, $Name, $(if ($Detail) { " - $Detail" } else { '' })) $lvl
        $script:Results += [pscustomobject]@{ Name = $Name; Ok = $Ok; Detail = $Detail }
    }
    $script:AllOk = $true
    $script:Results = @()

    if (-not $Web) {
        # 1. Worker healthy de verdad (antes solo se miraba "Up")
        $ok = Wait-Until { (Get-ContainerHealth 'hyworld_ml') -eq 'healthy' } -TimeoutSec 180 -IntervalSec 5
        Add-Check 'Contenedor worker healthy' $ok (Get-ContainerHealth 'hyworld_ml')

        # 2. GPU visible DENTRO del contenedor
        $gpu = (& docker exec hyworld_ml python3.11 -c "import torch;print(torch.cuda.get_device_name(0))" 2>&1 | Select-Object -Last 1)
        Add-Check 'GPU dentro del worker' ($LASTEXITCODE -eq 0) "$gpu"

        # 3. Asset server: on-demand, asi que solo verificamos que exista
        #    listo para arrancar. Lo enciende el worker al primer pedido.
        $st = Get-ContainerHealth 'hyworld_assets'
        Add-Check 'Asset server preparado (on-demand)' ($st -ne 'missing') "estado: $st"

        # 3b. El worker puede hablar con Docker para encenderlo
        & docker exec hyworld_ml python3.11 -c "import docker; docker.from_env().ping()" *> $null
        Add-Check 'Worker puede encender el asset server' ($LASTEXITCODE -eq 0) 'socket de Docker'

        # 4. El worker se autentico contra PocketBase
        $logs = (& docker logs --tail 200 hyworld_ml 2>&1) -join "`n"
        $authOk = $logs -match 'autenticado como'
        $detail = if ($authOk) { $script:WorkerMail } else { 'sin login en los logs del worker' }
        Add-Check 'Worker autenticado en PocketBase' $authOk $detail
    }

    # 5. PocketBase responde
    $pbOk = $false; $pbDetail = ''
    try {
        $r = Invoke-WebRequest -Uri "$($script:PbUrlHost)/api/health" -UseBasicParsing -TimeoutSec 10
        $pbOk = ($r.StatusCode -eq 200); $pbDetail = $script:PbUrlHost
    } catch { $pbDetail = $_.Exception.Message }
    Add-Check 'PocketBase responde' $pbOk $pbDetail

    # 6. Vite sirviendo la app (no solo "el puerto abre")
    $viteOk = $false; $viteDetail = ''
    $viteOk = Wait-Until {
        try {
            $r = Invoke-WebRequest -Uri 'http://localhost:5173' -UseBasicParsing -TimeoutSec 5
            return ($r.StatusCode -eq 200 -and $r.Content -match 'id="root"')
        } catch { return $false }
    } -TimeoutSec 90 -IntervalSec 3
    if (-not $viteOk) { $viteDetail = 'no devolvio el HTML de la app' }
    Add-Check 'Frontend en :5173' $viteOk $viteDetail

    return $script:AllOk
}

# =================================================================
#  MAIN
# =================================================================
Write-Host ''
Write-Host '==========================================' -ForegroundColor Cyan
Write-Host ' HYWorld - Start' -ForegroundColor Cyan
Write-Host '==========================================' -ForegroundColor Cyan

Test-Prerequisites
Initialize-Config
Write-Log "Repo: $Repo"

# Siempre se para lo anterior antes de arrancar: evita puertos ocupados y
# contenedores de una corrida vieja mezclados con la nueva.
Write-Log 'FASE 0 — Deteniendo lo anterior' 'STEP'
& (Join-Path $ScriptDir 'stop.ps1') -Quiet
Write-Log '  Entorno limpio' 'OK'

if (-not $Web) {
    Sync-Repos
    Write-ComposeEnv
    Build-Images
    Start-Containers
} else {
    Write-ComposeEnv
    Write-Log 'Modo --Web: contenedores sin tocar.' 'WARN'
}

Start-Frontend
$ok = Test-Deployment

Write-Host ''
if ($ok) {
    Write-Log '==========================================' 'OK'
    Write-Log ' TODO OK - el proyecto responde en localhost' 'OK'
    Write-Log '==========================================' 'OK'
    Write-Log "  Web        : http://localhost:5173"
    Write-Log "  PocketBase : $($script:PbUrlHost)"
    if ($script:Mode -eq 'local' -and $script:DevMail) {
        Write-Log "  Usuario dev: $($script:DevMail) / $($script:DevPass)"
        Write-Log "               (guardado en $RootEnv)"
    }
    if (-not $Web) {
        Write-Log '  Logs del worker: en Docker Desktop (contenedor hyworld_ml)'
    }
    if (-not $NoBrowser) { Start-Process 'http://localhost:5173' }
    exit 0
} else {
    Write-Log '==========================================' 'ERROR'
    Write-Log ' HAY CHEQUEOS EN FALLA - no abro el navegador' 'ERROR'
    Write-Log '==========================================' 'ERROR'
    foreach ($r in $script:Results | Where-Object { -not $_.Ok }) {
        Write-Log "  x $($r.Name): $($r.Detail)" 'ERROR'
    }
    Write-Log "  Log: $script:LogFile" 'WARN'
    Write-Log '  Diagnostico: docker compose -f scripts\docker-compose.yml logs' 'WARN'
    Write-Host ''
    Read-Host 'Enter para cerrar'
    exit 1
}
