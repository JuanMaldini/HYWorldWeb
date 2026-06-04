import PocketBase from 'pocketbase'

const PB_URL = import.meta.env.VITE_PB_URL || import.meta.env.VITE_PB_URL_LOCAL || 'http://localhost:8092'

export const pb = new PocketBase(PB_URL)

export const login = async (email, password) => {
  const authData = await pb.collection('hyworld_user').authWithPassword(email, password)
  return authData
}

export const logout = () => {
  pb.authStore.clear()
}

export const isAuthenticated = () => pb.authStore.isValid

export const getUser = () => pb.authStore.model

function generateSlug(name) {
  const clean = name.toLowerCase().trim().replace(/\s+/g, '-').replace(/[^a-z0-9-]/g, '')
  const rand = Math.random().toString(36).substring(2, 6)
  return `${clean}_${rand}`
}

export const saveToken = (token) => localStorage.setItem('pb_token', token)
export const getToken = () => localStorage.getItem('pb_token') || ''

async function pbFetch(path, opts = {}) {
  const base = PB_URL
  const token = getToken()
  const headers = {}
  if (token) headers['Authorization'] = `Bearer ${token}`
  if (opts.body && !(opts.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json'
  }
  const res = await fetch(`${base}${path}`, { ...opts, headers })
  const text = await res.text()
  if (!res.ok) throw new Error(`PB Error ${res.status}: ${text}`)
  if (!text) return null
  try { return JSON.parse(text) } catch { return text }
}

export const api = {
  async getProjects() {
    const data = await pbFetch('/api/collections/hyworld_data/records?sort=-created&perPage=100')
    if (!data?.items) return []
    return data.items.map(item => {
      let parsed = {}
      try { parsed = typeof item.json === 'string' ? JSON.parse(item.json) : item.json } catch {}
      const thumb = item.files?.length > 0
        ? `${PB_URL}/api/files/hyworld_data/${item.id}/${item.files[0]}`
        : ''
      return {
        id: item.id,
        slug: parsed.slug || item.id,
        name: parsed.name || item.id,
        status: parsed.status || 'pending',
        listo: parsed.listo || false,
        settings: parsed.settings || {},
        created: item.created,
        thumb,
        files: (item.files || []).map(f => `${PB_URL}/api/files/hyworld_data/${item.id}/${f}`),
      }
    })
  },

  async createProject(name, files) {
    const slug = generateSlug(name)
    const jsonData = { name, slug, status: 'pending', listo: false, created: new Date().toISOString() }
    const formData = new FormData()
    formData.append('json', JSON.stringify(jsonData))
    for (const f of files) formData.append('files', f)
    return pbFetch('/api/collections/hyworld_data/records', { method: 'POST', body: formData })
  },

  async getProject(id) {
    const item = await pbFetch(`/api/collections/hyworld_data/records/${id}`)
    if (!item) return null
    let parsed = {}
    try { parsed = typeof item.json === 'string' ? JSON.parse(item.json) : item.json } catch {}
    return {
      id: item.id,
      slug: parsed.slug || item.id,
      name: parsed.name || item.id,
      status: parsed.status || 'pending',
      listo: parsed.listo || false,
      settings: parsed.settings || {},
      files: (item.files || []).map(f => `${PB_URL}/api/files/hyworld_data/${item.id}/${f}`),
      created: item.created,
      _raw: item.files || [],
    }
  },

  async updateProjectStatus(id, listo) {
    let parsed = {}
    try {
      const current = await pbFetch(`/api/collections/hyworld_data/records/${id}`)
      parsed = typeof current.json === 'string' ? JSON.parse(current.json) : current.json
    } catch {}
    const jsonData = { ...parsed, listo }
    return pbFetch(`/api/collections/hyworld_data/records/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ json: JSON.stringify(jsonData) }),
    })
  },

  async generateMesh(id) {
    let parsed = {}
    try {
      const current = await pbFetch(`/api/collections/hyworld_data/records/${id}`)
      parsed = typeof current.json === 'string' ? JSON.parse(current.json) : current.json
    } catch {}
    // Calidad maxima fija para la malla final
    const maxSettings = {
      ...(parsed.settings || {}),
      target_size: 1120, max_resolution: 2560,
      apply_sky_mask: true, apply_edge_mask: true,
      save_gs: true, save_points: true,
    }
    const jsonData = { ...parsed, settings: maxSettings, mesh: true, regenerate: true, status: 'pending', triggered_at: new Date().toISOString() }
    console.debug('[HYWorld] generateMesh', id, jsonData)
    return pbFetch(`/api/collections/hyworld_data/records/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ json: JSON.stringify(jsonData) }),
    })
  },

  async regenerate(id) {
    let parsed = {}
    try {
      const current = await pbFetch(`/api/collections/hyworld_data/records/${id}`)
      parsed = typeof current.json === 'string' ? JSON.parse(current.json) : current.json
    } catch {}
    const jsonData = { ...parsed, regenerate: true, status: 'pending', triggered_at: new Date().toISOString() }
    console.debug('[HYWorld] regenerate', id, jsonData)
    return pbFetch(`/api/collections/hyworld_data/records/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ json: JSON.stringify(jsonData) }),
    })
  },

  async updateProjectSettings(id, settings) {
    let parsed = {}
    try {
      const current = await pbFetch(`/api/collections/hyworld_data/records/${id}`)
      parsed = typeof current.json === 'string' ? JSON.parse(current.json) : current.json
    } catch {}
    const jsonData = { ...parsed, settings }
    return pbFetch(`/api/collections/hyworld_data/records/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ json: JSON.stringify(jsonData) }),
    })
  },

  async triggerProcessing(id) {
    let parsed = {}
    try {
      const current = await pbFetch(`/api/collections/hyworld_data/records/${id}`)
      parsed = typeof current.json === 'string' ? JSON.parse(current.json) : current.json
    } catch {}
    const jsonData = { ...parsed, status: 'processing', triggered_at: new Date().toISOString() }
    return pbFetch(`/api/collections/hyworld_data/records/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ json: JSON.stringify(jsonData) }),
    })
  },

  async uploadImages(id, files) {
    const formData = new FormData()
    for (const f of files) formData.append('files', f)
    return pbFetch(`/api/collections/hyworld_data/records/${id}`, { method: 'PATCH', body: formData })
  },

  async deleteProject(id) {
    return pbFetch(`/api/collections/hyworld_data/records/${id}`, { method: 'DELETE' })
  },

  fileUrl(recordId, filename) {
    return `${PB_URL}/api/files/hyworld_data/${recordId}/${filename}`
  },
}