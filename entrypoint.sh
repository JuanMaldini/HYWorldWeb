#!/bin/bash
# ============================================================
# HYWorld — Entrypoint
# Levanta worker ML en background; mantiene contenedor vivo.
# ============================================================

set -e

WORKSPACE="/workspace"
HYWORLD_DATA="/c/HyWorldWebData"
PROJECTS_DIR="$HYWORLD_DATA/projects"
LOGS_DIR="$HYWORLD_DATA/logs"
MODELS_DIR="$HYWORLD_DATA/models"
ENV_FILE="$HYWORLD_DATA/.env"

# ── Crear estructura de carpetas ───────────────────────────
echo "[HYWorld] Init: creando estructura..."
mkdir -p "$PROJECTS_DIR" "$LOGS_DIR" "$MODELS_DIR"

# ── Cargar .env si existe ──────────────────────────────────
if [ -f "$ENV_FILE" ]; then
    echo "[HYWorld] Cargando variables desde $ENV_FILE"
    set -a
    source "$ENV_FILE"
    set +a
fi

# ── Validar GPU ────────────────────────────────────────────
echo "[HYWorld] Verificando GPU..."
python3.11 -c "
import torch
if not torch.cuda.is_available():
    raise RuntimeError('GPU NO DISPONIBLE — deteniendo')
print(f'GPU: {torch.cuda.get_device_name(0)}')
"

# ── Limpiar cache HuggingFace (archivos incompletos) ────────
HF_CACHE_ROOT="$HOME/.cache/huggingface/hub"
if [ -d "$HF_CACHE_ROOT" ]; then
    echo "[HYWorld] Limpiando archivos incompletos del cache HF..."
    find "$HF_CACHE_ROOT" -name "*.incomplete" -delete 2>/dev/null || true
    find "$HF_CACHE_ROOT" -name "*.lock" -delete 2>/dev/null || true
fi

# ── Paths (Git Bash style /c/) ────────────────────────────
export HYWORLD_DIR="/c/HyWorldWebData/repo"
export PROJECTS_DIR="/c/HyWorldWebData/projects"
export LOGS_DIR="/c/HyWorldWebData/logs"
export PYTHONPATH="/c/HyWorldWebData/repo/hyworld2/panogen:/c/HyWorldWebData/repo"

# ── Handover script ─────────────────────────────────────────
WORKER_WRAPPER="/workspace/scripts/run_worker_docker.py"
if [ ! -f "$WORKER_WRAPPER" ]; then
    echo "[HYWorld] ERROR: $WORKER_WRAPPER no existe"
    tail -f /dev/null
fi

# ── Directorio de trabajo ──────────────────────────────────
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
echo "============================================================"

# ── Verificar .env ─────────────────────────────────────────
if [ -z "$PB_URL" ] || [ -z "$PB_ADMIN_TOKEN" ]; then
    echo "[HYWorld] ERROR: PB_URL o PB_ADMIN_TOKEN no estan definidos"
    echo "[HYWorld] Edita C:/HyWorldWebData/.env y reinicia."
    tail -f /dev/null
fi

# ── Ejecutar worker via wrapper ────────────────────────────
echo "[HYWorld] Iniciando worker..."
exec python3.11 -u "$WORKER_WRAPPER"