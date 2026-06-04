#!/usr/bin/env python
"""
HYWorld — Run Inside Docker
===========================
Este script se ejecuta DENTRO del contenedor Docker.
Fija las variables de entorno correctas para que el worker.py
(funcionando via mounted volume) sepa dónde encontrar todo.

Uso: python3.11 run_worker_docker.py
"""

import os
import sys

# ── Paths dentro del contenedor ─────────────────────────────────────
# Cuando el compose monta C:\HyWorldWebData como C:\HyWorldWebData:
#   - projects  → C:\HyWorldWebData\projects
#   - logs      → C:\HyWorldWebData\logs
#   - repo      → C:\HyWorldWebData\repo
#   - .env      → C:\HyWorldWebData\.env
# Cuando scripts se monta: D:\GitHub\HYWorldWeb\scripts → /workspace/scripts

os.environ["HYWORLD_DIR"]   = r"C:\HyWorldWebData\repo"
os.environ["PROJECTS_DIR"]  = r"C:\HyWorldWebData\projects"
os.environ["LOGS_DIR"]     = r"C:\HyWorldWebData\logs"
os.environ["PYTHONPATH"]    = r"C:\HyWorldWebData\repo\hyworld2\panogen;C:\HyWorldWebData\repo"

# Override sys.path para imports de hyworld2
_HYWORLD = r"C:\HyWorldWebData\repo"
_PANOGEN = os.path.join(_HYWORLD, "hyworld2", "panogen")
if _HYWORLD not in sys.path:
    sys.path.insert(0, _HYWORLD)
if _PANOGEN not in sys.path:
    sys.path.insert(0, _PANOGEN)

# Cargar .env si existe (antes de importar worker)
_ENV_FILE = r"C:\HyWorldWebData\.env"
if os.path.exists(_ENV_FILE):
    for line in open(_ENV_FILE, encoding="utf-8"):
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

# ── Ejecutar worker ─────────────────────────────────────────────────
# El worker.py está montado en /workspace/scripts/worker.py
WORKER_PATH = "/workspace/scripts/worker.py"
if not os.path.exists(WORKER_PATH):
    print(f"[HYWorld] ERROR: worker.py no encontrado en {WORKER_PATH}")
    sys.exit(1)

print(f"[HYWorld] Ejecutando worker con:")
print(f"  HYWORLD_DIR   = {os.environ.get('HYWORLD_DIR')}")
print(f"  PROJECTS_DIR  = {os.environ.get('PROJECTS_DIR')}")
print(f"  LOGS_DIR      = {os.environ.get('LOGS_DIR')}")
print(f"  PB_URL        = {os.environ.get('PB_URL', 'NO CONFIGURADO')}")
print(f"  PB_TOKEN      = {'OK' if os.environ.get('PB_ADMIN_TOKEN') else 'FALTA'}")
print()

# Ejecutar worker con unbuffered output
os.execv(sys.executable, [sys.executable, "-u", WORKER_PATH])