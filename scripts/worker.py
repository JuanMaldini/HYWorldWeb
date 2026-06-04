#!/usr/bin/env python
"""
HYWorld ML Worker
Flujo (cada POLL_INTERVAL segundos):
  1. Lee TODOS los records de la coleccion `hyworld_data` en PocketBase.
  2. Para cada record (= un proyecto) descarga sus archivos de entrada a
     projects/<slug>/input/  (cacheado: salta lo ya descargado).
  3. Decide que hacer:
       - Ya construido (json.status == "completed" O hay output local) -> SKIP.
       - listo != true                                                 -> SKIP, solo deja inputs.
       - listo == true y no construido                                 -> reconstruye 3D,
         sube resultados y marca json.status = "completed".

El worker NUNCA crashea por dependencias faltantes: si torch / hyworld2 no
estan disponibles, se auto-diagnostica y salta la fase ML (sigue descargando).

Arranca con:  python scripts/worker.py
"""

import os
import sys
import json
import time
import glob
import platform
import traceback
import logging
from datetime import datetime

try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

import requests

# Rutas base
SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR     = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
PROJECTS_DIR = os.path.join(ROOT_DIR, "projects")
LOGS_DIR     = os.path.join(ROOT_DIR, "logs")
HYWORLD_DIR  = r"D:\GitHub\HY-World-2.0"

