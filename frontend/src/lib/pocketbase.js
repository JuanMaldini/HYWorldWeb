import PocketBase from 'pocketbase'

// VITE_PB_URL manda si esta definida. Si no: en dev apunta al PocketBase
// local que levanta start.bat (:8092); en el build de produccion, al deploy.
const PB_URL = import.meta.env.VITE_PB_URL
  || (import.meta.env.PROD ? 'https://pocketbase.vmoliver.cloud' : 'http://localhost:8092')

export const pb = new PocketBase(PB_URL)

// Modo local = el backend es un PocketBase de esta maquina. Es un estado
// esperado, no un error: la UI lo muestra como un icono, no como aviso.
export const isLocalMode = /^https?:\/\/(localhost|127\.0\.0\.1)/i.test(PB_URL)
export const pbUrl = PB_URL

const COLLECTION = 'hyworld_data'
const col = () => pb.collection(COLLECTION)

export const login = async (email, password) => {
  const authData = await pb.collection('hyworld_user').authWithPassword(email, password)
  return authData
}

export const logout = () => {
  pb.authStore.clear()
}

export const isAuthenticated = () => pb.authStore.isValid

export const getUser = () => pb.authStore.record || pb.authStore.model

function generateSlug(filename) {
  // slug = {nombre_sin_ext}_{hash6} — se genera del nombre del archivo, no del input del usuario
  const nameWithoutExt = filename.replace(/\.[^.]+$/, '').trim().toLowerCase().replace(/\s+/g, '-').replace(/[^a-z0-9-]/g, '')
  const hash = Math.random().toString(36).substring(2, 8)
  return `${nameWithoutExt}_${hash}`
}

// ── Helpers ───────────────────────────────────────────────────────────
// El SDK arma la URL del archivo y, si la coleccion pasara a ser protegida,
// tambien el token: es preferible a concatenar rutas a mano.
const fileUrlOf = (record, filename) => pb.files.getURL(record, filename)

// El campo `json` guarda todo el estado del proyecto como blob. PocketBase lo
// devuelve como objeto o como string segun el esquema, asi que se normaliza en
// un solo sitio en vez de repetir el try/catch en cada metodo.
function readJson(record) {
  const raw = record?.json
  if (!raw) return {}
  if (typeof raw !== 'string') return raw
  try { return JSON.parse(raw) } catch { return {} }
}

function mapRecord(item) {
  const parsed = readJson(item)
  const files = item.files || []
  return {
    id: item.id,
    slug: parsed.slug || item.id,
    name: parsed.name || item.id,
    status: parsed.status || 'pending',
    listo: parsed.listo || false,
    settings: parsed.settings || {},
    project_type: parsed.project_type || 'space',
    // Publicados por el worker: perfil de hardware detectado, etapa actual
    // del pipeline y aviso de degradacion (p.ej. el 360 no cupo en la GPU).
    hw: parsed.hw || null,
    stage: parsed.stage || null,
    degraded: parsed.degraded || null,
    created: item.created,
    thumb: files.length ? fileUrlOf(item, files[0]) : '',
    files: files.map(f => fileUrlOf(item, f)),
    _raw: files,
  }
}

// Lee-modifica-escribe sobre el blob `json`. Se releé SIEMPRE justo antes de
// escribir para reducir la ventana en la que el worker (que escribe status y
// stage en el mismo campo) pueda quedar pisado.
async function patchJson(id, mutate) {
  const current = await col().getOne(id, { requestKey: null })
  const next = mutate(readJson(current))
  return col().update(id, { json: JSON.stringify(next) })
}

export const api = {
  async getProjects() {
    // requestKey: null desactiva la auto-cancelacion del SDK. Sin esto, dos
    // vistas pidiendo la lista a la vez (o un refresco solapado) abortan la
    // peticion anterior con ClientResponseError 0.
    const items = await col().getFullList({
      sort: '-created', batch: 100, requestKey: null,
    })
    return items.map(mapRecord)
  },

  async getProject(id) {
    const item = await col().getOne(id, { requestKey: null })
    return item ? mapRecord(item) : null
  },

  // Suscripcion en tiempo real (SSE). Sustituye al sondeo cada 4-5 s: el
  // cambio de etapa del worker se ve al instante y desaparecen ~700 peticiones
  // por hora y pestana abierta.
  // Devuelve una funcion para cancelar.
  subscribeProjects(onChange) {
    let unsub = null
    let cancelled = false
    col().subscribe('*', (e) => onChange(e.action, e.record ? mapRecord(e.record) : null),
                    { requestKey: null })
      .then(fn => { if (cancelled) fn(); else unsub = fn })
      .catch(err => console.warn('[HYWorld] realtime no disponible:', err?.message || err))
    return () => {
      cancelled = true
      if (unsub) { try { unsub() } catch { /* ya desconectado */ } }
    }
  },

  async createProject(name, files, inputType = 'image', projectType = 'space') {
    const slug = generateSlug(name)
    const jsonData = {
      name, slug, status: 'pending', listo: false,
      input_type: inputType,
      project_type: projectType,
      created: new Date().toISOString(),
    }
    const formData = new FormData()
    formData.append('json', JSON.stringify(jsonData))
    for (const f of files) formData.append('files', f)
    return col().create(formData)
  },

  updateProjectStatus(id, listo) {
    // ON => el proyecto queda 'pending' (a la espera del worker, aunque no este activo)
    return patchJson(id, p => ({
      ...p, listo,
      status: listo ? 'pending' : (p.status === 'processing' ? 'processing' : p.status || 'pending'),
    }))
  },

  generateMesh(id) {
    // Se respetan los settings del proyecto TAL CUAL.
    //
    // Antes se pisaban aqui con target_size/max_resolution/save_gs al maximo en
    // CADA click de Generate, asi que los presets no hacian nada: eligieras
    // Minima o Media, siempre se enviaba Maxima. Esa era la causa principal de
    // los OOM en GPUs chicas. Quien acota ahora es el worker, contra el perfil
    // de hardware real (hw_profile.clamp_settings_to_profile).
    return patchJson(id, p => ({
      ...p,
      settings: {
        quality: 'max',                  // preset por defecto si nunca se eligio
        ...(p.settings || {}),
        apply_sky_mask: true, apply_edge_mask: true, save_points: true,
      },
      mesh: true, regenerate: true, status: 'pending',
      stage: null, degraded: null,
      triggered_at: new Date().toISOString(),
    }))
  },

  regenerate(id) {
    return patchJson(id, p => ({
      ...p, regenerate: true, status: 'pending',
      stage: null, degraded: null,
      triggered_at: new Date().toISOString(),
    }))
  },

  updateProjectSettings(id, settings) {
    return patchJson(id, p => ({ ...p, settings }))
  },

  triggerProcessing(id) {
    return patchJson(id, p => ({
      ...p, status: 'processing', triggered_at: new Date().toISOString(),
    }))
  },

  async uploadImages(id, files) {
    const formData = new FormData()
    for (const f of files) formData.append('files', f)
    return col().update(id, formData)
  },

  deleteProject(id) {
    return col().delete(id)
  },

  deleteFile(id, filename) {
    // PocketBase: "files-" elimina un archivo concreto del campo multi-archivo
    return col().update(id, { 'files-': [filename] })
  },

  fileUrl(recordId, filename) {
    return pb.files.getURL({ id: recordId, collectionId: COLLECTION, collectionName: COLLECTION }, filename)
  },
}
