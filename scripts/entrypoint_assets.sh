#!/bin/bash
# ============================================================
# HYWorld — Asset Server (Hunyuan3D-2) entrypoint
#
# El codigo viene montado desde el host en /data/Hunyuan3D-2, asi que
# las dependencias se instalan en runtime (no en el build) y solo cuando
# requirements.txt cambia — el hash queda en /data/.assets_deps_hash.
# ============================================================

set -e

DATA="/data"
HY3D="$DATA/Hunyuan3D-2"
LOGS_DIR="$DATA/logs"
SAVE_DIR="${HY3D_SAVE_DIR:-$DATA/projects/asset_cache}"
MODELS_DIR="${MODELS_DIR:-$DATA/models}"
STAMP="$DATA/.assets_deps_hash"

export HF_HOME="$MODELS_DIR"
export HUGGINGFACE_HUB_CACHE="$MODELS_DIR/hub"
# Limpieza defensiva: el proyecto no usa autenticacion de HuggingFace.
unset HF_TOKEN HUGGING_FACE_HUB_TOKEN

mkdir -p "$LOGS_DIR" "$SAVE_DIR" "$MODELS_DIR"

echo "============================================================"
echo " HYWorld — Asset Server (Hunyuan3D-2)"
echo " Codigo   : $HY3D"
echo " Salida   : $SAVE_DIR"
echo " Modelos  : $MODELS_DIR"
echo "============================================================"

if [ ! -f "$HY3D/api_server.py" ]; then
    echo "[Assets] ERROR: no encuentro $HY3D/api_server.py"
    echo "[Assets] preflight.ps1 deberia haber clonado el repo ahi."
    tail -f /dev/null
fi

# ── Dependencias: solo si cambio requirements.txt ──────────
REQ="$HY3D/requirements.txt"
NEW_HASH=""
[ -f "$REQ" ] && NEW_HASH="$(md5sum "$REQ" | cut -d' ' -f1)"
OLD_HASH=""
[ -f "$STAMP" ] && OLD_HASH="$(cat "$STAMP")"

if [ -n "$NEW_HASH" ] && [ "$NEW_HASH" != "$OLD_HASH" ]; then
    echo "[Assets] requirements.txt cambio - instalando dependencias..."
    # --no-deps en el paquete propio: las deps pesadas (torch) ya estan
    # en la imagen base y no queremos que pip las reemplace.
    pip install --no-cache-dir -r "$REQ" || echo "[Assets] AVISO: fallos en requirements.txt"
    pip install --no-cache-dir -e "$HY3D" --no-deps || true
    echo "$NEW_HASH" > "$STAMP"
    echo "[Assets] Dependencias OK"
else
    echo "[Assets] Dependencias OK (sin cambios)"
fi

# ── Extensiones compiladas para el pipeline de texturas ────
# Solo hacen falta con --enable_tex. Si fallan, el server igual levanta
# y sirve geometria.
python3.11 -c "import custom_rasterizer" 2>/dev/null || {
    echo "[Assets] Compilando custom_rasterizer..."
    ( cd "$HY3D/hy3dgen/texgen/custom_rasterizer" && python3.11 setup.py install ) \
        || echo "[Assets] AVISO: custom_rasterizer no compilo - texturas degradadas"
}
if [ -d "$HY3D/hy3dgen/texgen/differentiable_renderer" ]; then
    python3.11 -c "import mesh_processor" 2>/dev/null || {
        echo "[Assets] Compilando differentiable_renderer..."
        ( cd "$HY3D/hy3dgen/texgen/differentiable_renderer" && python3.11 setup.py install ) \
            || echo "[Assets] AVISO: differentiable_renderer no compilo"
    }
fi

# ── Arrancar ───────────────────────────────────────────────
cd "$HY3D"
echo "[Assets] Iniciando api_server en 0.0.0.0:8081 ..."
exec python3.11 -u api_server.py --host 0.0.0.0 --port 8081 --enable_tex