os.makedirs(PROJECTS_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

# .env
ENV_FILE = os.path.join(ROOT_DIR, ".env")
if os.path.exists(ENV_FILE):
    for line in open(ENV_FILE, encoding="utf-8"):
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

PB_URL         = os.environ.get("PB_URL", "https://pocketbase.vmoliver.cloud").rstrip("/")
PB_ADMIN_TOKEN = os.environ.get("PB_ADMIN_TOKEN", "")
COLLECTION     = "hyworld_data"
POLL_INTERVAL  = int(os.environ.get("POLL_INTERVAL", "10"))

if os.path.isdir(HYWORLD_DIR):
    sys.path.insert(0, HYWORLD_DIR)

# Logging (consola + archivo diario)
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

# Estado del entorno ML
ML_READY = False
ML_REASON = "sin comprobar"


def check_ml_env():
    """Comprueba torch + hyworld2 SIN crashear. Devuelve (ok, motivo)."""
    log.info("-" * 60)
    log.info("HYWorld ML Worker")
    log.info("Python   : %s  (%s)" % (platform.python_version(), sys.executable))
    log.info("Platform : %s %s" % (platform.system(), platform.release()))
    log.info("PB URL   : %s" % PB_URL)
    log.info("PB token : %s" % ("OK" if PB_ADMIN_TOKEN else "FALTA (las peticiones pueden fallar)"))
    log.info("Projects : %s" % PROJECTS_DIR)
    log.info("Poll     : cada %ss" % POLL_INTERVAL)

    try:
        import psutil
        vm = psutil.virtual_memory()
        log.info("RAM      : %.1f GB total | %.1f GB libre" % (vm.total / 1e9, vm.available / 1e9))
    except Exception:
        log.debug("psutil no disponible (opcional)")

    ok, reason = False, ""
    try:
        import torch
        cuda = torch.cuda.is_available()
        log.info("PyTorch  : %s | CUDA: %s" % (torch.__version__, cuda))
        if cuda:
            log.info("GPU      : %s" % torch.cuda.get_device_name(0))
        else:
            log.warning("CUDA no disponible - la reconstruccion correra en CPU (muy lento)")
    except Exception as e:
        reason = "torch no importable: %s" % e
        log.error("PyTorch  : %s" % reason)
        log.info("-" * 60)
        return False, reason

    if not os.path.isdir(HYWORLD_DIR):
        reason = "no existe %s" % HYWORLD_DIR
        log.error("hyworld2 : %s" % reason)
        log.info("-" * 60)
        return False, reason

    try:
        from hyworld2.worldrecon.pipeline import WorldMirrorPipeline  # noqa: F401
        log.info("hyworld2 : WorldMirrorPipeline importado OK")
        ok = True
    except Exception as e:
        reason = "no importable: %s" % e
        log.error("hyworld2 : %s" % reason)

    log.info("ML       : %s" % ("LISTO" if ok else "NO LISTO - solo se descargaran inputs"))
    log.info("-" * 60)
    return ok, (reason or "ok")


# Helpers PocketBase
def _headers():
    return {"Authorization": "Bearer " + PB_ADMIN_TOKEN} if PB_ADMIN_TOKEN else {}


def pb_get(path, retries=3):
    for i in range(retries):
        try:
            r = requests.get(PB_URL + path, headers=_headers(), timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.warning("  GET %s intento %d/%d: %s" % (path, i + 1, retries, e))
            if i == retries - 1:
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
            log.warning("  PATCH intento %d/%d: %s" % (i + 1, retries, e))
            if i == retries - 1:
                raise
            time.sleep(2)


def download_file(url, dest):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    for i in range(3):
        try:
            r = requests.get(url, headers=_headers(), timeout=120)
            r.raise_for_status()
            with open(dest, "wb") as f:
                f.write(r.content)
            log.debug("    descargado %s (%.2f MB)" % (os.path.basename(dest), len(r.content) / 1e6))
            return True
        except Exception as e:
            log.warning("    descarga intento %d/3 %s: %s" % (i + 1, url, e))
            time.sleep(3)
    log.error("    FALLO al descargar %s" % url)
    return False


def upload_output(record_id, filepath):
    fname = os.path.basename(filepath)
    url = "%s/api/collections/%s/records/%s" % (PB_URL, COLLECTION, record_id)
    for i in range(3):
        try:
            with open(filepath, "rb") as f:
                r = requests.patch(url, data={}, files={"files": (fname, f)},
                                   headers=_headers(), timeout=300)
            if r.ok:
                log.info("    subido %s (%.2f MB)" % (fname, os.path.getsize(filepath) / 1e6))
                return True
            log.warning("    subida intento %d: %s %s" % (i + 1, r.status_code, r.text[:120]))
        except Exception as e:
            log.warning("    subida intento %d: %s" % (i + 1, e))
        time.sleep(2)
    log.error("    FALLO al subir %s" % fname)
    return False


# Descarga de inputs
IMG_EXT = (".jpg", ".jpeg", ".png", ".webp")


def download_inputs(rec):
    slug, rid, files = rec["slug"], rec["id"], rec["files"]
    input_dir = os.path.join(PROJECTS_DIR, slug, "input")
    os.makedirs(input_dir, exist_ok=True)
    new = cached = failed = 0
    for fname in files:
        if not fname.lower().endswith(IMG_EXT):
            continue  # outputs (.ply/.obj/.glb) viven en el mismo campo files
        dest = os.path.join(input_dir, fname)
        if os.path.exists(dest) and os.path.getsize(dest) > 0:
            cached += 1
            continue
        url = "%s/api/files/%s/%s/%s" % (PB_URL, COLLECTION, rid, fname)
        if download_file(url, dest):
            new += 1
        else:
            failed += 1
    return new, cached, failed


# Ya construido?
OUT_EXT = (".ply", ".obj", ".glb", ".gltf", ".splat")


def list_outputs(out_dir):
    found = []
    for root, _dirs, files in os.walk(out_dir):
        for f in files:
            if f.lower().endswith(OUT_EXT):
                found.append(os.path.join(root, f))
    return sorted(found)


def output_exists(slug):
    out_dir = os.path.join(PROJECTS_DIR, slug, "output")
    return os.path.isdir(out_dir) and len(list_outputs(out_dir)) > 0


def is_built(rec):
    return rec["status"] == "completed" or output_exists(rec["slug"])


# Reconstruccion 3D
def run_ml(slug):
    input_dir = os.path.join(PROJECTS_DIR, slug, "input")
    output_dir = os.path.join(PROJECTS_DIR, slug, "output")
    os.makedirs(output_dir, exist_ok=True)

    imgs = [p for p in sorted(glob.glob(os.path.join(input_dir, "*")))
            if p.lower().endswith(IMG_EXT)]
    if not imgs:
        log.error("  [%s] sin imagenes en %s" % (slug, input_dir))
        return None

    log.info("  [%s] %d imagen(es). Cargando WorldMirrorPipeline..." % (slug, len(imgs)))
    from hyworld2.worldrecon.pipeline import WorldMirrorPipeline

    # from_pretrained auto-detecta CUDA. enable_bf16 ahorra VRAM (recomendado en RTX 30xx).
    pipeline = WorldMirrorPipeline.from_pretrained("tencent/HY-World-2.0", enable_bf16=True)

    log.info("  [%s] Pipeline cargado. Reconstruyendo (input dir completo)..." % slug)
    # __call__ recibe un DIRECTORIO de imagenes; strict_output_path escribe
    # los resultados directamente en output/ (sin subcarpeta con timestamp).
    result = pipeline(input_dir, strict_output_path=output_dir)
    if not result:
        log.error("  [%s] el pipeline devolvio None (sin salida)" % slug)
        return None
    log.info("  [%s] Reconstruccion terminada -> %s" % (slug, result))
    return output_dir


# Procesa un proyecto
def process(rec):
    slug, rid = rec["slug"], rec["id"]
    log.info("[%s] name=%s listo=%s status=%s files=%d" % (
        slug, rec["name"], rec["listo"], rec["status"], len(rec["files"])))

    new, cached, failed = download_inputs(rec)
    log.info("  [%s] inputs: %d nuevos, %d cacheados, %d fallidos" % (slug, new, cached, failed))
    if failed:
        log.error("  [%s] hubo fallos de descarga - no se procesa este ciclo" % slug)
        return

    if is_built(rec):
        log.info("  [%s] YA construido (status=completed u output local) - SKIP" % slug)
        return

    if not rec["listo"]:
        log.info("  [%s] listo=OFF - inputs cacheados, esperando que lo marques listo" % slug)
        return

    if not ML_READY:
        log.warning("  [%s] listo=ON pero entorno ML no disponible (%s) - SKIP reconstruccion" % (slug, ML_REASON))
        return

    log.info("  [%s] listo=ON - iniciando reconstruccion 3D" % slug)
    try:
        out_dir = run_ml(slug)
    except Exception as e:
        log.error("  [%s] ML FALLO: %s\n%s" % (slug, e, traceback.format_exc()))
        return
    if not out_dir:
        return

    outputs = list_outputs(out_dir)
    log.info("  [%s] %d archivo(s) de salida, subiendo..." % (slug, len(outputs)))
    for f in outputs:
        upload_output(rid, f)

    try:
        current = pb_get("/api/collections/%s/records/%s" % (COLLECTION, rid))
        parsed = current.get("json") or {}
        if isinstance(parsed, str):
            try:
                parsed = json.loads(parsed or "{}")
            except Exception:
                parsed = {}
        parsed["status"] = "completed"
        parsed["finished_at"] = datetime.now().isoformat()
        pb_patch_json(rid, {"json": parsed})
        log.info("  [%s] marcado completed en PocketBase" % slug)
    except Exception as e:
        log.error("  [%s] no se pudo marcar completed: %s" % (slug, e))


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
            "files": it.get("files", []) or [],
        })
    return out


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
            for rec in recs:
                process(rec)
            log.info("ciclo %d ok. durmiendo %ss..." % (cycle, POLL_INTERVAL))
        except Exception as e:
            log.error("ciclo %d ERROR: %s" % (cycle, e))
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Worker detenido por el usuario.")
