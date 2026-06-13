#!/usr/bin/env python
"""
HYWorld ML Worker — v4
Full pipeline: HY-Pano 2.0 → multi-view extraction → WorldMirror 2.0 → GLB → PocketBase

Flujo por proyecto:
  1. Download input image from PocketBase (preserve original filename)
  2. HY-Pano 2.0: single image → 360° equirectangular panorama
  3. Extract 9 equiangular perspective views from panorama
  4. WorldMirror 2.0: multi-view → 3D reconstruction (PLY + GLB)
  5. Upload output to PocketBase (preserve filenames at every stage)
  6. Mark completed

FIXES v4 (over v3):
  - GLB generado desde points.ply via trimesh (sin re-inferencia CUDA)
    Root cause v3: export_glb_mesh re-ejecutaba inferencia porque
    predictions_best.pt nunca existe → CUDA CachingAllocator crash
  - Logging deduplicado: detecta Docker y omite FileHandler si el
    entrypoint.sh ya redirige stdout al log (evita líneas duplicadas)

Start: python scripts/worker.py
"""

import os
import sys
import json
import time
import glob
import shutil
import platform
import traceback
import logging
import math
import random
import base64
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

import requests

# ── Paths ──────────────────────────────────────────────────────────────
SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR     = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
PROJECTS_DIR = os.environ.get("PROJECTS_DIR", os.path.join(ROOT_DIR, "projects"))
LOGS_DIR     = os.environ.get("LOGS_DIR", os.path.join(ROOT_DIR, "logs"))
HYWORLD_DIR  = os.environ.get("HYWORLD_DIR", r"D:\GitHub\HY-World-2.0")

