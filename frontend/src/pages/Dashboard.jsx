import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../lib/pocketbase'
import '../App.css'

export default function Dashboard({ user, onLogout }) {
  const [projects, setProjects] = useState([])
  const [loading, setLoading] = useState(true)
  const [showModal, setShowModal] = useState(false)
  const [name, setName] = useState('')
  const [files, setFiles] = useState([])
  const [preview, setPreview] = useState(null)
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState('')
  const navigate = useNavigate()

  const fetchProjects = async () => {
    try {
      const data = await api.getProjects()
      setProjects(data)
    } catch (err) {
      console.error('Failed to fetch projects:', err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchProjects()
  }, [])

  const handleFileChange = (e) => {
    const selected = Array.from(e.target.files)
    if (selected.length > 0) {
      setFiles(selected)
      setPreview(URL.createObjectURL(selected[0]))
    }
  }

  const handleCreate = async () => {
    if (!name.trim()) { setError('Name is required'); return }
    if (files.length === 0) { setError('At least one image is required'); return }
    setError('')
    setCreating(true)
    try {
      const record = await api.createProject(name.trim(), files)
      const slug = JSON.parse(record.json || '{}').slug || record.id
      setShowModal(false)
      setName('')
      setFiles([])
      setPreview(null)
      navigate(`/p/${slug}`)
    } catch (err) {
      setError('Failed to create project. Try again.')
      console.error(err)
    } finally {
      setCreating(false)
    }
  }

  return (
    <div>
      <div className="topbar">
        <div className="topbar-logo">HY<span>World</span></div>
        <div className="topbar-user">
          {user?.email}
          <a href="/" onClick={onLogout}>Logout</a>
        </div>
      </div>

      <div className="container">
        <div className="dashboard-header">
          <h1>Projects</h1>
          <button className="btn" onClick={() => setShowModal(true)}>+ New Project</button>
        </div>

        {loading ? (
          <div className="empty-state"><div className="empty-icon">⏳</div></div>
        ) : projects.length === 0 ? (
          <div className="empty-state">
            <div className="empty-icon">📁</div>
            <h2>No projects yet</h2>
            <p>Create your first project to start reconstructing 3D worlds.</p>
          </div>
        ) : (
          <div className="project-grid">
            {projects.map(p => (
              <div key={p.id} className="project-card" onClick={() => navigate(`/p/${p.slug}`)}>
                {p.thumb ? (
                  <img className="project-thumb" src={p.thumb} alt={p.name} />
                ) : (
                  <div className="project-thumb-placeholder">🏗</div>
                )}
                <div className="project-body">
                  <div className="project-name">{p.name}</div>
                  <div className="project-meta">
                    <span className={`status status-${p.status}`}>{p.status}</span>
                    <span>{new Date(p.created).toLocaleDateString()}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Modal */}
      {showModal && (
        <div className="modal-overlay" onClick={() => setShowModal(false)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <h2 style={{ fontSize: 18, marginBottom: 20 }}>New Project</h2>

            {error && <div className="login-error" style={{ marginBottom: 16 }}>{error}</div>}

            <div className="form-group">
              <label>Project Name</label>
              <input
                type="text"
                value={name}
                onChange={e => setName(e.target.value)}
                placeholder="My 3D Scene"
                onKeyDown={e => e.key === 'Enter' && handleCreate()}
              />
            </div>

            <div className="form-group">
              <label>Cover Image (required)</label>
              <input type="file" accept="image/*" multiple onChange={handleFileChange} />
              {preview && (
                <img src={preview} alt="preview" style={{ marginTop: 12, width: '100%', borderRadius: 8, maxHeight: 160, objectFit: 'cover' }} />
              )}
            </div>

            <div style={{ display: 'flex', gap: 12, justifyContent: 'flex-end' }}>
              <button className="btn btn-outline" onClick={() => setShowModal(false)}>Cancel</button>
              <button className="btn" onClick={handleCreate} disabled={creating}>
                {creating ? 'Creating...' : 'Create Project'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}