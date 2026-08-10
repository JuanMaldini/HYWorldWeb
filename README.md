# HYWorld

Pipeline de generacion 3D (HY-World-2.0 + Hunyuan3D-2) con worker en GPU,
PocketBase como backend y un frontend React.

## Arranque

```bat
start.bat
```

No hace falta configurar nada. En el primer arranque `start.bat`:

1. **Deja Docker listo**: si esta apagado lo abre y espera al daemon; si no
   esta instalado lo instala con `winget`.
2. Verifica git, pnpm y la GPU.
3. **Para lo que hubiera quedado corriendo** de una sesion anterior.
4. Crea `.data\` y, si encuentra datos en el layout viejo `C:\HyWorldWebData`,
   te ofrece moverlos (no re-descarga nada).
5. Clona/actualiza HY-World-2.0 y Hunyuan3D-2 dentro de `.data\`.
6. Detecta la arquitectura CUDA real de tu GPU y construye las imagenes.
7. Levanta un PocketBase local, crea las colecciones y las cuentas.
8. Arranca el worker y el frontend.
9. **Valida que todo responda de verdad en localhost** antes de abrir el navegador.

Si algun chequeo falla, no abre el navegador: te dice que fallo y donde mirar.

No quedan consolas de `cmd` abiertas: los logs del worker se ven en Docker
Desktop y los del frontend en `.data\logs\vite.log`.

### Carga bajo demanda

El arranque es liviano y no toca la GPU. Los modelos se cargan recien cuando
el frontend pide algo:

- El **worker** idlea haciendo polling; sus pipelines se cargan por trabajo.
- El **asset server** ni siquiera arranca: queda creado y apagado, y el worker
  lo enciende solo cuando llega un pedido de assets.

### Comandos

| Comando | Que hace |
|---|---|
| `start.bat` | Arranque completo con validacion |
| `stop.bat` | Baja todo |
| `startWeb.bat` | Solo el frontend, independiente |
| `stopWeb.bat` | Baja solo el frontend |
| `start.bat -Rebuild` | Fuerza rebuild de las imagenes |
| `start.bat -SkipPull` | No actualiza los repos ML |
| `start.bat -NoBrowser` | No abre el navegador |

## Modo local vs remoto

El modo se resuelve solo a partir de `.env`:

- **Local** (por defecto): `.env` vacio o con `PB_URL=` vacia. Levanta un
  PocketBase propio en `:8092`, con las colecciones y un usuario de desarrollo
  creados automaticamente. La cuenta de servicio del worker se genera sola y
  queda en `scripts/.env` (ignorado por git). El frontend lo indica con un
  icono 💻 discreto al lado del titulo: es un estado esperado, todo se
  procesa en tu maquina y no se sube a la web.
- **Remoto**: si `PB_URL` apunta a un PocketBase alcanzable, preflight.ps1
  te pide por consola el email y password del superuser, valida que
  autentiquen y los guarda en `scripts/.env` (no en `.env`).
- **Fallback automatico**: si `PB_URL` no responde a `/api/health`, o si
  las credenciales remotas no autentican, se cae a modo local con un
  warning claro. El proyecto nunca queda inutilizable por una config rota.

### Que hay en `.env`

Solo tres variables, todas relacionadas a COMO te conectas al backend:

```
PB_URL=
PB_AUTH_COLLECTION=hyworld_user
PB_DATA_COLLECTION=hyworld_data
```

Todo lo demas (rutas de datos, modelos, cache HF, cuenta de servicio del
worker) se resuelve internamente y no se expone. No hace falta editar `.env`
nunca para empezar — basta con un archivo vacio (o solo `PB_URL=`) y el
arranque funciona.

## Donde vive cada cosa

```
<repo>\.data\            todo el estado local (gitignored)
  models\                cache de HuggingFace
  repo\                  HY-World-2.0
  Hunyuan3D-2\           asset server
  projects\              proyectos generados
  pocketbase\            base local
  logs\                  logs de arranque y del worker
```

Dentro de los contenedores todo cuelga de `/data`. La ruta en el host es
siempre `<repo>\.data` — no hay variable de entorno que la cambie.

## Servicios

| Servicio | Contenedor | Puerto | Que hace |
|---|---|---|---|
| `worker` | `hyworld_ml` | — | Worker ML, consume jobs de PocketBase |
| `assets` | `hyworld_assets` | 8081 | Asset server Hunyuan3D-2 (on-demand) |
| `pocketbase` | `hyworld_pb` | 8092 | Backend local (solo modo local) |
| Vite | — | 5173 | Frontend |

## Autenticacion

No hay tokens estaticos en ningun lado:

- El **frontend** usa el login normal de PocketBase; el token vive solo en
  `pb.authStore`. `frontend\.env` solo lleva config publica.
- El **worker** usa una cuenta de servicio (email + password) y renueva su
  token solo, con re-auth automatica ante un 401.
- Los permisos los definen las **API rules** de las colecciones.