os.makedirs(PROJECTS_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

# ── .env loading ─────────────────────────────────────────────────────────
ENV_FILE = os.path.join(ROOT_DIR, ".env")
if os.path.exists(ENV_FILE):
    for line in open(ENV_FILE, encoding="utf-8"):
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

# CRITICAL: hunyuan_image_3 lives inside hyworld2/panogen/ — add both
# HYWORLD_DIR (for `import hyworld2`) and the panogen dir (for
# `from hunyuan_image_3 import` inside pipeline.py).
_PANOGEN = os.path.join(HYWORLD_DIR, "hyworld2", "panogen")
if HYWORLD_DIR not in sys.path:
    sys.path.insert(0, HYWORLD_DIR)
if _PANOGEN not in sys.path:
    sys.path.insert(0, _PANOGEN)

PB_URL         = os.environ.get("PB_URL", "https://pocketbase.vmoliver.cloud").strip().rstrip("/")
PB_ADMIN_TOKEN = os.environ.get("PB_ADMIN_TOKEN", "").strip()
COLLECTION     = os.environ.get("PB_DATA_COLLECTION", "hyworld_data").strip()
POLL_INTERVAL  = 10  # segundos (hardcodeado)
ASSET_SERVER   = os.environ.get("ASSET_SERVER_URL", "http://host.docker.internal:8081")

# Global pipeline instances (loaded once, reused)
_PIPELINE_HYPOANO = None   # HunyuanPanoPipeline (loaded on demand)
_PIPELINE_WORLD   = None   # WorldMirrorPipeline  (loaded once in run_ml)

# ── Logging ──────────────────────────────────────────────────────────────
log_file = os.path.join(LOGS_DIR, "worker_" + datetime.now().strftime("%Y%m%d") + ".log")

class _Fmt(logging.Formatter):
    def format(self, record):
        ts = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
        return "{} [{:<4}] {}".format(ts, record.levelname[:4], record.getMessage())

log = logging.getLogger("worker")
log.setLevel(logging.DEBUG)
_sh = logging.StreamHandler(sys.stdout); _sh.setLevel(logging.DEBUG); _sh.setFormatter(_Fmt())
# Solo agregar FileHandler si el entrypoint NO está redirigiendo stdout al log.
# En Docker, entrypoint.sh ya hace `exec > >(tee -a "$LOG_FILE")`, por lo que
# agregar otro FileHandler al mismo archivo causaría que cada línea aparezca dos veces.
_IN_DOCKER = os.path.exists("/.dockerenv") or os.environ.get("HYWORLD_DIR", "").startswith("/c/")
if not _IN_DOCKER:
    _fh = logging.FileHandler(log_file, encoding="utf-8"); _fh.setLevel(logging.DEBUG); _fh.setFormatter(_Fmt())
    log.handlers = [_fh, _sh]
else:
    log.handlers = [_sh]

dbg_file = os.path.join(LOGS_DIR, "debug_" + datetime.now().strftime("%Y%m%d") + ".log")
dbg = logging.getLogger("debug")
dbg.setLevel(logging.DEBUG)
_dh = logging.FileHandler(dbg_file, encoding="utf-8"); _dh.setFormatter(_Fmt())
dbg.handlers = [_dh]


def dump_record(rid, tag):
    try:
        rec = pb_get("/api/collections/%s/records/%s" % (COLLECTION, rid))
        files = rec.get("files", []) or []
        raw = rec.get("json")
        dbg.info("[%s] id=%s files(%d)=%s json=%s" % (tag, rid, len(files), files, raw))
    except Exception as e:
        dbg.warning("[%s] id=%s no se pudo leer record: %s" % (tag, rid, e))


# ── Log cleanup: delete log files older than MAX_LOG_AGE_DAYS ─────────────
MAX_LOG_AGE_DAYS = 2

def _cleanup_old_logs():
    """Borra archivos de log en LOGS_DIR que tengan más de MAX_LOG_AGE_DAYS días.
    Preserva el log del día actual. Esto evita que los logs crezcan indefinidamente
    y garantiza tener siempre al menos 2 días de historial para debugging."""
    try:
        if not os.path.isdir(LOGS_DIR):
            return
        now = time.time()
        cutoff = now - (MAX_LOG_AGE_DAYS * 86400)
        removed = 0
        for fname in os.listdir(LOGS_DIR):
            fpath = os.path.join(LOGS_DIR, fname)
            if not os.path.isfile(fpath):
                continue
            # Only touch known log file patterns
            base = os.path.splitext(fname)[0]
            if not any(pattern in base for pattern in ("worker", "debug", "asset_server")):
                continue
            try:
                mtime = os.path.getmtime(fpath)
            except Exception:
                continue
            if mtime < cutoff:
                try:
                    os.remove(fpath)
                    removed += 1
                    log.debug("  Limpieza logs: borrado %s (%.1f días)" % (fname, (now - mtime) / 86400))
                except Exception:
                    pass
        if removed:
            log.info("  Limpieza logs: %d archivo(s) de más de %d días eliminado(s)" % (removed, MAX_LOG_AGE_DAYS))
        else:
            log.debug("  Limpieza logs: ningún archivo antiguo")
    except Exception as e:
        log.debug("  Limpieza logs: no se pudo ejecutar: %s" % e)


# ── HuggingFace cache cleanup (on startup — remove *.incomplete garbage) ──
def _cleanup_hf_cache():
    """Borra archivos *.incomplete en el cache de HuggingFace para evitar
    que ocupen espacio inútilmente. Solo elimina los incompletos;
    los completos se preservan. Esto permite descargas limpias cuando
    una descarga anterior fue interrumpida.
    Usa HF_HOME si está definido (volumen persistente); si no, fallback al default."""
    try:
        hf_home = os.environ.get("HF_HOME") or os.environ.get("HUGGINGFACE_HUB_CACHE")
        if hf_home:
            hf_base = os.path.join(hf_home, "hub") if not hf_home.endswith("hub") else hf_home
        else:
            hf_base = os.path.expanduser(os.path.join("~", ".cache", "huggingface", "hub"))
        if not os.path.isdir(hf_base):
            return
        removed = 0
        for root, _dirs, files in os.walk(hf_base):
            for f in files:
                if f.endswith(".incomplete") or f.endswith(".lock"):
                    try:
                        path = os.path.join(root, f)
                        size = os.path.getsize(path) / 1e9
                        os.remove(path)
                        removed += 1
                        log.debug("  Limpieza: borrado %s (%.1f GB)" % (f, size))
                    except Exception:
                        pass
        if removed:
            log.info("  Limpieza HuggingFace: %d archivo(s) incompleto(s) eliminado(s)" % removed)
        else:
            log.debug("  Limpieza HuggingFace: no habia archivos incompletos")
    except Exception as e:
        log.debug("  Limpieza HuggingFace: no se pudo ejecutar: %s" % e)


# ── Environment check ────────────────────────────────────────────────────
ML_READY = False
ML_REASON = "sin comprobar"

def check_ml_env():
    _cleanup_old_logs()  # Purge logs older than MAX_LOG_AGE_DAYS
    _cleanup_hf_cache()  # Always run cleanup on startup
    log.info("-" * 60)
    log.info("HYWorld ML Worker v3 (HY-Pano → multi-view → WorldMirror)")
    log.info("Python   : %s  (%s)" % (platform.python_version(), sys.executable))
    log.info("Platform : %s %s" % (platform.system(), platform.release()))
    log.info("PB URL   : %s" % PB_URL)
    log.info("PB token : %s" % ("OK" if PB_ADMIN_TOKEN else "FALTA"))
    log.info("Projects : %s" % PROJECTS_DIR)
    log.info("Poll     : cada %ss" % POLL_INTERVAL)
    try:
        import psutil
        vm = psutil.virtual_memory()
        log.info("RAM      : %.1f GB total | %.1f GB libre" % (vm.total / 1e9, vm.available / 1e9))
    except Exception:
        pass
    ok, reason = False, ""
    try:
        import torch
        cuda = torch.cuda.is_available()
        log.info("PyTorch  : %s | CUDA: %s" % (torch.__version__, cuda))
        if cuda:
            log.info("GPU      : %s" % torch.cuda.get_device_name(0))
        else:
            log.warning("CUDA no disponible")
    except Exception as e:
        reason = "torch no importable: %s" % e
        log.error("PyTorch  : %s" % reason)
        return False, reason
    if not os.path.isdir(HYWORLD_DIR):
        reason = "no existe %s" % HYWORLD_DIR
        log.error("hyworld2 : %s" % reason)
        return False, reason
    try:
        from hyworld2.worldrecon.pipeline import WorldMirrorPipeline
        log.info("hyworld2 : WorldMirrorPipeline importado OK")
        ok = True
    except Exception as e:
        reason = "no importable: %s" % e
        log.error("hyworld2 : %s" % reason)
    log.info("ML       : %s" % ("LISTO" if ok else "NO LISTO"))
    log.info("-" * 60)
    return ok, reason or "ok"


# ─────────────────────────────────────────────────────────────────────
# PocketBase helpers
# ─────────────────────────────────────────────────────────────────────
def _headers():
    return {"Authorization": "Bearer " + PB_ADMIN_TOKEN} if PB_ADMIN_TOKEN else {}

def pb_get(path, retries=3):
    for i in range(retries):
        try:
            r = requests.get(PB_URL + path, headers=_headers(), timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.warning("  GET %s intento %d/%d: %s" % (path, i+1, retries, e))
            if i == retries-1:
                raise
            time.sleep(2)

def pb_patch_json(record_id, data, retries=3):
    url = "%s/api/collections/%s/records/%s" % (PB_URL, COLLECTION, record_id)
    for i in range(retries):
        try:
            r = requests.patch(url, json=data, headers=_headers(), timeout=60)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.warning("  PATCH intento %d/%d: %s" % (i+1, retries, e))
            if i == retries-1:
                raise
            time.sleep(2)

def pb_get_record_by_slug(slug):
    """Busca record por slug. Devuelve (id, record) fresco desde PocketBase."""
    try:
        data = pb_get("/api/collections/%s/records?perPage=1&filter=json~'%s'" % (COLLECTION, slug))
        items = data.get("items", [])
        if items:
            return items[0]["id"], items[0]
        # Fallback: iterate
        data = pb_get("/api/collections/%s/records?perPage=200" % COLLECTION)
        for it in data.get("items", []):
            raw = it.get("json", {})
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw)
                except Exception:
                    raw = {}
            if raw.get("slug") == slug or it["id"] == slug:
                return it["id"], it
        return None, None
    except Exception as e:
        log.warning("  pb_get_record_by_slug(%s) ERROR: %s" % (slug, e))
        return None, None

def download_file(url, dest):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    for i in range(3):
        try:
            r = requests.get(url, headers=_headers(), timeout=120)
            r.raise_for_status()
            with open(dest, "wb") as f:
                f.write(r.content)
            log.debug("    descargado %s (%.2f MB)" % (os.path.basename(dest), len(r.content)/1e6))
            return True
        except Exception as e:
            log.warning("    descarga intento %d/3 %s: %s" % (i+1, url, e))
            time.sleep(3)
    log.error("    FALLO al descargar %s" % url)
    return False

def upload_output(record_id, filepath):
    fname = os.path.basename(filepath)
    url = "%s/api/collections/%s/records/%s" % (PB_URL, COLLECTION, record_id)
    for i in range(3):
        try:
            with open(filepath, "rb") as f:
                r = requests.patch(url, data={}, files={"files+": (fname, f)},
                                   headers=_headers(), timeout=300)
            if r.ok:
                log.info("    [%s] subido %s (%.2f MB)" % (record_id, fname, os.path.getsize(filepath)/1e6))
                return True
            log.warning("    [%s] subida intento %d: %s %s" % (record_id, i+1, r.status_code, r.text[:120]))
        except Exception as e:
            log.warning("    [%s] subida intento %d: %s" % (record_id, i+1, e))
        time.sleep(2)
    log.error("    [%s] FALLO al subir %s" % (record_id, fname))
    return False


# ─────────────────────────────────────────────────────────────────────
# File naming utilities — preserve original filename through ALL stages
# ─────────────────────────────────────────────────────────────────────
# PocketBase stores files with their original names. When we download to
# local, we use the same name (preserved in `files` array from record).
# At each stage (pano, multiview), we use the same base name + suffix.
#
# Example: original = "vacations.jpg"
#   input/   → projects/<slug>/input/vacations.jpg
#   pano/    → projects/<slug>/pano/vacations_pano.png
#   views/   → projects/<slug>/views/vacations_view_00.png ... _view_08.png
#   output/  → projects/<slug>/output/mesh.glb, gaussians.ply, etc.
#
# The original filename is extracted from the PocketBase `files` list,
# never invented or generated. This ensures uploads match expected names.

IMG_EXT = (".jpg", ".jpeg", ".png", ".webp")
PLY_EXT = (".ply",)

def get_original_image_name(files):
    """Return the original image filename from PocketBase files list.
    Excluye los panoramas generados (contienen "_pano" en el nombre)."""
    for f in files:
        if isinstance(f, str) and f.lower().endswith(IMG_EXT) and "_pano" not in f.lower():
            return f
    return None

def get_pano_filenames(files):
    """Filenames de panoramas ya subidos a PocketBase."""
    return [f for f in files
            if isinstance(f, str) and "_pano" in f.lower() and f.lower().endswith(IMG_EXT)]

def get_ply_filename(files):
    """Return the .ply filename from PocketBase files list, if any."""
    for f in files:
        if isinstance(f, str) and f.lower().endswith(PLY_EXT):
            return f
    return None

def input_path_for_slug(slug, orig_filename):
    """Local path: projects/<slug>/input/<orig_filename>"""
    return os.path.join(PROJECTS_DIR, slug, "input", orig_filename)

def pano_path_for_slug(slug, orig_filename_no_ext):
    """Local path: projects/<slug>/pano/<orig_filename_no_ext>_pano.png"""
    return os.path.join(PROJECTS_DIR, slug, "pano", orig_filename_no_ext + "_pano.png")

def view_path_for_slug(slug, orig_filename_no_ext, view_index):
    """Local path: projects/<slug>/views/<orig_filename_no_ext>_view_XX.png"""
    return os.path.join(PROJECTS_DIR, slug, "views",
                        orig_filename_no_ext + "_view_%02d.png" % view_index)

def ensure_dir(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)


def prepare_front_view(slug, orig_filename):
    """Modo 'solo frente': copia la imagen de entrada como vista unica en views/.
    Devuelve la lista [view_path] o None si falla. Esto permite que run_ml()
    (que siempre lee de projects/<slug>/views) funcione sin panorama."""
    input_file = input_path_for_slug(slug, orig_filename)
    if not os.path.exists(input_file) or os.path.getsize(input_file) == 0:
        log.error("  [%s] front: input no existe %s" % (slug, input_file))
        return None
    base_name = os.path.splitext(orig_filename)[0]
    view_path = view_path_for_slug(slug, base_name, 0)
    ensure_dir(view_path)
    # Limpiar vistas previas (evita mezclar con un 360 anterior)
    views_dir = os.path.dirname(view_path)
    for old in glob.glob(os.path.join(views_dir, "*.png")) + glob.glob(os.path.join(views_dir, "*.jpg")):
        try:
            os.remove(old)
        except Exception:
            pass
    try:
        from PIL import Image
        img = Image.open(input_file).convert("RGB")
        img.save(view_path, "PNG")
        log.info("  [%s] front: vista unica -> %s" % (slug, view_path))
        return [view_path]
    except Exception as e:
        log.error("  [%s] front: no se pudo preparar vista: %s" % (slug, e))
        return None


def pano_is_valid(path):
    """True si el panorama existe, abre como imagen y es equirectangular (2:1).
    Detecta archivos corruptos o escrituras incompletas de corridas fallidas."""
    try:
        if not os.path.isfile(path) or os.path.getsize(path) == 0:
            return False
        from PIL import Image
        with Image.open(path) as im:
            im.verify()
        with Image.open(path) as im:
            w_, h_ = im.size
        return w_ >= 512 and abs(w_ - 2 * h_) <= 2
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────
# HY-Pano 2.0 — single image → 360° panorama
# ─────────────────────────────────────────────────────────────────────
def generate_panorama(slug, orig_filename):
    """Generate equirectangular panorama from single input image.

    Returns path to panorama PNG, or None if generation failed.

    Stages:
      1. Load HunyuanPanoPipeline (cached globally)
      2. Call pipeline with input image → panorama
      3. Save to projects/<slug>/pano/<orig_name>_pano.png

    If generation fails, returns None (caller falls back to original image).
    """
    global _PIPELINE_HYPOANO

    input_file = input_path_for_slug(slug, orig_filename)
    if not os.path.exists(input_file):
        log.error("  [%s] pano: input no existe %s" % (slug, input_file))
        return None

    base_name = os.path.splitext(orig_filename)[0]
    pano_path = pano_path_for_slug(slug, base_name)
    ensure_dir(pano_path)

    # Skip if already generated (solo si es valido; corrupto/incompleto se rehace)
    if os.path.exists(pano_path):
        if pano_is_valid(pano_path):
            log.info("  [%s] pano: ya existe (cache valido) -> %s" % (slug, pano_path))
            return pano_path
        log.warning("  [%s] pano: cache corrupto/incompleto — regenerando" % slug)
        try:
            os.remove(pano_path)
        except Exception:
            pass

    log.info("  [%s] pano: generando panorama..." % slug)
    log.info("  [%s] pano: input=%s" % (slug, input_file))

    try:
        from hyworld2.panogen.pipeline import HunyuanPanoPipeline
        log.info("  [%s] pano: HunyuanPanoPipeline importado OK" % slug)
    except Exception as e:
        log.error("  [%s] pano: no se pudo importar HunyuanPanoPipeline: %s" % (slug, e))
        return None

    if _PIPELINE_HYPOANO is None:
        log.info("  [%s] pano: cargando HY-Pano 2.0 (solo primera vez)..." % slug)
        try:
            _PIPELINE_HYPOANO = HunyuanPanoPipeline.from_pretrained(
                "tencent/HY-World-2.0",
                subfolder="HY-Pano-2.0",
            )
            log.info("  [%s] pano: HY-Pano 2.0 cargado OK" % slug)
        except Exception as e:
            log.error("  [%s] pano: FALLO al cargar HY-Pano: %s" % (slug, e))
            return None

    try:
        result = _PIPELINE_HYPOANO(
            image=input_file,
            height=1024,
            width=2048,
            diff_infer_steps=50,
            blend_width=32,
            verbose=2,
            seed=random.randint(0, 2**31),
        )
    except Exception as e:
        log.error("  [%s] pano: inference FALLO: %s\n%s" % (slug, e, traceback.format_exc()))
        return None

    try:
        if hasattr(result, "save"):
            result.save(pano_path)
        elif isinstance(result, object) and hasattr(result, "pano"):
            result.pano.save(pano_path)
        else:
            # result might be a PIL Image or tensor
            try:
                from PIL import Image
                if isinstance(result, Image.Image):
                    result.save(pano_path)
                elif hasattr(result, "detach"):
                    # tensor → PIL
                    arr = result.detach().cpu().float().clamp(0, 1).numpy()
                    if arr.ndim == 3:
                        import numpy as np
                        arr = (arr * 255).astype(np.uint8)
                        Image.fromarray(arr.transpose(1, 2, 0) if arr.shape[0] < arr.shape[2] else arr).save(pano_path)
                    else:
                        Image.fromarray(result).save(pano_path)
                else:
                    log.error("  [%s] pano: resultado inesperado tipo=%s" % (slug, type(result)))
                    return None
            except Exception as img_err:
                log.error("  [%s] pano: no se pudo guardar panorama: %s" % (slug, img_err))
                return None

        if pano_is_valid(pano_path):
            log.info("  [%s] pano: generado -> %s (%.2f MB)" % (
                slug, pano_path, os.path.getsize(pano_path)/1e6))
            return pano_path
        else:
            log.error("  [%s] pano: archivo no creado o invalido — descartado" % slug)
            try:
                os.remove(pano_path)
            except Exception:
                pass
            return None
    except Exception as e:
        log.error("  [%s] pano: error al guardar resultado: %s" % (slug, e))
        return None


# ─────────────────────────────────────────────────────────────────────
# Multi-view extraction from equirectangular panorama
# ─────────────────────────────────────────────────────────────────────
def extract_multiview_from_panorama(slug, orig_filename, n_views=9):
    """Extract N equiangular perspective views from an equirectangular panorama.

    Uses the equirectangular projection to sample N views with overlapping
    coverage. Each view is saved as a perspective PNG that WorldMirror can
    process directly.

    Returns list of view image paths, or None if extraction failed.

    View layout (n_views=9):
      - Center: 1 view at azimuth=0°, elev=0°
      - Ring 1: 4 views at 45°, 135°, 225°, 315° (elev=0°)
      - Ring 2: 4 views at 45°, 135°, 225°, 315° (elev=±30°)
    """
    base_name = os.path.splitext(orig_filename)[0]
    pano_path = pano_path_for_slug(slug, base_name)

    if not os.path.exists(pano_path):
        log.error("  [%s] multiview: panorama no existe %s" % (slug, pano_path))
        return None

    views_dir = os.path.join(PROJECTS_DIR, slug, "views")
    os.makedirs(views_dir, exist_ok=True)

    # Check cache
    view_paths = [view_path_for_slug(slug, base_name, i) for i in range(n_views)]
    cached = all(os.path.exists(p) and os.path.getsize(p) > 0 for p in view_paths)
    if cached:
        log.info("  [%s] multiview: %d views ya cacheadas" % (slug, n_views))
        return view_paths

    log.info("  [%s] multiview: extrayendo %d views desde panorama..." % (slug, n_views))
    try:
        from PIL import Image
        import numpy as np
    except Exception as e:
        log.error("  [%s] multiview: PIL/numpy no disponible: %s" % (slug, e))
        return None

    try:
        pano = Image.open(pano_path)
        pano_w, pano_h = pano.size
        log.info("  [%s] multiview: panorama size=%dx%d" % (slug, pano_w, pano_h))
    except Exception as e:
        log.error("  [%s] multiview: no se pudo abrir panorama: %s" % (slug, e))
        return None

    VIEW_FOV = 60  # degrees, vertical FOV for each extracted view
    VIEW_W, VIEW_H = 1024, 1024

    def equirectangular_to_cartesian(azimuth_deg, elev_deg):
        """Convert azimuth/elevation (degrees) to direction unit vector."""
        az = math.radians(azimuth_deg)
        el = math.radians(elev_deg)
        x = math.cos(el) * math.sin(az)
        y = math.cos(el) * math.cos(az)
        z = math.sin(el)
        return np.array([x, y, z])

    pano_arr = np.array(pano.convert("RGB"))  # una sola conversion (no por pixel)

    def sample_perspective_from_pano(pano_img, azimuth_deg, elev_deg, fov_deg, out_w, out_h):
        """Sample a perspective view from equirectangular panorama (vectorizado).

        Returns PIL Image of the perspective projection."""
        # Camera basis
        cam_dir = equirectangular_to_cartesian(azimuth_deg, elev_deg)
        world_up = np.array([0, 0, 1])
        cam_right = np.cross(world_up, cam_dir)
        cam_right = cam_right / (np.linalg.norm(cam_right) + 1e-8)
        cam_up = np.cross(cam_dir, cam_right)

        # FOV -> focal
        fov_rad = math.radians(fov_deg)
        focal_px = (out_w / 2) / math.tan(fov_rad / 2)
        cx, cy = out_w // 2, out_h // 2

        # Rays para todos los pixeles a la vez
        xs, ys = np.meshgrid(np.arange(out_w), np.arange(out_h))
        dx = (xs - cx) / focal_px
        dy = (ys - cy) / focal_px
        ray = np.stack([dx, -dy, np.ones_like(dx, dtype=np.float64)], axis=-1)
        ray /= (np.linalg.norm(ray, axis=-1, keepdims=True) + 1e-8)

        ray_world = (ray[..., 0:1] * cam_right +
                     ray[..., 1:2] * cam_up +
                     ray[..., 2:3] * cam_dir)
        ray_world /= (np.linalg.norm(ray_world, axis=-1, keepdims=True) + 1e-8)

        # Direccion -> UV equirectangular
        az = np.arctan2(ray_world[..., 0], ray_world[..., 1])   # [-pi, pi]
        el = np.arcsin(np.clip(ray_world[..., 2], -1, 1))
        u = (az / (2 * math.pi) + 0.5) % 1.0
        v = (el / math.pi + 0.5)
        px_pano = (u * pano_w).astype(np.int64) % pano_w
        py_pano = np.clip((v * pano_h).astype(np.int64), 0, pano_h - 1)

        out = pano_arr[py_pano, px_pano]
        return Image.fromarray(out.astype(np.uint8))

    # View angles: cobertura horizontal uniforme, sin duplicados.
    # n_views=9 -> azimuts cada 40 grados (0, 40, ..., 320), elev 0.
    step = 360.0 / n_views
    view_angles = [(round(i * step), 0) for i in range(n_views)]

    for i, (az, el) in enumerate(view_angles):
        view_path = view_path_for_slug(slug, base_name, i)
        try:
            view_img = sample_perspective_from_pano(pano, az, el, VIEW_FOV, VIEW_W, VIEW_H)
            view_img.save(view_path, "PNG")
            log.debug("  [%s] multiview: view %d (az=%d°, el=%d°) -> %s" % (
                slug, i, az, el, view_path))
        except Exception as e:
            log.error("  [%s] multiview: view %d FALLO: %s" % (slug, i, e))
            return None

    log.info("  [%s] multiview: %d views extraidas" % (slug, len(view_angles)))
    return view_paths


# ─────────────────────────────────────────────────────────────────────
# WorldMirror 2.0 — multi-view → 3D reconstruction
# ─────────────────────────────────────────────────────────────────────
def run_ml(slug, settings=None, want_mesh=True):
    """Ejecuta WorldMirrorPipeline con las views extraidas.
    El output se guarda en projects/<slug>/output/."""
    views_dir = os.path.join(PROJECTS_DIR, slug, "views")
    output_dir = os.path.join(PROJECTS_DIR, slug, "output")
    os.makedirs(output_dir, exist_ok=True)

    views = sorted(glob.glob(os.path.join(views_dir, "*.png"))) + \
            sorted(glob.glob(os.path.join(views_dir, "*.jpg")))
    if not views:
        log.error("  [%s] run_ml: sin views en %s" % (slug, views_dir))
        return None

    global _PIPELINE_WORLD
    if _PIPELINE_WORLD is None:
        log.info("  [%s] run_ml: cargando WorldMirrorPipeline (solo la primera vez)..." % slug)
        from hyworld2.worldrecon.pipeline import WorldMirrorPipeline
        _PIPELINE_WORLD = WorldMirrorPipeline.from_pretrained(
            "tencent/HY-World-2.0", enable_bf16=True)
        log.info("  [%s] run_ml: WorldMirrorPipeline cacheado OK" % slug)

    ALLOWED = {
        "target_size", "max_resolution",
        "apply_sky_mask", "apply_edge_mask", "apply_confidence_mask",
        "save_gs", "save_points", "save_depth", "save_normal", "save_camera",
        "compress_pts", "compress_pts_max_points",
    }
    kwargs = {"strict_output_path": output_dir}
    for k, v in (settings or {}).items():
        if k in ALLOWED and v is not None:
            kwargs[k] = v
    # Alias del frontend: presets mandan max_points -> compress_pts_max_points
    if (settings or {}).get("max_points") is not None:
        kwargs["compress_pts_max_points"] = settings["max_points"]

    # Siempre guardar points.ply (necesario para generar GLB después)
    kwargs["save_points"] = True
    kwargs.setdefault("apply_sky_mask", True)
    kwargs.setdefault("apply_edge_mask", True)
    kwargs.setdefault("max_resolution", 2560)
    kwargs.setdefault("target_size", 1120)
    kwargs.setdefault("compress_pts_max_points", 4_000_000)

    log.info("  [%s] run_ml: %d views. Ajustes=%s" % (
        slug, len(views), {k: v for k, v in kwargs.items()
                           if k != "strict_output_path"}))

    try:
        result = _PIPELINE_WORLD(views_dir, **kwargs)
        if not result:
            log.error("  [%s] run_ml: pipeline devolvio None" % slug)
            return None
        log.info("  [%s] run_ml: pipeline completado -> %s" % (slug, result))
    except Exception as e:
        log.error("  [%s] run_ml: FALLO: %s\n%s" % (slug, e, traceback.format_exc()))
        return None

    if want_mesh:
        try:
            export_glb_from_ply(slug)
        except Exception as e:
            log.error("  [%s] mesh GLB FALLO: %s\n%s" % (slug, e, traceback.format_exc()))

    return output_dir


def export_glb_from_ply(slug):
    """Genera mesh.glb desde depth map + imagen de vista (malla 3D real con colores).
    Proyecta cada pixel del depth map al espacio 3D usando los intrinsecos de camara,
    conecta pixeles adyacentes con triangulos filtrando discontinuidades de profundidad.
    Sin CUDA, sin re-inferencia. Fallback: nube de puntos si faltan depth maps.
    """
    import numpy as np
    import trimesh
    import json

    output_dir = os.path.join(PROJECTS_DIR, slug, "output")
    views_dir  = os.path.join(PROJECTS_DIR, slug, "views")
    glb_path   = os.path.join(output_dir, "mesh.glb")

    # --- Buscar depth maps y vistas ---
    depth_files = sorted(glob.glob(os.path.join(output_dir, "depth", "depth_*.npy")))
    view_files  = sorted(glob.glob(os.path.join(views_dir, "*.png")) +
                         glob.glob(os.path.join(views_dir, "*.jpg")))
    cam_path    = os.path.join(output_dir, "camera_params.json")

    if not depth_files or not view_files or not os.path.exists(cam_path):
        log.warning("  [%s] glb: sin depth maps — fallback a nube de puntos" % slug)
        return _export_glb_pointcloud(slug, glb_path)

    try:
        with open(cam_path) as f:
            cam_data = json.load(f)
    except Exception as e:
        log.warning("  [%s] glb: camera_params.json no leible (%s) — fallback" % (slug, e))
        return _export_glb_pointcloud(slug, glb_path)

    log.info("  [%s] glb: reconstruyendo malla desde %d depth map(s)..." % (
        slug, len(depth_files)))

    try:
        from PIL import Image
    except ImportError:
        return _export_glb_pointcloud(slug, glb_path)

    all_verts  = []
    all_colors = []
    all_faces  = []
    total_verts = 0

    for i, (depth_path, view_path) in enumerate(zip(depth_files, view_files)):
        # Cargar depth (float32, en metros)
        depth = np.load(depth_path)
        if depth.ndim == 3:
            depth = depth[..., 0]
        depth = depth.astype(np.float32)

        # Submuestreo: step=2 → 4x menos vertices/triangulos, GLB ~7 MB vs 28 MB
        STEP = 2
        depth = depth[::STEP, ::STEP]

        img = np.array(Image.open(view_path).convert("RGB"))
        if img.shape[:2] != depth.shape:
            img = np.array(Image.fromarray(img).resize(
                (depth.shape[1], depth.shape[0]), Image.BILINEAR))

        H, W = depth.shape

        # Intrínsecos de cámara (ajustados al submuestreo)
        ci   = min(i, len(cam_data["intrinsics"]) - 1)
        intr = cam_data["intrinsics"][ci]["matrix"]
        fx, fy = float(intr[0][0]) / STEP, float(intr[1][1]) / STEP
        cx, cy = float(intr[0][2]) / STEP, float(intr[1][2]) / STEP

        # Extrinsecos (world-to-camera 4x4)
        ei   = min(i, len(cam_data["extrinsics"]) - 1)
        E    = np.array(cam_data["extrinsics"][ei]["matrix"], dtype=np.float64)
        R, t = E[:3, :3], E[:3, 3]
        # camera-to-world: p_world = R^T*(p_cam - t)
        Rt   = R.T

        # Desproyectar pixeles a espacio de camara
        ys, xs = np.mgrid[0:H, 0:W]
        Z = depth
        X = (xs - cx) * Z / fx
        Y = (ys - cy) * Z / fy

        # Transformar a espacio mundo (vectorizado)
        pts_cam = np.stack([X, Y, Z], axis=-1).reshape(-1, 3)
        pts_world = (pts_cam - t) @ Rt  # (N, 3)

        # Mascara de pixeles validos (profundidad en rango razonable)
        valid_2d = (Z > 0.05) & (Z < 100.0)
        valid_flat = valid_2d.ravel()

        # Mapa de indice de vertice por pixel
        idx_grid = np.full(H * W, -1, dtype=np.int32)
        idx_grid[valid_flat] = np.arange(int(valid_flat.sum()), dtype=np.int32) + total_verts
        idx_grid = idx_grid.reshape(H, W)

        # Crear triangulos vectorizado (quad → 2 triangulos por pixel)
        yy, xx = np.mgrid[0:H-1, 0:W-1]
        v00 = idx_grid[yy,   xx  ]
        v10 = idx_grid[yy+1, xx  ]
        v01 = idx_grid[yy,   xx+1]
        v11 = idx_grid[yy+1, xx+1]

        # Filtrar "flying triangles": descartar quads con salto de profundidad grande
        Z00 = Z[yy,   xx  ]
        Z10 = Z[yy+1, xx  ]
        Z01 = Z[yy,   xx+1]
        Z11 = Z[yy+1, xx+1]
        # Umbral: max 15% del valor de profundidad o 0.1m (el mayor)
        ref1  = np.maximum(np.maximum(Z00, Z10), Z01)
        thr1  = np.maximum(ref1 * 0.15, 0.1)
        ok1   = ((v00 >= 0) & (v10 >= 0) & (v01 >= 0) &
                 (np.abs(Z00-Z10) < thr1) & (np.abs(Z00-Z01) < thr1) & (np.abs(Z10-Z01) < thr1))
        ref2  = np.maximum(np.maximum(Z10, Z11), Z01)
        thr2  = np.maximum(ref2 * 0.15, 0.1)
        ok2   = ((v10 >= 0) & (v11 >= 0) & (v01 >= 0) &
                 (np.abs(Z10-Z11) < thr2) & (np.abs(Z10-Z01) < thr2) & (np.abs(Z11-Z01) < thr2))

        tri1 = np.stack([v00[ok1], v10[ok1], v01[ok1]], axis=1)
        tri2 = np.stack([v10[ok2], v11[ok2], v01[ok2]], axis=1)

        verts  = pts_world[valid_flat].astype(np.float32)
        colors = img.reshape(-1, 3)[valid_flat]

        all_verts.append(verts)
        all_colors.append(colors)
        if tri1.shape[0]: all_faces.append(tri1)
        if tri2.shape[0]: all_faces.append(tri2)
        total_verts += len(verts)

        log.info("  [%s] glb: vista %d → %d verts | %d tris" % (
            slug, i, len(verts), tri1.shape[0] + tri2.shape[0]))

    if not all_verts:
        log.error("  [%s] glb: sin vertices" % slug)
        return _export_glb_pointcloud(slug, glb_path)

    vertices = np.concatenate(all_verts)
    colors   = np.concatenate(all_colors)
    faces    = np.concatenate(all_faces) if all_faces else np.zeros((0, 3), dtype=np.int32)

    colors_rgba = np.concatenate(
        [colors, np.full((len(colors), 1), 255, dtype=np.uint8)], axis=1)

    try:
        mesh = trimesh.Trimesh(vertices=vertices, faces=faces,
                               vertex_colors=colors_rgba, process=False)
        mesh.export(glb_path)
    except Exception as e:
        log.error("  [%s] glb: export trimesh fallo: %s — fallback" % (slug, e))
        return _export_glb_pointcloud(slug, glb_path)

    if not os.path.exists(glb_path) or os.path.getsize(glb_path) == 0:
        return _export_glb_pointcloud(slug, glb_path)

    log.info("  [%s] glb: mesh.glb generado — %d verts | %d tris | %.2f MB" % (
        slug, len(vertices), len(faces), os.path.getsize(glb_path) / 1e6))
    return glb_path


def _export_glb_pointcloud(slug, glb_path):
    """Fallback: exporta points.ply como nube de puntos GLB."""
    import trimesh
    ply_path = os.path.join(PROJECTS_DIR, slug, "output", "points.ply")
    if not os.path.exists(ply_path):
        log.error("  [%s] glb: points.ply no existe" % slug)
        return None
    try:
        cloud = trimesh.load(ply_path, process=False)
        cloud.export(glb_path)
        log.info("  [%s] glb: fallback nube de puntos (%.2f MB)" % (
            slug, os.path.getsize(glb_path) / 1e6))
        return glb_path
    except Exception as e:
        log.error("  [%s] glb: fallback fallo: %s" % (slug, e))
        return None


# ─────────────────────────────────────────────────────────────────────
# PocketBase state management
# ─────────────────────────────────────────────────────────────────────
def set_status(rid, status):
    try:
        current = pb_get("/api/collections/%s/records/%s" % (COLLECTION, rid))
        parsed = current.get("json") or {}
        if isinstance(parsed, str):
            try:
                parsed = json.loads(parsed or "{}")
            except Exception:
                parsed = {}
        parsed["status"] = status
        if status == "processing":
            parsed.setdefault("started_at", datetime.now().isoformat())
        pb_patch_json(rid, {"json": parsed})
    except Exception as e:
        log.warning("  [%s] no se pudo fijar status=%s: %s" % (rid, status, e))

def set_json_fields(rid, **fields):
    """Mergea campos al json del record (lee fresco, escribe atomico)."""
    try:
        current = pb_get("/api/collections/%s/records/%s" % (COLLECTION, rid))
        parsed = current.get("json") or {}
        if isinstance(parsed, str):
            try:
                parsed = json.loads(parsed or "{}")
            except Exception:
                parsed = {}
        parsed.update(fields)
        pb_patch_json(rid, {"json": parsed})
        return True
    except Exception as e:
        log.warning("  [%s] set_json_fields%s: %s" % (rid, tuple(fields), e))
        return False


def sync_pano_to_pb(slug, rid, pano_path, force=False):
    """Sube el panorama a PocketBase apenas existe, para habilitar el visor 360
    en el frontend mientras el modelo 3D sigue generandose.
    - force=True (regenerate): reemplaza el pano anterior en PB.
    - marca json.pano_status='ready' + pano_at (el front lo detecta por nombre *_pano)."""
    try:
        current = pb_get("/api/collections/%s/records/%s" % (COLLECTION, rid))
        existing = get_pano_filenames(current.get("files", []) or [])
        if existing and not force:
            log.info("  [%s] pano: ya sincronizado en PB (%s)" % (slug, existing[0]))
            set_json_fields(rid, pano_status="ready")
            return True
        if existing:
            pb_patch_json(rid, {"files-": existing})
            log.info("  [%s] pano: %d pano(s) anterior(es) eliminado(s) de PB" % (slug, len(existing)))
        if not upload_output(rid, pano_path):
            set_json_fields(rid, pano_status="error")
            return False
        set_json_fields(rid, pano_status="ready", pano_at=datetime.now().isoformat())
        log.info("  [%s] pano: SINCRONIZADO -> visor 360 habilitado en frontend" % slug)
        return True
    except Exception as e:
        log.error("  [%s] pano: sync a PB fallo: %s" % (slug, e))
        return False


def delete_pb_outputs(rid):
    try:
        current = pb_get("/api/collections/%s/records/%s" % (COLLECTION, rid))
        files = current.get("files", []) or []
        remove = [f for f in files if str(f).lower().endswith((".ply", ".obj", ".glb", ".gltf", ".splat", ".pfm"))]
        dbg.info("[delete_outputs] id=%s remove=%s" % (rid, remove))
        if remove:
            pb_patch_json(rid, {"files-": remove})
            log.info("  [%s] %d output(s) viejo(s) eliminado(s)" % (rid, len(remove)))
            dump_record(rid, "after_delete_outputs")
    except Exception as e:
        log.error("  [%s] no se pudieron borrar outputs: %s" % (rid, e))


# ─────────────────────────────────────────────────────────────────────
# Output discovery
# ─────────────────────────────────────────────────────────────────────
OUT_EXT = (".ply", ".obj", ".glb", ".gltf", ".splat", ".pfm")

def list_outputs(out_dir):
    found = []
    for root, _dirs, files in os.walk(out_dir):
        for f in files:
            if f.lower().endswith(OUT_EXT):
                found.append(os.path.join(root, f))
    return sorted(found)

def mesh_glb_exists(slug):
    for name in ("mesh.glb", "asset.glb"):
        glb = os.path.join(PROJECTS_DIR, slug, "output", name)
        if os.path.isfile(glb) and os.path.getsize(glb) > 0:
            return True
    return False

def is_built(rec):
    if rec["status"] == "completed" and mesh_glb_exists(rec["slug"]):
        return True
    if rec["status"] == "completed":
        pb_has_glb = any(str(f).lower().endswith(".glb") for f in rec["files"])
        if pb_has_glb:
            return True
    return False


# ─────────────────────────────────────────────────────────────────────
# PLY → GLB direct conversion (sin ML, sin inferencia)
# ─────────────────────────────────────────────────────────────────────
def process_ply_input(slug, rid, ply_filename):
    """Descarga el .ply, lo convierte a .glb con trimesh y sube el resultado.
    No requiere GPU ni modelos — conversión directa de nube de puntos a mesh."""
    import trimesh

    input_file = os.path.join(PROJECTS_DIR, slug, "input", ply_filename)
    output_dir = os.path.join(PROJECTS_DIR, slug, "output")
    os.makedirs(os.path.join(PROJECTS_DIR, slug, "input"), exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)
    glb_path = os.path.join(output_dir, "mesh.glb")

    # Descargar .ply si no está cacheado
    if not os.path.exists(input_file) or os.path.getsize(input_file) == 0:
        url = "%s/api/files/%s/%s/%s" % (PB_URL, COLLECTION, rid, ply_filename)
        log.info("  [%s] ply: descargando %s..." % (slug, ply_filename))
        if not download_file(url, input_file):
            log.error("  [%s] ply: descarga fallida" % slug)
            return False
    else:
        log.info("  [%s] ply: cacheado -> %s" % (slug, input_file))

    log.info("  [%s] ply: convirtiendo a GLB..." % slug)
    try:
        mesh = trimesh.load(input_file, process=False)
        # Si es una escena con múltiples geometrías, combinar
        if isinstance(mesh, trimesh.Scene):
            mesh = mesh.to_mesh() if hasattr(mesh, 'to_mesh') else trimesh.util.concatenate(
                [g for g in mesh.geometry.values()])
        mesh.export(glb_path)
        size_mb = os.path.getsize(glb_path) / 1e6
        log.info("  [%s] ply: GLB generado -> %.2f MB" % (slug, size_mb))
        return True
    except Exception as e:
        log.error("  [%s] ply: conversion FALLO: %s\n%s" % (slug, e, traceback.format_exc()))
        return False


# ─────────────────────────────────────────────────────────────────────
# Asset processing — imagen → Hunyuan3D-2 → GLB
# ─────────────────────────────────────────────────────────────────────
ASSET_SERVER_MAX_WAIT = 600   # segundos (10 min) antes de timeout
ASSET_SERVER_POLL_SEC = 8     # intervalo de poll


def _asset_server_ready():
    """Retorna True si el asset server responde en /status/ping (o cualquier endpoint)."""
    try:
        r = requests.get(f"{ASSET_SERVER}/status/ping", timeout=5)
        return True   # 404 también cuenta — el server está up
    except Exception:
        return False


def process_asset(rec):
    """Pipeline asset: imagen en PocketBase → Hunyuan3D-2 → GLB → PocketBase."""
    slug = rec["slug"]
    orig_filename = get_original_image_name(rec["files"])

    if not orig_filename:
        log.warning("  [%s] asset: no se encontró imagen de entrada — SKIP" % slug)
        return

    rid, fresh_rec = pb_get_record_by_slug(slug)
    if not rid:
        log.warning("  [%s] asset: no encontrado en PocketBase — SKIP" % slug)
        return

    # ── Descargar imagen ──────────────────────────────────────────────
    input_file = input_path_for_slug(slug, orig_filename)
    if not os.path.exists(input_file) or os.path.getsize(input_file) == 0:
        url = "%s/api/files/%s/%s/%s" % (PB_URL, COLLECTION, rid, orig_filename)
        if not download_file(url, input_file):
            log.error("  [%s] asset: descarga de input FALLO" % slug)
            set_status(rid, "error")
            return
    else:
        log.info("  [%s] asset: input cacheado: %s" % (slug, input_file))

    # ── Verificar asset server disponible ────────────────────────────
    if not _asset_server_ready():
        log.warning("  [%s] asset: Asset Server no disponible en %s — SKIP" % (slug, ASSET_SERVER))
        return

    # ── Preparar payload ─────────────────────────────────────────────
    settings = rec.get("settings") or {}
    enable_tex = bool(settings.get("texture", False))

    with open(input_file, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()

    payload = {
        "image": img_b64,
        "texture": enable_tex,
        "type": "glb",
        "seed": 1234,
        "num_inference_steps": 5,
        "octree_resolution": 128,
        "guidance_scale": 5.0,
    }

    # ── Enviar al asset server (async) ───────────────────────────────
    set_status(rid, "processing")
    log.info("  [%s] asset: enviando a %s (texture=%s)..." % (slug, ASSET_SERVER, enable_tex))
    try:
        r = requests.post("%s/send" % ASSET_SERVER, json=payload, timeout=60)
        r.raise_for_status()
        uid = r.json()["uid"]
        log.info("  [%s] asset: uid=%s — esperando generación..." % (slug, uid))
    except Exception as e:
        log.error("  [%s] asset: error al enviar al server: %s" % (slug, e))
        set_status(rid, "error")
        return

    # ── Poll hasta completado ─────────────────────────────────────────
    waited = 0
    while waited < ASSET_SERVER_MAX_WAIT:
        time.sleep(ASSET_SERVER_POLL_SEC)
        waited += ASSET_SERVER_POLL_SEC
        try:
            sr = requests.get("%s/status/%s" % (ASSET_SERVER, uid), timeout=30)
            sr.raise_for_status()
            data = sr.json()
        except Exception as e:
            log.warning("  [%s] asset: poll error: %s" % (slug, e))
            continue

        status = data.get("status", "")
        if status == "processing":
            log.info("  [%s] asset: generando... (%ds)" % (slug, waited))
            continue
        elif status == "completed":
            log.info("  [%s] asset: completado en %ds" % (slug, waited))
            break
        else:
            log.error("  [%s] asset: estado inesperado: %s" % (slug, data))
            set_status(rid, "error")
            return
    else:
        log.error("  [%s] asset: timeout (%ds) esperando generación" % (slug, ASSET_SERVER_MAX_WAIT))
        set_status(rid, "error")
        return

    # ── Decodificar GLB y guardar localmente ─────────────────────────
    glb_b64 = data.get("model_base64")
    if not glb_b64:
        log.error("  [%s] asset: respuesta sin model_base64" % slug)
        set_status(rid, "error")
        return

    output_dir = os.path.join(PROJECTS_DIR, slug, "output")
    os.makedirs(output_dir, exist_ok=True)
    glb_path = os.path.join(output_dir, "asset.glb")

    try:
        with open(glb_path, "wb") as f:
            f.write(base64.b64decode(glb_b64))
        log.info("  [%s] asset: GLB guardado -> %.2f MB" % (slug, os.path.getsize(glb_path) / 1e6))
    except Exception as e:
        log.error("  [%s] asset: error al guardar GLB: %s" % (slug, e))
        set_status(rid, "error")
        return

    # ── Subir a PocketBase ────────────────────────────────────────────
    rid, _ = pb_get_record_by_slug(slug)
    if not rid:
        log.error("  [%s] asset: record no encontrado para upload" % slug)
        return
    delete_pb_outputs(rid)
    upload_output(rid, glb_path)

    # ── Marcar completed ──────────────────────────────────────────────
    rid, _ = pb_get_record_by_slug(slug)
    if rid:
        try:
            current = pb_get("/api/collections/%s/records/%s" % (COLLECTION, rid))
            parsed = current.get("json") or {}
            if isinstance(parsed, str):
                try:
                    parsed = json.loads(parsed)
                except Exception:
                    parsed = {}
            parsed["status"] = "completed"
            parsed["regenerate"] = False
            parsed["finished_at"] = datetime.now().isoformat()
            pb_patch_json(rid, {"json": parsed})
            log.info("  [%s] asset: marcado completed" % slug)
        except Exception as e:
            log.error("  [%s] asset: no se pudo marcar completed: %s" % (slug, e))


# ─────────────────────────────────────────────────────────────────────
# Process one project
# ─────────────────────────────────────────────────────────────────────
def process(rec):
    """Procesa un proyecto completo.
    - Si project_type='asset': imagen → Hunyuan3D-2 → GLB (asset 3D de objeto)
    - Si input_type='ply':     PLY → GLB directo (sin ML)
    - Si input_type='image':   HY-Pano → multiview → WorldMirror → GLB (espacio 3D)
    """
    slug = rec["slug"]

    # ── Rama Asset: Hunyuan3D-2 ───────────────────────────────────────
    project_type = rec.get("project_type", "space")
    if project_type == "asset":
        if is_built(rec) and not rec.get("regenerate", False):
            log.info("  [%s] asset YA construido — SKIP" % slug)
            return
        if not rec["listo"] and not rec.get("regenerate", False):
            log.info("  [%s] asset listo=OFF — esperando" % slug)
            return
        process_asset(rec)
        return

    input_type = rec.get("input_type", "image")
    ply_filename = get_ply_filename(rec["files"])
    orig_filename = get_original_image_name(rec["files"])

    # Detectar automaticamente por extension si input_type no esta seteado
    if not rec.get("input_type_explicit") and ply_filename and not orig_filename:
        input_type = "ply"

    log.info("[%s] process: listo=%s status=%s files=%d input_type=%s" % (
        slug, rec["listo"], rec["status"], len(rec["files"]), input_type))

    # Fresh record ID lookup
    rid, fresh_rec = pb_get_record_by_slug(slug)
    if not rid:
        log.warning("  [%s] no encontrado en PocketBase — SKIP" % slug)
        return

    # ── Rama PLY: conversión directa sin ML ──────────────────────────
    if input_type == "ply":
        if not ply_filename:
            log.warning("  [%s] input_type=ply pero no hay .ply en files — SKIP" % slug)
            return
        if is_built(rec) and not rec.get("regenerate", False):
            log.info("  [%s] YA construido — SKIP" % slug)
            return
        if not rec["listo"] and not rec.get("regenerate", False):
            log.info("  [%s] listo=OFF — esperando" % slug)
            return

        set_status(rid, "processing")
        ok = process_ply_input(slug, rid, ply_filename)
        if not ok:
            set_status(rid, "error")
            return

        # Upload GLB
        glb_path = os.path.join(PROJECTS_DIR, slug, "output", "mesh.glb")
        rid, _ = pb_get_record_by_slug(slug)
        if rid and os.path.exists(glb_path):
            delete_pb_outputs(rid)
            upload_output(rid, glb_path)
            # Mark completed
            try:
                current = pb_get("/api/collections/%s/records/%s" % (COLLECTION, rid))
                parsed = current.get("json") or {}
                if isinstance(parsed, str):
                    try: parsed = json.loads(parsed)
                    except: parsed = {}
                parsed["status"] = "completed"
                parsed["regenerate"] = False
                parsed["finished_at"] = datetime.now().isoformat()
                pb_patch_json(rid, {"json": parsed})
                log.info("  [%s] PLY→GLB completado" % slug)
            except Exception as e:
                log.error("  [%s] no se pudo marcar completed: %s" % (slug, e))
        return

    # ── Rama imagen: pipeline completo ───────────────────────────────
    if not orig_filename:
        log.warning("  [%s] no se encontro imagen de entrada — SKIP" % slug)
        return

    dump_record(rid, "process_start[%s]" % slug)

    # ── Download input ────────────────────────────────────────────────
    input_file = input_path_for_slug(slug, orig_filename)
    if not os.path.exists(input_file) or os.path.getsize(input_file) == 0:
        url = "%s/api/files/%s/%s/%s" % (PB_URL, COLLECTION, rid, orig_filename)
        if not download_file(url, input_file):
            log.error("  [%s] descarga de input FALLO — SKIP" % slug)
            return
    else:
        log.info("  [%s] input cacheado: %s" % (slug, input_file))

    force = rec.get("regenerate", False)

    # ── ML available? ─────────────────────────────────────────────────
    if not ML_READY:
        if force or (rec["listo"] and not is_built(rec)):
            log.warning("  [%s] ML no disponible (%s) — SKIP" % (slug, ML_REASON))
        return

    # ── Skip if already built ────────────────────────────────────────
    if is_built(rec) and not force:
        log.info("  [%s] YA construido — SKIP" % slug)
        return

    # ── Skip if not listo ─────────────────────────────────────────────
    if not force and not rec["listo"]:
        log.info("  [%s] listo=OFF — esperando" % slug)
        return

    log.info("  [%s] Iniciando pipeline completo (HY-Pano → WorldMirror)..." % slug)
    set_status(rid, "processing")

    # ── Modo de generacion: full_360 (default False) ─────────────────
    # full_360 = True  -> HY-Pano 360 + multiview (9 vistas) + GLB completo
    # full_360 = False -> solo imagen de frente (GLB rapido del frente)
    settings = rec.get("settings") or {}
    full_360 = bool(settings.get("full_360", False))
    log.info("  [%s] modo generacion: %s" % (slug, "360 COMPLETO" if full_360 else "SOLO FRENTE"))

    view_paths = None
    if full_360:
        # ── Step 1: HY-Pano 2.0 → panorama ────────────────────────────
        pano_path = generate_panorama(slug, orig_filename)
        if pano_path and pano_is_valid(pano_path):
            # ── Step 1b: subir pano a PB YA (habilita visor 360 en el front
            #    mientras WorldMirror genera el modelo 3D) ──────────────
            sync_pano_to_pb(slug, rid, pano_path, force=force)
            # ── Step 2: extract multiview from panorama ──────────────
            view_paths = extract_multiview_from_panorama(slug, orig_filename, n_views=9)
            if not view_paths:
                log.warning("  [%s] multiview falló — usando solo frente" % slug)
        else:
            log.warning("  [%s] HY-Pano no generó panorama — usando solo frente" % slug)
            set_json_fields(rid, pano_status="error")

    # ── Front-only: preparar imagen de frente como vista unica ────────
    # Se usa cuando full_360=False, o como fallback si el 360 falló.
    if not view_paths:
        view_paths = prepare_front_view(slug, orig_filename)
        if not view_paths:
            log.error("  [%s] no se pudo preparar entrada para WorldMirror" % slug)
            set_status(rid, "error")
            return

    # ── Step 3: WorldMirror 2.0 (siempre lee de projects/<slug>/views) ─
    output_dir = None
    try:
        output_dir = run_ml(slug, settings, want_mesh=True)
    except Exception as e:
        log.error("  [%s] ML FALLO: %s\n%s" % (slug, e, traceback.format_exc()))
        set_status(rid, "error")
        return

    if not output_dir:
        log.error("  [%s] pipeline sin output — error" % slug)
        set_status(rid, "error")
        return

    # ── Verify mesh.glb exists ─────────────────────────────────────────
    glb_path = os.path.join(output_dir, "mesh.glb")
    if not os.path.exists(glb_path) or os.path.getsize(glb_path) == 0:
        log.error("  [%s] mesh.glb no generado" % slug)
        set_status(rid, "error")
        return

    # ── Upload outputs to PocketBase (fresh ID) ─────────────────────────
    rid, _ = pb_get_record_by_slug(slug)
    if not rid:
        log.error("  [%s] no se encontro record para upload" % slug)
        return

    delete_pb_outputs(rid)
    outputs = list_outputs(output_dir)
    log.info("  [%s] %d archivo(s) de salida, subiendo..." % (slug, len(outputs)))
    for f in outputs:
        upload_output(rid, f)
    dump_record(rid, "after_uploads[%s]" % slug)

    # ── Mark completed (fresh ID) ──────────────────────────────────────
    rid, _ = pb_get_record_by_slug(slug)
    if rid:
        try:
            current = pb_get("/api/collections/%s/records/%s" % (COLLECTION, rid))
            parsed = current.get("json") or {}
            if isinstance(parsed, str):
                try:
                    parsed = json.loads(parsed or "{}")
                except Exception:
                    parsed = {}
            parsed["status"] = "completed"
            parsed["regenerate"] = False
            parsed["finished_at"] = datetime.now().isoformat()
            pb_patch_json(rid, {"json": parsed})
            log.info("  [%s] marcado completed" % slug)
            dump_record(rid, "after_completed[%s]" % slug)
        except Exception as e:
            log.error("  [%s] no se pudo marcar completed: %s" % (slug, e))


# ─────────────────────────────────────────────────────────────────────
# Parse records
# ─────────────────────────────────────────────────────────────────────
def parse_records(items):
    out = []
    for it in items:
        raw = it.get("json") or {}
        if isinstance(raw, str):
            try:
                raw = json.loads(raw or "{}")
            except Exception:
                raw = {}
        out.append({
            "id": it["id"],
            "slug": raw.get("slug", it["id"]),
            "name": raw.get("name", it["id"]),
            "listo": bool(raw.get("listo", False)),
            "status": raw.get("status", "pending"),
            "settings":      raw.get("settings", {}) or {},
            "regenerate":    bool(raw.get("regenerate", False)),
            "input_type":    raw.get("input_type") or "image",
            "input_type_explicit": bool(raw.get("input_type")),
            "project_type":  raw.get("project_type", "space"),
            "files":         it.get("files", []) or [],
        })
    return out


# ─────────────────────────────────────────────────────────────────────
# Reconciliation: orphan cleanup + 0-byte file cleanup
# ─────────────────────────────────────────────────────────────────────
def _clean_empty_files(folder):
    removed = 0
    if not os.path.isdir(folder):
        return 0
    for root, _d, files in os.walk(folder):
        for f in files:
            fp = os.path.join(root, f)
            try:
                if os.path.getsize(fp) == 0:
                    os.remove(fp); removed += 1
            except Exception:
                pass
    return removed

def reconcile(recs):
    """Sincroniza PocketBase con filesystem local.
    Borra carpetas huerfanas, limpia 0-bytes, auto-repara completed sin mesh."""
    valid  = {r["slug"] for r in recs}
    active = {r["slug"] for r in recs if r["listo"]}

    if recs and os.path.isdir(PROJECTS_DIR):
        now = time.time()
        for name in os.listdir(PROJECTS_DIR):
            path = os.path.join(PROJECTS_DIR, name)
            if not os.path.isdir(path) or name in valid:
                continue
            if name in active:
                continue
            try:
                age = now - os.path.getmtime(path)
            except Exception:
                age = 1e9
            if age < 600:
                log.debug("Reconcile: %s huerfana reciente (%.0fs) — conservada" % (name, age))
                continue
            try:
                shutil.rmtree(path, ignore_errors=True)
                log.info("Reconcile: borrada carpeta huerfana %s" % name)
            except Exception as e:
                log.warning("Reconcile: no se pudo borrar %s: %s" % (name, e))

    for r in recs:
        proj = os.path.join(PROJECTS_DIR, r["slug"])
        os.makedirs(os.path.join(proj, "input"),  exist_ok=True)
        os.makedirs(os.path.join(proj, "output"), exist_ok=True)
        os.makedirs(os.path.join(proj, "pano"),   exist_ok=True)
        os.makedirs(os.path.join(proj, "views"),  exist_ok=True)
        n = _clean_empty_files(proj)
        if n:
            log.info("Reconcile: [%s] %d archivo(s) 0-byte eliminados" % (r["slug"], n))

        # Auto-repair: completed sin mesh → pending
        if r["status"] == "completed" and not mesh_glb_exists(r["slug"]):
            pb_has_glb = any(str(f).lower().endswith(".glb") for f in r["files"])
            if not pb_has_glb:
                rid, _ = pb_get_record_by_slug(r["slug"])
                if rid:
                    set_status(rid, "pending")
                    log.info("Reconcile: [%s] completed sin mesh → pending" % r["slug"])


# ─────────────────────────────────────────────────────────────────────
# Main loop
# ─────────────────────────────────────────────────────────────────────
def main():
    global ML_READY, ML_REASON
    ML_READY, ML_REASON = check_ml_env()

    cycle = 0
    while True:
        cycle += 1
        t0 = time.time()
        log.info("--- ciclo %d | %s ---" % (cycle, datetime.now().strftime("%H:%M:%S")))
        try:
            data = pb_get("/api/collections/%s/records?perPage=200" % COLLECTION)
            items = data.get("items", [])
            recs  = parse_records(items)
            log.info("%d proyecto(s) en PocketBase" % len(recs))
            reconcile(recs)
            for rec in recs:
                try:
                    process(rec)
                except Exception as e:
                    log.error("process(%s) excepcion: %s\n%s" % (
                        rec.get("slug","?"), e, traceback.format_exc()))
        except Exception as e:
            log.error("ciclo %d error: %s" % (cycle, e))

        elapsed = time.time() - t0
        log.info("ciclo %d ok. durmiendo %ss..." % (cycle, POLL_INTERVAL))
        time.sleep(max(0, POLL_INTERVAL - elapsed))


if __name__ == "__main__":
    main()
