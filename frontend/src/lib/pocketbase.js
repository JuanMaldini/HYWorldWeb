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

// Generate slug: name-abc1
function generateSlug(name) {
  const clean = name.toLowerCase().trim().replace(/\s+/g, '-').replace(/[^a-z0-9-]/g, '')
  const rand = Math.random().toString(36).substring(2, 6)
  return `${clean}_${rand}`
}

// Save token on login
export const saveToken = (token) => localStorage.setItem('pb_token', token)
export const getToken = () => localStorage.getItem('pb_token') || ''

// PB direct calls
async function pbFetch(path, opts = {}) {
  const token = getToken()
  const base = import.meta.env.VITE_PB_URL || import.meta.env.VITE_PB_URL_LOCAL || ''
  const res = await fetch(`${base}${path}`, {
    ...opts,
    headers: {
      ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
      ...(opts.body && !(opts.body instanceof FormData) ? { 'Content-Type': 'application/json' } : {}),
      ...opts.headers,
    },
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export const api = {
  // List all projects
  async getProjects() {
    const data = await pbFetch('/api/collections/hyworld_data/records?sort=-created&perPage=100')
    return data.items.map(item => ({
      id: item.id,
      slug: JSON.parse(item.json || '{}').slug || item.id,
      name: JSON.parse(item.json || '{}').name || item.id,
      status: JSON.parse(item.json || '{}').status || 'pending',
      created: item.created,
      thumb: item.files?.length > 0 ? `${import.meta.env.VITE_PB_URL || import.meta.env.VITE_PB_URL_LOCAL}/api/files/hyworld_data/${item.id}/${item.files[0]}` : '',
    }))
  },

  // Create project (name + images required)
  async createProject(name, files) {
    const slug = generateSlug(name)
    const jsonData = JSON.stringify({ name, slug, status: 'pending', created: new Date().toISOString() })

    // Create record with files in single request
    const formData = new FormData()
    formData.append('json', jsonData)
    for (const f of files) formData.append('files', f)

    const data = await pbFetch('/api/collections/hyworld_data/records', {
      method: 'POST',
      body: formData,
    })
    return data
  },

  // Get single project
  async getProject(id) {
    const item = await pbFetch(`/api/collections/hyworld_data/records/${id}`)
    return {
      id: item.id,
      slug: JSON.parse(item.json || '{}').slug || item.id,
      name: JSON.parse(item.json || '{}').name || item.id,
      status: JSON.parse(item.json || '{}').status || 'pending',
      files: item.files || [],
      created: item.created,
    }
  },

  // Mark project as processing (trigger)
  async triggerProcessing(id) {
    return pbFetch(`/api/collections/hyworld_data/records/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ json: JSON.stringify({ status: 'processing', triggered_at: new Date().toISOString() }) }),
    })
  },

  // Upload more images to existing project
  async uploadImages(id, files) {
    const formData = new FormData()
    for (const f of files) formData.append('files', f)
    return pbFetch(`/api/collections/hyworld_data/records/${id}`, {
      method: 'PATCH',
      body: formData,
    })
  },

  // File URL helper
  fileUrl(recordId, filename) {
    const base = import.meta.env.VITE_PB_URL || import.meta.env.VITE_PB_URL_LOCAL || ''
    return `${base}/api/files/hyworld_data/${recordId}/${filename}`
  },
}