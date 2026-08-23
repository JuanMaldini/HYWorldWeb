#!/usr/bin/env python
"""
HYWorld — Run Inside Docker
===========================
Wrapper que se ejecuta DENTRO del contenedor y lanza worker.py.

Las rutas ya vienen del compose (HYWORLD_DIR / PROJECTS_DIR / LOGS_DIR,
todas bajo /data). Aca solo se ponen defaults por si el contenedor se
corre a mano sin compose, y se arma el sys.path.
"""

import os
import sys

DATA = "/data"

# ── Defaults (el compose normalmente ya los define) ───────
os.environ.setdefault("HYWORLD_DIR", DATA + "/repo")
os.environ.setdefault("PROJECTS_DIR", DATA + "/projects")
os.environ.setdefault("LOGS_DIR", DATA + "/logs")

HYWORLD_DIR = os.environ["HYWORLD_DIR"]
PANOGEN = os.path.join(HYWORLD_DIR, "hyworld2", "panogen")
os.environ.setdefault("PYTHONPATH", PANOGEN + ":" + HYWORLD_DIR)

# ── sys.path ───────────────────────────────────────────────
for p in (HYWORLD_DIR, PANOGEN):
    if p not in sys.path:
        sys.path.insert(0, p)

# ── Ejecutar worker ───────────────────────────────────────
WORKER_PATH = "/workspace/scripts/worker.py"
if not os.path.exists(WORKER_PATH):
    print("[HYWorld] ERROR: worker.py no encontrado en %s" % WORKER_PATH)
    sys.exit(1)

print("[HYWorld] Ejecutando worker:")
print("  HYWORLD_DIR   = %s" % os.environ["HYWORLD_DIR"])
print("  PROJECTS_DIR  = %s" % os.environ["PROJECTS_DIR"])
print("  LOGS_DIR      = %s" % os.environ["LOGS_DIR"])
print("  PB_URL        = %s" % os.environ.get("PB_URL", "NO CONFIGURADO"))
print("  PB_USER       = %s" % (os.environ.get("PB_USER_EMAIL") or "FALTA"))
print()

os.execv(sys.executable, [sys.executable, "-u", WORKER_PATH])
