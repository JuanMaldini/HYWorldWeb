#!/usr/bin/env python
"""
HYWorld — Run Inside Docker
===========================
Wrapper que se ejecuta DENTRO del contenedor Docker.
Fija las variables de entorno y ejecuta worker.py
"""

import os
import sys

# ── Paths ─────────────────────────────────────────────────
os.environ["HYWORLD_DIR"]   = r"C:\HyWorldWebData\repo"
os.environ["PROJECTS_DIR"]  = r"C:\HyWorldWebData\projects"
os.environ["LOGS_DIR"]     = r"C:\HyWorldWebData\logs"
os.environ["PYTHONPATH"]    = r"C:\HyWorldWebData\repo\hyworld2\panogen;C:\HyWorldWebData\repo"

# ── sys.path ───────────────────────────────────────────────
_HYWORLD = r"C:\HyWorldWebData\repo"
_PANOGEN = os.path.join(_HYWORLD, "hyworld2", "panogen")
if _HYWORLD not in sys.path:
    sys.path.insert(0, _HYWORLD)
if _PANOGEN not in sys.path:
    sys.path.insert(0, _PANOGEN)

# ── Cargar .env ───────────────────────────────────────────
_ENV_FILE = r"C:\HyWorldWebData\.env"
if os.path.exists(_ENV_FILE):
    for line in open(_ENV_FILE, encoding="utf-8"):
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

# ── Ejecutar worker ───────────────────────────────────────
WORKER_PATH = "/workspace/scripts/worker.py"
if not os.path.exists(WORKER_PATH):
    print(f"[HYWorld] ERROR: worker.py no encontrado en {WORKER_PATH}")
    sys.exit(1)

print(f"[HYWorld] Ejecutando worker:")
print(f"  HYWORLD_DIR   = {os.environ.get('HYWORLD_DIR')}")
print(f"  PROJECTS_DIR  = {os.environ.get('PROJECTS_DIR')}")
print(f"  LOGS_DIR      = {os.environ.get('LOGS_DIR')}")
print(f"  PB_URL        = {os.environ.get('PB_URL', 'NO CONFIGURADO')}")
print(f"  PB_TOKEN      = {'OK' if os.environ.get('PB_ADMIN_TOKEN') else 'FALTA'}")
print()

os.execv(sys.executable, [sys.executable, "-u", WORKER_PATH])