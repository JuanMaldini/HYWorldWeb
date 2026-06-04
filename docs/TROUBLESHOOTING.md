# Solución de Problemas

## El contenedor no levanta

### "Docker no esta corriendo"

```
[HYWorld] ERROR: Docker no esta corriendo
```

**Solución:** Abrí Docker Desktop y esperá a que termine de iniciar.

---

### "GPU NO DISPONIBLE — deteniendo"

El contenedor detecta que no hay GPU NVIDIA disponible.

**Solución:**
1. Verificá que tenés una GPU NVIDIA: `nvidia-smi`
2. Asegurate de tener NVIDIA Container Toolkit instalado
3. En Docker Desktop → Settings → Resources → WSL Integration → enable

---

## Error 400 Invalid leading whitespace en Bearer token

```
[WARN] GET ... intento 1/3: Invalid leading whitespace... Bearer eyJhbG...
```

El token en `.env` tiene caracteres `\r` (carriage return de Windows).

**Solución:**

```bat
powershell -Command "$c = Get-Content 'C:\HyWorldWebData\.env' -Raw; $c = $c -replace '\r', ''; Set-Content -Path 'C:\HyWorldWebData\.env' -Value $c -NoNewline -Encoding utf8"
```

Luego:
```bat
docker restart hyworld_ml
```

---

## "ML no disponible (no existe C:\HyWorldWebData\repo)"

El worker no encuentra el repo de HY-World-2.0.

**Causa:** Los paths dentro del contenedor usan formato Unix (`/c/HyWorldWebData/repo`) pero el worker está buscando formato Windows (`C:\HyWorldWebData\repo`).

**Solución:** Ya fue arreglado en el código. Si seguís viendo este error:
```bat
docker restart hyworld_ml
```

Si persiste, verificá que el volumen está bien:
```bat
docker exec hyworld_ml ls /c/HyWorldWebData/repo
```

---

## "no importable: No module named 'flash_attn'"

El worker levanta pero los modelos no pueden cargar porque falta `flash-attn`.

**Causa:** La imagen Docker se construyó con `runtime` (no `devel`), que no tiene `nvcc` para compilar flash-attn.

**Solución:** Rebuild de la imagen con la imagen `devel`:

```bat
docker build -t hyworld_ml:latest -f D:\GitHub\HYWorldWeb\Dockerfile D:\GitHub\HYWorldWeb
docker restart hyworld_ml
```

> **Nota:** El build con la imagen `devel` tarda más (~20 min extra) porque tiene que compilar flash-attn.

---

## Modelos no se descargan / se descargan cada vez

Los modelos de HuggingFace (169 GB de HY-Pano + 5 GB de WorldMirror) deberían persistir en `C:\HyWorldWebData\models`.

Si cada vez empiezan de nuevo:

1. Verificá que el volumen está bien montado:
```bat
docker exec hyworld_ml ls /root/.cache/huggingface
```

2. Si está vacío, los modelos se van a descargar la próxima vez que el worker procese un proyecto.

---

## El frontend no conecta con PocketBase

```
Error: Network Error
```

**Solución:**
1. Verificá que PocketBase esté accesible: [https://pocketbase.vmoliver.cloud](https://pocketbase.vmoliver.cloud)
2. Verificá que el `PB_ADMIN_TOKEN` en `.env` sea válido y no esté vacío
3. Verificá que `PB_URL` apunte a `https://pocketbase.vmoliver.cloud` (sin `/` al final)

---

## Puerto 5173 ya en uso

```
Error: listen EADDRINUSE 0.0.0.0:5173
```

**Solución:**

```bat
netstat -ano | findstr :5173
taskkill /PID <pid> /F
```

O cambiá el puerto en `frontend/vite.config.js`:

```js
server: { port: 5174 }
```

---

## docker-compose se traba / no responde

```bat
docker compose -f D:\GitHub\HYWorldWeb\docker-compose.yml down
docker system prune -f
docker compose -f D:\GitHub\HYWorldWeb\docker-compose.yml up -d
```

---

## Ver logs detallados

### Logs del contenedor completo:
```bat
docker logs hyworld_ml --tail 100 -f
```

### Logs solo de errores:
```bat
docker logs hyworld_ml --tail 100 2>&1 | findstr /i "ERRO WARN"
```

### Logs del archivo local:
```bat
Get-Content C:\HyWorldWebData\logs\worker_20260604.log -Tail 50 -Wait
```

---

## Diagnóstico rápido

Pegá esto en PowerShell para un diagnóstico completo:

```powershell
Write-Host "=== Docker ===" -ForegroundColor Cyan
docker info 2>&1 | Select-Object -First 5

Write-Host "`n=== Imagen ===" -ForegroundColor Cyan
docker images hyworld_ml:latest

Write-Host "`n=== Contenedor ===" -ForegroundColor Cyan
docker ps -a --filter "name=hyworld_ml"

Write-Host "`n=== GPU ===" -ForegroundColor Cyan
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv

Write-Host "`n=== .env ===" -ForegroundColor Cyan
Get-Content C:\HyWorldWebData\.env

Write-Host "`n=== Ultimo log worker ===" -ForegroundColor Cyan
Get-ChildItem C:\HyWorldWebData\logs\worker_*.log | Sort-Object LastWriteTime -Descending | Select-Object -First 1 | Get-Content -Tail 20
```
