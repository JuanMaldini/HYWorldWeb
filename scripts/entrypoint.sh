#!/bin/bash
# ============================================================
# HYWorld — Entrypoint
# Levanta el worker ML. Todo cuelga de /data (montado por compose
# desde HYWORLD_DATA): no hay rutas de Windows aca.
# ============================================================

set -e

DATA="/data"
PROJECTS_DIR="${PROJECTS_DIR:-$DATA/projects}"
LOGS_DIR="${LOGS_DIR:-$DATA/logs}"
MODELS_DIR="${MODELS_DIR:-$DATA/models}"
HYWORLD_DIR="${HYWORLD_DIR:-$DATA/repo}"

# HuggingFace -> volumen persistente (sin token: descargas anonimas).
export HF_HOME="$MODELS_DIR"
export HUGGINGFACE_HUB_CACHE="$MODELS_DIR/hub"
# Aun si la imagen base trae HF_TOKEN del entorno del builder, lo
# limpiamos: el proyecto no usa autenticacion de HuggingFace.
unset HF_TOKEN HUGGING_FACE_HUB_TOKEN
export HYWORLD_DIR PROJECTS_DIR LOGS_DIR
export PYTHONPATH="${PYTHONPATH:-$HYWORLD_DIR/hyworld2/panogen:$HYWORLD_DIR}"

# ── Crear estructura de carpetas ───────────────────────────
echo "[HYWorld] Init: creando estructura..."
mkdir -p "$PROJECTS_DIR" "$LOGS_DIR" "$MODELS_DIR"

# ── Validar GPU ────────────────────────────────────────────
echo "[HYWorld] Verificando GPU..."
python3.11 -c "
import torch
if not torch.cuda.is_available():
    raise RuntimeError('GPU NO DISPONIBLE - deteniendo')
print(f'GPU: {torch.cuda.get_device_name(0)}')
"

# ── Limpiar cache HuggingFace (archivos incompletos) ────────
HF_CACHE_ROOT="$HF_HOME/hub"
if [ -d "$HF_CACHE_ROOT" ]; then
    echo "[HYWorld] Limpiando archivos incompletos del cache HF..."
    find "$HF_CACHE_ROOT" -name "*.incomplete" -delete 2>/dev/null || true
    find "$HF_CACHE_ROOT" -name "*.lock" -delete 2>/dev/null || true
fi

# ── Handover script ─────────────────────────────────────────
WORKER_WRAPPER="/workspace/scripts/run_worker_docker.py"
if [ ! -f "$WORKER_WRAPPER" ]; then
    echo "[HYWorld] ERROR: $WORKER_WRAPPER no existe"
    tail -f /dev/null
fi

cd /workspace

# ── Logging ───────────────────────────────────────────────
LOG_FILE="$LOGS_DIR/worker_$(date +%Y%m%d).log"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "============================================================"
echo " HYWorld — Worker ML"
echo " Fecha    : $(date)"
echo " GPU      : $(python3.11 -c 'import torch; print(torch.cuda.get_device_name(0))')"
echo " Projects : $PROJECTS_DIR"
echo " Logs     : $LOG_FILE"
echo " Repo     : $HYWORLD_DIR"
echo " PB_URL   : ${PB_URL:-NO CONFIGURADO}"
echo " Modo     : ${HYWORLD_MODE:-desconocido}"
echo "============================================================"

# ── Verificar configuracion de PocketBase ──────────────────
# Ya no hay token estatico: el worker se autentica con una cuenta de
# servicio (email+password) y renueva su token solo. preflight.ps1
# garantiza que estas variables lleguen en ambos modos.
if [ -z "$PB_URL" ]; then
    echo "[HYWorld] ERROR: PB_URL no esta definido."
    echo "[HYWorld] Corre start.bat para regenerar la configuracion."
    tail -f /dev/null
fi
if [ -z "$PB_WORKER_EMAIL" ] || [ -z "$PB_WORKER_PASSWORD" ]; then
    echo "[HYWorld] ERROR: falta la cuenta del worker (PB_WORKER_EMAIL/PASSWORD)."
    echo "[HYWorld] start.bat las autogenera en scripts/.env."
    tail -f /dev/null
fi

# ── Ejecutar worker via wrapper ────────────────────────────
echo "[HYWorld] Iniciando worker..."
exec python3.11 -u "$WORKER_WRAPPER"
