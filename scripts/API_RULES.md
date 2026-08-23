# API rules de las colecciones

PocketBase evalua cinco reglas por coleccion. Cada una acepta:

- `""` — regla vacia: el acceso depende del `type` de la coleccion.
- `null` — bloqueado para todos (incluido el admin via API).
- una expresión de filtro estilo SQL, ej. `@request.auth.id != ""`.

| Campo | Cuando se evalua |
|---|---|
| `listRule`   | `GET /api/collections/{name}/records` |
| `viewRule`   | `GET /api/collections/{name}/records/{id}` |
| `createRule` | `POST /api/collections/{name}/records` |
| `updateRule` | `PATCH /api/collections/{name}/records/{id}` |
| `deleteRule` | `DELETE /api/collections/{name}/records/{id}` |

`@request.auth.id` es el id del usuario autenticado, o vacio si no hay sesion.
`@request.body.<campo>` permite leer campos del payload entrante.

---

## `hyworld_user` — auth

Coleccion de autenticacion. Cada registro es un usuario del frontend.

| Regla | Valor | Por que |
|---|---|---|
| `listRule`   | `@request.auth.id = id` | Cada usuario solo se ve a si mismo en listados. |
| `viewRule`   | `@request.auth.id = id` | Nadie puede leer la ficha de otro. |
| `createRule` | `` (vacia)            | El SDK solo crea registros via `/api/collections/{name}/auth-with-password` y el endpoint de admin (no confundir con `createRule`). La regla vacia permite registros via API; los registros que se creen manualmente seran usuarios reales. |
| `updateRule` | `@request.auth.id = id` | Solo el propio usuario edita su perfil. |
| `deleteRule` | `null`                 | Nadie se borra a si mismo via API. El admin lo hace desde el panel `/admin`. |

> El frontend NO usa `auth-with-password` directo sobre esta coleccion —
> usa el helper de `pocketbase.js` que delega al SDK. Las reglas de arriba
> ya cubren login, signup y gestion basica sin necesidad de un token admin.

---

## `hyworld_data` — base (proyectos)

Coleccion de proyectos. Contiene un campo `json` (text con la metadata del
proyecto) y `files` (file[] con la salida 3D).

| Regla | Valor | Por que |
|---|---|---|
| `listRule`   | `` (vacia)            | El dashboard y `/p/:slug` son publicos: cualquier visitante ve el listado y las fichas. |
| `viewRule`   | `` (vacia)            | Idem para el detalle. |
| `createRule` | `@request.auth.id != ""` | Solo usuarios logueados crean proyectos. |
| `updateRule` | `@request.auth.id != ""` | Solo usuarios logueados tocan proyectos (el worker usa su propia cuenta de servicio, que cumple esta regla). |
| `deleteRule` | `@request.auth.id != ""` | Idem para borrado. |

El worker entra con la MISMA cuenta de usuario que la web (`PB_USER_EMAIL` /
`PB_USER_PASSWORD` del `.env`) y renueva su token solo — cumple la regla con
`@request.auth.id != ""` igual que el frontend. No hay cuenta de servicio ni
superuser: el worker no puede hacer nada que el usuario no pueda hacer desde
la web.

---

## Como verificar / cambiar las reglas

### Local (PB en :8092)

```powershell
# Desde el repo, con preflight ya ejecutado:
Invoke-RestMethod -Uri 'http://localhost:8092/api/collections/hyworld_data' `
    -Headers @{ Authorization = "Bearer $token" } | Select-Object listRule, viewRule, createRule, updateRule, deleteRule
```

Para editar reglas a mano (no recomendado, preflight las recrea al provisionar):

```powershell
$body = @{ listRule = ''; viewRule = ''; createRule = '@request.auth.id != ""';
           updateRule = '@request.auth.id != ""'; deleteRule = '@request.auth.id != ""' } | ConvertTo-Json
Invoke-RestMethod -Method Patch `
    -Uri 'http://localhost:8092/api/collections/hyworld_data' `
    -Headers @{ Authorization = "Bearer $token" } `
    -ContentType 'application/json' -Body $body
```

### Remoto (cualquier PB)

Mismas llamadas, reemplazando `http://localhost:8092` por tu `PB_URL` y
autenticando como admin para `PATCH /api/collections/{name}`. Si el remoto
ya tiene las colecciones creadas, preflight las deja como estan y solo las
intenta crear si no existen.

### Caso especial: panel `/admin`

PocketBase sirve su panel admin en `PB_URL/_/`. Para entrar necesitás una
cuenta de la coleccion `_superusers` (no de `hyworld_user`). Esa cuenta NO
esta en el `.env` ni la maneja el proyecto:

- **Local**: preflight crea un superuser interno del contenedor (`admin@hyworld.local`)
  solo para poder crear las colecciones por API. Es efimero y no se persiste.
- **Remoto**: es la cuenta de admin de esa instancia, la que ya usás para
  entrar al panel. El proyecto nunca la pide ni la guarda.
