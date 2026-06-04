# Arquitectura — HYWorld ML

## Vista general

```
┌─────────────────────────────────────────────────────────────┐
│  Tu PC (Windows)                                            │
│                                                             │
│  ┌──────────────────┐    ┌─────────────────────────────┐  │
│  │  Frontend (Vite) │    │  Docker Container            │  │
│  │  localhost:5173  │    │  hyworld_ml                 │  │
│  │                   │    │                              │  │
│  │  React app        │    │  ┌──────────────────────┐  │  │
│  │  → PocketBase     │    │  │  worker.py           │  │  │
│  │  (solo API)       │    │  │  (polling cada 10s)  │  │  │
│  └──────────────────┘    │  │  │                      │  │  │
│         ▲                │  │  │  ┌───────────────┐  │  │  │
│         │                │  │  │  │ HY-Pano 2.0   │  │  │  │
│         │                │  │  │  │ (169 GB)      │  │  │  │
│         │                │  │  │  └───────────────┘  │  │  │
│         │                │  │  │  ┌───────────────┐  │  │  │
│         │                │  │  │  │ WorldMirror   │  │  │  │
│         │                │  │  │  │ 2.0 (5 GB)    │  │  │  │
│         │                │  │  │  └───────────────┘  │  │  │
│         │                │  │  └──────────────────────┘  │  │
│         │                │  └─────────────────────────────┘  │
│         │                │           │                        │
│  ┌──────┴───────────────┐│           │ NVIDIA GPU (RTX 3080)  │
│  │ PocketBase (remote)  ││           ▼                        │
│  │ pocketbase.vmoliver  ││    ┌──────────────────┐           │
│  │ .cloud               ││    │  GPU VRAM        │           │
│  │                      ││    │  ~10-14 GB usados │           │
│  │ • Almacena imágenes ││    └──────────────────┘           │
│  │ • Estado proyectos   ││                                   │
│  │ • Archivos 3D (GLB) │└───────────────────────────────────┘
│  └─────────────────────┘
└─────────────────────────────────────────────────────────────┘
```

## Componentes

### Frontend (`frontend/`)
- **Vite + React** — corre ** fuera** de Docker, en el host
- Puerto 5173
- Se comunica **directamente** con PocketBase (solo API, no tiene acceso al worker)
- Sube imágenes → PocketBase → el worker las detecta

### Worker (`scripts/worker.py`)
- Corre **dentro** del contenedor Docker
- Poll cada `POLL_INTERVAL` segundos (default 10s)
- Busca proyectos con `listo=True` y `status=pending` en PocketBase
- Por cada proyecto:
  1. Descarga la imagen original desde PocketBase
  2. Ejecuta HY-Pano 2.0 → genera panorama 360°
  3. Extrae 9 vistas equiangulares del panorama
  4. Ejecuta WorldMirror 2.0 → PLY + GLB
  5. Sube los resultados a PocketBase
  6. Marca el proyecto como `completed` o `error`

### Docker Container (`hyworld_ml`)
- Base: `nvidia/cuda:12.8.1-devel-ubuntu22.04` (para compilar flash-attn)
- Python 3.11 (sin conda — pip directo)
- Todos los Python packages instalados en la imagen
- Modelos de HuggingFace en volumen montado (`C:\HyWorldWebData\models`)
- Repo HY-World-2.0 montado en `C:\HyWorldWebData\repo`

### PocketBase (remoto)
- `https://pocketbase.vmoliver.cloud`
- Colección: `hyworld_data`
- Campos relevantes:
  - `json.slug` — identificador único del proyecto
  - `json.status` — `pending` | `processing` | `completed` | `error`
  - `json.listo` — boolean ( imagen lista para procesar)
  - `files` — imágenes y archivos 3D

## Volúmenes y paths

### Dentro del contenedor

| Variable | Path dentro del contenedor |
|---|---|
| `HYWORLD_DIR` | `/c/HyWorldWebData/repo` |
| `PROJECTS_DIR` | `/c/HyWorldWebData/projects` |
| `LOGS_DIR` | `/c/HyWorldWebData/logs` |
| `HF_HOME` | `/root/.cache/huggingface` → `C:\HyWorldWebData\models` |

### En el host (Windows)

| Path | Contenido |
|---|---|
| `C:\HyWorldWebData` | Carpeta de datos raíz |
| `C:\HyWorldWebData\repo` | Clone de HY-World-2.0 |
| `C:\HyWorldWebData\models` | Cache HuggingFace (~174 GB) |
| `C:\HyWorldWebData\projects` | Proyectos en proceso |
| `C:\HyWorldWebData\logs` | Archivos de log |

## Flujo de datos por proyecto

```
1. Usuario sube imagen desde frontend
   → PocketBase: archivo guardado, registro creado con listo=True, status=pending

2. Worker poll (cada 10s)
   → PocketBase: GET /api/collections/hyworld_data/records?filter=status="pending"
   → Descarga imagen → C:\HyWorldWebData\projects\<slug>\input\<archivo>

3. HY-Pano 2.0 (primera etapa)
   → Imagen → pipeline → panorama_360.png
   → Ubicación: C:\HyWorldWebData\projects\<slug>\pano\

4. Extracción de vistas
   → panorama_360.png → 9 imágenes (view_00.png ... view_08.png)
   → Ubicación: C:\HyWorldWebData\projects\<slug>\multiview\

5. WorldMirror 2.0 (segunda etapa)
   → 9 vistas → mesh.ply + mesh.glb
   → Ubicación: C:\HyWorldWebData\projects\<slug>\output\

6. Worker sube resultados a PocketBase
   → PATCH /api/collections/hyworld_data/records/<id> con archivos

7. Worker marca proyecto como completed
   → PATCH /api/collections/hyworld_data/records/<id> con status="completed"
```

## Slug generation

El slug se genera automáticamente en el frontend:

```
slug = `{nombre_sin_extension}_{hash6}`
```

Ejemplo: `env_10_uzbrzzr7z9.JPG` → `env-10_ukdjx7`

No hay campo de nombre de proyecto — el usuario solo selecciona la imagen.

## Logs

| Archivo | Contenido |
|---|---|
| `C:\HyWorldWebData\logs\worker_YYYYMMDD.log` | Log principal del worker |
| `C:\HyWorldWebData\logs\start_04-Jun-26_0409.log` | Output de start.bat |

Ver worker en tiempo real:
```bat
docker logs hyworld_ml -f
```
