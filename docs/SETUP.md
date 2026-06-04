# Setup — Instalación y configuración

## Requisitos previos

### 1. GPU NVIDIA con CUDA

El sistema **no funciona sin GPU NVIDIA**. Verificá:

```bat
nvidia-smi
```

Deberías ver tu GPU listada. Si no tenés NVIDIA, el worker no va a procesar nada.

### 2. Docker Desktop

Descargá e instalá [Docker Desktop](https://www.docker.com/products/docker-desktop/).

Durante la instalación, asegurate de:
- ✓ Enable WSL 2 integration (recomendado para Windows)
- ✓ Install NVIDIA Container Toolkit (para GPU dentro de containers)

Verificá que Docker funciona:
```bat
docker info
```

### 3. NVIDIA Container Toolkit

Si `docker run --gpus all nvidia/cuda:12.8.0-base-ubuntu22.04 nvidia-smi` no funciona, seguí [esta guía](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html).

---

## Configuración

### 1. Clonar/actualizar el repo

```bat
cd D:\GitHub\HYWorldWeb
git pull
```

### 2. Crear archivo `.env`

El archivo `C:\HyWorldWebData\.env` se crea automáticamente en el primer `start.bat`, pero podés crearlo manualmente:

```env
# URL de PocketBase (remoto)
PB_URL=https://pocketbase.vmoliver.cloud

# Token de admin de PocketBase
# Obtenerlo desde: PocketBase → Admin → Settings → API Tokens
PB_ADMIN_TOKEN=tu_token_aqui

# Cada cuántos segundos el worker revisa si hay proyectos nuevos
POLL_INTERVAL=10
```

### 3. Obtener el PB_ADMIN_TOKEN

1. Andá a [https://pocketbase.vmoliver.cloud](https://pocketbase.vmoliver.cloud)
2. Logueate como admin
3. Ve a **Settings** → **API Tokens**
4. Creá un nuevo token o usá el existente
5. Copiá el token en `.env`

---

## Primera corrida

### start.bat

```bat
D:\GitHub\HYWorldWeb\start.bat
```

**Primera vez** tarda ~20-30 minutos porque:
- Descarga la imagen Docker (~3 GB)
- Instala todas las dependencias de Python (~15 GB)
- Descarga los modelos de HuggingFace (~174 GB) al procesar el primer proyecto

### Verificar que está funcionando

```bat
docker ps
```

Deberías ver `hyworld_ml` corriendo.

### Logs del worker

```bat
docker logs hyworld_ml -f
```

Buscá estas líneas para confirmar que todo está bien:

```
[HYWorld] GPU: NVIDIA GeForce RTX 3080   ← GPU detectada
[HYWorld] Cargando variables...           ← .env cargado
[INFO] ML: LISTO                          ← Worker listo
[INFO] Poll: cada 10s                    ← Worker haciendo polling
```

---

## Frontend (interfaz web)

El frontend corre **afuera** de Docker (Node.js/Vite).

### Instalar dependencias (solo la primera vez)

```bat
cd D:\GitHub\HYWorldWeb\frontend
npm install
```

### Arrancar

```bat
D:\GitHub\HYWorldWeb\Start-Web.bat
```

O manualmente:
```bat
cd D:\GitHub\HYWorldWeb\frontend
npm run dev
```

Luego visitá [http://localhost:5173](http://localhost:5173)

---

## Estructura de carpetas

### C:\HyWorldWebData

Esta carpeta se crea automáticamente y contiene todo lo que persiste entre corridas:

```
C:\HyWorldWebData\
├── .env                  ← Token y configuración (CRÍTICO)
├── repo/                 ← Clone de HY-World-2.0 (~5 GB)
│   └── hyworld2/         ← Código del pipeline
│       └── panogen/      ← HY-Pano 2.0
├── models/               ← Cache de HuggingFace (~174 GB)
│   └── hub/              ← Modelos descargados
├── projects/             ← Proyectos en procesamiento
│   └── <slug>/
│       ├── input/        ← Imagen original descargada
│       ├── pano/         ← Panorama 360° generado
│       ├── multiview/    ← 9 vistas extraídas
│       └── output/       ← PLY + GLB finales
└── logs/                 ← Logs del worker
    ├── worker_YYYYMMDD.log
    └── start_YY-MMM-DD_HHMM.log
```

> **No borres `C:\HyWorldWebData\models`** — contiene los 174 GB de modelos. Si lo borrás, se vuelven a descargar.

---

## Actualizar a una nueva versión

```bat
cd D:\GitHub\HYWorldWeb
git pull
docker compose -f D:\GitHub\HYWorldWeb\docker-compose.yml build
docker compose -f D:\GitHub\HYWorldWeb\docker-compose.yml up -d
```

---

## Desinstalación

Para borrar todo (incluidos modelos):

```bat
docker compose -f D:\GitHub\HYWorldWeb\docker-compose.yml down
docker rmi hyworld_ml:latest
rmdir /s /q C:\HyWorldWebData
```
