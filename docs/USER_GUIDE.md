# Guía de Usuario — HYWorld Web

## ¿Qué es HYWorld?

HYWorld transforma **una sola foto** de un ambiente (living, habitación, oficina) en un **modelo 3D interactivo** que podés ver, rotar y usar.

**No necesitás saber nada de 3D.** Solo subís una imagen y el sistema hace todo.

---

## Usar la interfaz web

### 1. Arrancá el sistema

```bat
D:\GitHub\HYWorldWeb\start.bat
```

Esperá a ver:
```
HYWorld iniciado!
```

### 2. Arrancá el frontend

```bat
D:\GitHub\HYWorldWeb\Start-Web.bat
```

### 3. Abrí en el navegador

[http://localhost:5173](http://localhost:5173)

---

## Subir una imagen

1. En la página principal, hacé click en **"Nueva Reconstrucción"** o arrastrá una imagen al área de upload
2. Seleccioná una foto de ambiente (living, cocina, habitación, etc.)
   - Formatos: JPG, PNG, WEBP
   - Recomendado: buena iluminación, vista desde el medio del ambiente
   - Mínimo: 512x512 px
3. Esperá a que diga "Imagen lista"

**No hay campo de nombre de proyecto.** El slug se genera automáticamente desde el nombre del archivo.

---

## ¿Qué pasa después?

Una vez que subís la imagen:

1. **Worker detecta** el proyecto (tarda hasta 10s)
2. **HY-Pano 2.0** genera un panorama 360° (puede tardar varios minutos)
3. **WorldMirror 2.0** convierte las vistas en un modelo 3D (5-15 min depending on GPU)
4. **Resultado** sube a PocketBase automáticamente

Todo esto pasa **en segundo plano**. No necesités tener la página abierta.

---

## Monitorear progreso

### Desde la web
- La lista de proyectos muestra el estado: `pending` → `processing` → `completed`
- Si hay un error, aparece en rojo

### Desde la terminal

```bat
docker logs hyworld_ml -f
```

Buscá líneas como:
```
[INFO] [env-10_ukdjx7] process: listo=True status=pending  ← detectado
[INFO]   [env-10_ukdjx7] input cacheado                   ← descargando imagen
[INFO]   HY-Pano 2.0 iniciando...                          ← procesando
[INFO]   WorldMirror 2.0 iniciando...                     ← reconstructing 3D
[INFO]   [env-10_ukdjx7] COMPLETADO                      ← listo
```

---

## Descargar el modelo 3D

Cuando el estado es `completed`:

1. Hacé click en el proyecto en la lista
2. Buscá la sección **"Archivos"** o **"Downloads"**
3. Descargá `mesh.glb` — el modelo 3D en formato estándar

### Ver el modelo 3D

El archivo `mesh.glb` se puede abrir con:
- [3D Viewer](https://3dviewer.net/) (gratis, web)
- Blender (gratis, escritorio)
- Cualquier visor GLB/GLTF

---

## Estados de un proyecto

| Estado | Significado |
|---|---|
| `pending` | Esperando a que el worker lo procese |
| `processing` | El worker lo está procesando ahora |
| `completed` | Listo — modelo 3D disponible |
| `error` | Algo falló — ver logs para detalles |

---

## Buenas fotos = mejores resultados

Para mejores resultados:

✓ **Buena iluminación** — luz natural o iluminación均匀
✓ **Vista desde el medio** — parate en el centro del ambiente
✓ **Angulo ligeramente inclinado** — no perfectamente horizontal
✓ **Mínimo furniture** — menos objetos = mejor reconstrucción de la estructura
✓ ** Paredes y pisos visibles** — el sistema usa esto como referencia

✗ **Noches o muy oscuro**
✗ **Solo techo o solo piso**
✗ **Fotos extremadamente amplias** (puede generar artifacts)
✗ **Demasiado objetos** (muebles pequeños pueden desaparecer)
