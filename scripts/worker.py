#!/usr/bin/env python
"""
HYWorld ML Worker — v3
Full pipeline: HY-Pano 2.0 → multi-view extraction → WorldMirror 2.0 → GLB → PocketBase

Flujo por proyecto:
  1. Download input image from PocketBase (preserve original filename)
  2. HY-Pano 2.0: single image → 360° equirectangular panorama
  3. Extract 9 equiangular perspective views from panorama
  4. WorldMirror 2.0: multi-view → 3D reconstruction (PLY + GLB)
  5. Upload output to PocketBase (preserve filenames at every stage)
  6. Mark completed

FIXES v3 (over v2):
  - HY-Pano 2.0 integration (HunyuanPanoPipeline) before WorldMirror
  - Multi-view extraction from panorama (9 views with overlap)
  - Filename preservation: original file → projects/<slug>/input/<orig_name>
      → projects/<slug>/pano/<orig_name>_pano.png
      → projects/<slug>/multiview/<orig_name>_view_00.png ... _view_08.png
  - Fresh record ID lookup before every PocketBase operation
  - Graceful fallback: if HY-Pano fails, use original single image directly
  - is_built() requires mesh.glb (not just PLY) to mark completed
  - Never crash: ML errors are caught and logged, project marked error

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

PB_URL         = os.environ.get("PB_URL", "https://pocketbase.vmoliver.cloud").rstrip("/")
PB_ADMIN_TOKEN = os.environ.get("PB_ADMIN_TOKEN", "")
COLLECTION     = "hyworld_data"
POLL_INTERVAL  = int(os.environ.get("POLL_INTERVAL", "10"))

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
_fh = logging.FileHandler(log_file, encoding="utf-8"); _fh.setLevel(logging.DEBUG); _fh.setFormatter(_Fmt())
_sh = logging.StreamHandler(sys.stdout);               _sh.setLevel(logging.DEBUG); _sh.setFormatter(_Fmt())
log.handlers = [_fh, _sh]

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


# ── HuggingFace cache cleanup (on startup — remove *.incomplete garbage) ──
def _cleanup_hf_cache():
    """Borra archivos *.incomplete en el cache de HuggingFace para evitar
    que Ocupen espacio inútilmente. Solo elimina los incompletos;
    los completos se preservan. Esto permite descargas limpias cuando
    una descarga anterior fue interrumpida."""
    try:
        hf_base = os.path.expanduser(r"~/.cache\huggingface\hub")
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

def get_original_image_name(files):
    """Return the original image filename from PocketBase files list.
    Prefers the first file with an image extension."""
    for f in files:
        if isinstance(f, str) and f.lower().endswith(IMG_EXT):
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
        log.error("  [%s] pano: input不存在 %s" % (slug, input_file))
        return None

    base_name = os.path.splitext(orig_filename)[0]
    pano_path = pano_path_for_slug(slug, base_name)
    ensure_dir(pano_path)

    # Skip if already generated
    if os.path.exists(pano_path) and os.path.getsize(pano_path) > 0:
        log.info("  [%s] pano: ya existe (cache) -> %s" % (slug, pano_path))
        return pano_path

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

        if os.path.exists(pano_path) and os.path.getsize(pano_path) > 0:
            log.info("  [%s] pano: generado -> %s (%.2f MB)" % (
                slug, pano_path, os.path.getsize(pano_path)/1e6))
            return pano_path
        else:
            log.error("  [%s] pano: archivo no fue creado" % slug)
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

    def sample_perspective_from_pano(pano_img, azimuth_deg, elev_deg, fov_deg, out_w, out_h):
        """Sample a perspective view from equirectangular panorama.

        Returns PIL Image of the perspective projection."""
        # Camera looking direction
        cam_dir = equirectangular_to_cartesian(azimuth_deg, elev_deg)

        # Camera "right" vector (perpendicular to cam_dir, in horizontal plane)
        # For a standard perspective camera: right = cross(cam_dir, world_up)
        world_up = np.array([0, 0, 1])
        cam_right = np.cross(world_up, cam_dir)
        cam_right = cam_right / (np.linalg.norm(cam_right) + 1e-8)

        # Camera "up" vector
        cam_up = np.cross(cam_dir, cam_right)

        # Field of view → focal length
        fov_rad = math.radians(fov_deg)
        focal_px = (out_w / 2) / math.tan(fov_rad / 2)

        # Build output image
        out = np.zeros((out_h, out_w, 3), dtype=np.uint8)
        cx, cy = out_w // 2, out_h // 2

        # Ray direction for each pixel
        for py in range(out_h):
            for px in range(out_w):
                # NDC offsets from center
                dx = (px - cx) / focal_px
                dy = (py - cy) / focal_px

                # Ray direction in camera space
                ray_cam = np.array([dx, -dy, 1.0])
                ray_cam = ray_cam / (np.linalg.norm(ray_cam) + 1e-8)

                # Transform to world space
                ray_world = (ray_cam[0] * cam_right +
                             ray_cam[1] * cam_up +
                             ray_cam[2] * cam_dir)
                ray_world = ray_world / (np.linalg.norm(ray_world) + 1e-8)

                # Convert to equirectangular UV
                # x = sin(az), y = cos(az) for longitude; z for latitude
                az = math.atan2(ray_world[0], ray_world[1])   # [-π, π]
                el = math.asin(np.clip(ray_world[2], -1, 1))

                # Map to pixel coordinates in panorama
                u = (az / (2 * math.pi) + 0.5) % 1.0
                v = (el / math.pi + 0.5)
                px_pano = int(u * pano_w) % pano_w
                py_pano = int(v * pano_h)
                py_pano = max(0, min(pano_h - 1, py_pano))

                out[py, px] = np.array(pano_img)[py_pano, px_pano]

        return Image.fromarray(out)

    # View angles: center + ring at 45° intervals + ring at 45° with ±elev
    azimuths = [0, 45, 90, 135, 180, 225, 270, 315]
    elevations = [0, 15, -15]
    view_angles = []
    view_angles.append((0, 0))       # center
    for az in azimuths:
        view_angles.append((az, 0))  # ring 1 — horizontal
    for az in azimuths:
        view_angles.append((az % 360, 30 if az % 90 == 0 else -30))  # ring 2 — elevated

    # Trim to n_views
    view_angles = view_angles[:n_views]

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

    # Max quality settings (override defaults)
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

    # Guardar cache para export_glb_mesh (sin re-inferencia)
    try:
        import torch
        cache_path = os.path.join(output_dir, "pipeline_cache.json")
        with open(cache_path, "w") as fh:
            json.dump({
                "slug": slug,
                "views": views,
                "saved_at": datetime.now().isoformat(),
            }, fh)
    except Exception as e:
        log.warning("  [%s] run_ml: no se pudo guardar cache: %s" % (slug, e))

    if want_mesh:
        try:
            export_glb_mesh(slug, settings)
        except Exception as e:
            log.error("  [%s] mesh GLB FALLO: %s" % (slug, e))

    return output_dir


def export_glb_mesh(slug, settings):
    """Genera mesh.glb usando predictions cacheadas (sin re-inferencia).
    Si el panorama fue generado, usa las views; si no, usa las imágenes
    originales del input/."""
    import numpy as np
    import torch
    from hyworld2.worldrecon.hyworldmirror.utils.inference_utils import (
        prepare_input, compute_adaptive_target_size, compute_sky_mask, compute_filter_mask,
    )
    from hyworld2.worldrecon.hyworldmirror.models.utils.geometry import depth_to_world_coords_points
    from hyworld2.worldrecon.hyworldmirror.utils.visual_util import convert_predictions_to_glb_scene

    views_dir = os.path.join(PROJECTS_DIR, slug, "views")
    input_dir  = os.path.join(PROJECTS_DIR, slug, "input")
    output_dir = os.path.join(PROJECTS_DIR, slug, "output")
    os.makedirs(output_dir, exist_ok=True)

    # Try views first, then fallback to input
    view_paths = sorted(glob.glob(os.path.join(views_dir, "*.png"))) + \
                 sorted(glob.glob(os.path.join(views_dir, "*.jpg")))
    if view_paths:
        img_paths = view_paths
        source_desc = "views"
    else:
        img_paths, _ = prepare_input(input_dir, target_size=952)
        source_desc = "input"

    if not img_paths:
        log.error("  [%s] mesh: sin imagenes (%s)" % (slug, source_desc))
        return None

    target_size = int((settings or {}).get("target_size", 952))
    effective = compute_adaptive_target_size(img_paths, target_size)
    log.info("  [%s] mesh: usando %d imagenes de %s (target=%s)" % (
        slug, len(img_paths), source_desc, effective))

    # Load predictions from cache
    cache_path = os.path.join(output_dir, "pipeline_cache.json")
    use_cache = os.path.exists(cache_path)
    if use_cache:
        log.info("  [%s] mesh: usando predictions cacheadas (sin re-inferencia)" % slug)
        try:
            pred_path = os.path.join(output_dir, "predictions_best.pt")
            if os.path.exists(pred_path):
                predictions = torch.load(pred_path,
                    map_location="cuda" if torch.cuda.is_available() else "cpu")
            else:
                use_cache = False
                log.warning("  [%s] mesh: predictions_best.pt no existe — re-inferencia" % slug)
        except Exception as e:
            use_cache = False
            log.warning("  [%s] mesh: error cargando cache — re-inferencia: %s" % (slug, e))

    if not use_cache:
        log.info("  [%s] mesh: re-ejecutando inferencia..." % slug)
        predictions, imgs, _ = _PIPELINE_WORLD._run_inference(img_paths, effective, None, None)

    # Ensure images exist in views/ (re-download from PocketBase if missing)
    for ip in img_paths:
        if not os.path.exists(ip):
            log.warning("  [%s] mesh: imagen faltante '%s' — re-descargando" % (slug, ip))
            fname = os.path.basename(ip)
            rid, _ = pb_get_record_by_slug(slug)
            if rid:
                url = "%s/api/files/%s/%s/%s" % (PB_URL, COLLECTION, rid, fname)
                download_file(url, ip)
            else:
                log.error("  [%s] mesh: no se encontro record para re-descarga" % slug)

    # Get imgs from pipeline
    try:
        imgs = _PIPELINE_WORLD._imgs
    except Exception:
        imgs = None

    if imgs is not None:
        B, S, C, H, W = imgs.shape
        H = int(H); W = int(W); S = int(S)
    else:
        d = predictions.get("depth")
        if d is not None:
            B, S, _, H, W = d.shape[0], d.shape[1], 1, d.shape[2], d.shape[3]
            H = int(H); W = int(W)
        else:
            B, S, C, H, W = 1, len(img_paths), 3, 574, 966
            H = int(H); W = int(W)

    sky_mask = compute_sky_mask(
        img_paths, H, W, S, predictions=predictions, source="auto",
        model_threshold=0.45, processed_aspect_ratio=W/float(H),
    )
    filter_mask, _ = compute_filter_mask(
        predictions, imgs, img_paths, H, W, S,
        apply_confidence_mask=False, apply_edge_mask=True, apply_sky_mask=True,
        confidence_percentile=10.0, edge_normal_threshold=1.0, edge_depth_threshold=0.03,
        sky_mask=sky_mask, use_gs_depth=("gs_depth" in predictions),
    )

    imgs_np = imgs[0].permute(0, 2, 3, 1).detach().cpu().numpy() if imgs is not None else None
    pts3d_np = depth_to_world_coords_points(
        predictions["depth"][0, ..., 0],
        predictions["camera_poses"][0],
        predictions["camera_intrs"][0],
    )[0].detach().cpu().float().numpy()

    outputs = {
        "images": imgs_np,
        "world_points": pts3d_np,
        "final_mask": filter_mask,
        "sky_mask": sky_mask,
        "camera_poses": predictions["camera_poses"][0].detach().cpu().float().numpy(),
    }

    log.info("  [%s] mesh: construyendo GLB (as_mesh=True)..." % slug)
    scene = convert_predictions_to_glb_scene(
        outputs, filter_by_frames="all", show_camera=False,
        mask_sky_bg=True, mask_ambiguous=True, as_mesh=True,
    )
    glb_path = os.path.join(output_dir, "mesh.glb")
    scene.export(file_obj=glb_path)
    log.info("  [%s] mesh: GLB -> %s (%.2f MB)" % (slug, glb_path, os.path.getsize(glb_path)/1e6))
    try:
        del predictions, imgs
        torch.cuda.empty_cache()
    except Exception:
        pass
    return glb_path


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
    glb = os.path.join(PROJECTS_DIR, slug, "output", "mesh.glb")
    return os.path.isfile(glb) and os.path.getsize(glb) > 0

def is_built(rec):
    if rec["status"] == "completed" and mesh_glb_exists(rec["slug"]):
        return True
    if rec["status"] == "completed":
        pb_has_glb = any(str(f).lower().endswith(".glb") for f in rec["files"])
        if pb_has_glb:
            return True
    return False


# ─────────────────────────────────────────────────────────────────────
# Process one project
# ─────────────────────────────────────────────────────────────────────
def process(rec):
    """Procesa un proyecto completo: HY-Pano → multiview → WorldMirror → upload."""
    slug = rec["slug"]
    orig_filename = get_original_image_name(rec["files"])

    log.info("[%s] process: listo=%s status=%s files=%d orig=%s" % (
        slug, rec["listo"], rec["status"], len(rec["files"]), orig_filename))

    if not orig_filename:
        log.warning("  [%s] no se encontro imagen de entrada — SKIP" % slug)
        return

    # Fresh record ID lookup (detecta projects re-creados)
    rid, fresh_rec = pb_get_record_by_slug(slug)
    if not rid:
        log.warning("  [%s] no encontrado en PocketBase — SKIP" % slug)
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
        if pano_path and os.path.exists(pano_path) and os.path.getsize(pano_path) > 0:
            # ── Step 2: extract multiview from panorama ──────────────
            view_paths = extract_multiview_from_panorama(slug, orig_filename, n_views=9)
            if not view_paths:
                log.warning("  [%s] multiview falló — usando solo frente" % slug)
        else:
            log.warning("  [%s] HY-Pano no generó panorama — usando solo frente" % slug)

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
            "settings": raw.get("settings", {}) or {},
            "regenerate": bool(raw.get("regenerate", False)),
            "files": it.get("files", []) or [],
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
    """Sincroniza PocketBase ↔ local filesystem.
    - Borra carpetas huerfanas (no existen en PocketBase).
    - Proyectos activos (listo=true, o modificados hace <10 min) se preservan.
    - Limpia archivos de 0 bytes.
    - Auto-repara 'completed' sin mesh.glb → 'pending'."""
    valid = {r["slug"] for r in recs}
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
                log.debug("Reconcile: %s huerfana pero reciente (%.0fs) — se conserva" % (name, age))
                continue
            try:
                shutil.rmtree(path, ignore_errors=True)
                log.info("Reconcile: borrada carpeta huerfana %s" % name)
            except Exception as e:
                log.warning("Reconcile: no se pudo borrar %s: %s" % (name, e))

    # Por proyecto: asegurar estructura + limpiar 0-bytes
    for r in recs:
        proj = os.path.join(PROJECTS_DIR, r["slug"])
        os.makedirs(os.path.join(proj, "input"), exist_ok=True)
        os.makedirs(os.path.join(proj, "output"), exist_ok=True)
        os.makedirs(os.path.join(proj, "pano"), exist_ok=True)
        os.makedirs(os.path.join(proj, "views"), exist_ok=True)
        n = _clean_empty_files(proj)
        if n:
            log.info("Reconcile: [%s] %d archivo(s) 0-byte eliminados" % (r["slug"], n))

        # Auto-repair: completed without mesh
        if r["status"] == "completed" and not mesh_glb_exists(r["slug"]):
            pb_has_glb = any(str(f).lower().endswith(".glb") for f in r["files"])
            if not pb_has_glb:
                rid, _ = pb_get_record_by_slug(r["slug"])
                if rid:
                    set_status(rid, "pending")
                    log.info("Reconcile: [%s] 'completed' sin mesh → 'pending'" % r["slug"])


# ─────────────────────────────────────────────────────────────────────
# Main loop
# ─────────────────────────────────────────────────────────────────────
def main():
    global ML_READY, ML_REASON
    ML_READY, ML_REASON = check_ml_env()

    cycle = 0
    while True:
        cycle += 1
        try:
            log.info("--- ciclo %d | %s ---" % (cycle, datetime.now().strftime("%H:%M:%S")))
            data = pb_get("/api/collections/%s/records?perPage=500&sort=-created" % COLLECTION)
            recs = parse_records(data.get("items", []))
            log.info("%d proyecto(s) en PocketBase" % len(recs))
            reconcile(recs)
            for rec in recs:
                try:
                    process(rec)
                except Exception as e:
                    log.error("  [%s] process Exception: %s\n%s" % (
                        rec["slug"], e, traceback.format_exc()))
            log.info("ciclo %d ok. durmiendo %ss..." % (cycle, POLL_INTERVAL))
        except Exception as e:
            log.error("ciclo %d ERROR: %s" % (cycle, e))
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Worker detenido.")