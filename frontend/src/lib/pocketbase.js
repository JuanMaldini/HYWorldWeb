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

export const api = {
  async getProjects() {
    const base = import.meta.env.VITE_PB_URL || import.meta.env.VITE_PB_URL_LOCAL
    const token = localStorage.getItem('pb_token') || ''
    
    if (base) {
      // Production or local PocketBase — query directly
      const r = await fetch(`${base}/api/collections/hyworld_data/records?sort=-created&perPage=100`, {
        headers: { 'Authorization': `Bearer ${token}` }
      })
      if (r.ok) {
        const data = await r.json()
        return data.items.map(item => ({
          id: item.id,
          name: JSON.parse(item.json || '{}').name || item.id,
          status: JSON.parse(item.json || '{}').status || 'pending',
          created: item.created,
          input_count: 0,
        }))
      }
      return []
    } else {
      // Local dev via Flask
      const r = await fetch('/api/projects')
      return r.json()
    }
  },

  async createProject(name) {
    const base = import.meta.env.VITE_PB_URL || import.meta.env.VITE_PB_URL_LOCAL
    const token = localStorage.getItem('pb_token') || ''
    
    if (base) {
      const r = await fetch(`${base}/api/collections/hyworld_data/records`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({
          json: JSON.stringify({ name, status: 'pending', created: new Date().toISOString() })
        })
      })
      if (r.ok) {
        const data = await r.json()
        return { id: data.id, name, status: 'pending' }
      }
      throw new Error('Failed to create project')
    }
    // Local dev via Flask
    const r = await fetch('/project/new', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: `name=${encodeURIComponent(name)}`,
    })
    return r.json()
  },

  async getProject(pid) {
    return { id: pid }
  },

  async uploadImages(pid, files) {
    const base = import.meta.env.VITE_PB_URL || import.meta.env.VITE_PB_URL_LOCAL
    const token = localStorage.getItem('pb_token') || ''
    
    if (base) {
      const formData = new FormData()
      files.forEach(f => formData.append('images', f))
      const r = await fetch(`${base}/api/collections/hyworld_data/records/${pid}`, {
        method: 'PATCH',
        headers: { 'Authorization': `Bearer ${token}` },
        body: formData
      })
      return r.ok ? { uploaded: files.length } : { error: 'upload failed' }
    }
    const r = await fetch(`/project/${pid}/upload`, { method: 'POST', body: formData })
    return r.json()
  },

  async triggerProcessing(pid) {
    const base = import.meta.env.VITE_PB_URL || import.meta.env.VITE_PB_URL_LOCAL
    const token = localStorage.getItem('pb_token') || ''
    
    if (base) {
      const r = await fetch(`${base}/api/collections/hyworld_data/records/${pid}`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({
          json: JSON.stringify({ status: 'processing', triggered_at: new Date().toISOString() })
        })
      })
      return r.ok ? { status: 'processing' } : { error: 'failed' }
    }
    const r = await fetch(`/project/${pid}/trigger`, { method: 'POST' })
    return r.json()
  },

  async refreshStatus(pid) {
    return { status: 'unknown' }
  },
}

export const saveToken = (token) => {
  localStorage.setItem('pb_token', token)
}

export const getToken = () => localStorage.getItem('pb_token') || ''