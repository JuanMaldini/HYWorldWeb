import PocketBase from 'pocketbase'

const PB_URL = import.meta.env.VITE_PB_URL || 'http://localhost:8092'

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
  // Projects (local via Flask)
  async getProjects() {
    const r = await fetch('/api/projects')
    return r.json()
  },

  async createProject(name) {
    const r = await fetch('/project/new', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: `name=${encodeURIComponent(name)}`,
    })
    return r.json()
  },

  async getProject(pid) {
    const r = await fetch(`/project/${pid}`)
    return r
  },

  async uploadImages(pid, files) {
    const formData = new FormData()
    files.forEach(f => formData.append('images', f))
    const r = await fetch(`/project/${pid}/upload`, { method: 'POST', body: formData })
    return r.json()
  },

  async triggerProcessing(pid) {
    const r = await fetch(`/project/${pid}/trigger`, { method: 'POST' })
    return r.json()
  },

  async refreshStatus(pid) {
    const r = await fetch(`/project/${pid}/refresh`, { method: 'POST' })
    return r.json()
  },
}