# HYWorld ML — Documentación

> Sistema completo de reconstrucción 3D、环境復元 desde una sola imagen.

## Índice

- [Quick Start](#quick-start) — Levantar y correr en 5 minutos
- [Arquitectura](./ARCHITECTURE.md) — Cómo funciona el sistema por dentro
- [Setup](./SETUP.md) — Instalación detallada y configuración
- [Guía de Usuario](./USER_GUIDE.md) — Cómo usar la interfaz web
- [Solución de Problemas](./TROUBLESHOOTING.md) — Errores comunes y cómo arreglarlos

---

## Quick Start

### Requisitos

- **GPU NVIDIA** con CUDA (mínimo RTX 3060 recomendado)
- **Docker Desktop** instalado y corriendo
- **Git** instalado

### 1. Configurar variables de entorno

Editá el archivo `C:\HyWorldWebData\.env`:

```env
PB_URL=https://pocketbase.vmoliver.cloud
PB_ADMIN_TOKEN=tu_token_de_admin_aqui
POLL_INTERVAL=10
```

> ¿No tenés token? Andá a PocketBase → Admin → Settings → API Tokens y creá uno nuevo.

### 2. Levantar todo con un solo comando

```bat
D:\GitHub\HYWorldWeb\start.bat
```

Esto va a:
1. Crear la carpeta `C:\HyWorldWebData` (modelos, logs, proyectos)
2. Clonar el repo de HY-World-2.0 en `C:\HyWorldWebData\repo`
3. Construir la imagen Docker (~20 min la primera vez)
4. Arrancar el contenedor con GPU
5. El worker empieza a procesar proyectos automáticamente

### 3. Abrir la interfaz web

```bat
D:\GitHub\HYWorldWeb\Start-Web.bat
```

Luego visitá [http://localhost:5173](http://localhost:5173)

### 4. Ver los logs del worker

```bat
docker logs hyworld_ml -f
```

O los archivos en:
```
C:\HyWorldWebData\logs\
```

### 5. Detener todo

```bat
D:\GitHub\HYWorldWeb\stop.bat
```

---

## Estructura de archivos

```
D:\GitHub\HYWorldWeb\          ← Repo principal
├── start.bat                  ← Levanta todo (Docker + worker)
├── stop.bat                   ← Detiene todo
├── Start-Web.bat              ← Levanta solo el frontend (no-Docker)
├── docker-compose.yml         ← Configuración del contenedor
├── Dockerfile                 ← Imagen Docker (CUDA + Python + deps)
├── entrypoint.sh              ← Script que se ejecuta al iniciar el contenedor
├── scripts/
│   ├── worker.py              ← Worker ML (busca proyectos pending, los procesa)
│   └── run_worker_docker.py   ← Wrapper que corre dentro del contenedor
└── frontend/                  ← Interfaz web (Vite + React)

C:\HyWorldWebData\             ← Carpeta de datos (persiste entre corridas)
├── .env                       ← Credenciales (NO compartir)
├── repo/                      ← Clone de HY-World-2.0 (~5 GB)
├── models/                    ← Cache de HuggingFace (~174 GB, se descarga solo)
├── projects/                  ← Proyectos en procesamiento
└── logs/                      ← Logs del worker y del start script
```

---

## Pipeline de procesamiento

Cada proyecto pasa por:

```
1. HY-Pano 2.0        Single image → 360° panorama equirectangular
2. Extracción         9 vistas equiangulares desde el panorama
3. WorldMirror 2.0     Multi-view → Reconstrucción 3D (PLY + GLB)
4. Upload              Archivos subidos a PocketBase
```

El slug del proyecto se genera automáticamente desde el nombre del archivo de imagen original, no requiere ingreso manual.

---

## Hardware

| Componente | Mínimo | Recomendado |
|---|---|---|
| GPU | RTX 3060 (12 GB) | RTX 4080 / 4090 |
| RAM | 16 GB | 32 GB |
| VRAM | 8 GB | 12+ GB |
| Espacio disco | 50 GB | 200+ GB (modelos ~174 GB) |

Los modelos de HuggingFace (~174 GB) se descargan **la primera vez** que el worker procesa un proyecto, y persisten en `C:\HyWorldWebData\models`.
