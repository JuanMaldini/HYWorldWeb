import { useState, useEffect } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../lib/pocketbase'
import '../App.css'

export default function Dashboard({ user, onLogout }) {
  const [projects, setProjects] = useState([])
  const [loading, setLoading] = useState(true)
  const [showModal, setShowModal] = useState(false)
  const [newName, setNewName] = useState('')
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

  const createProject = async () => {
    if (!newName.trim()) return
    try {
      const data = await api.createProject(newName.trim())
      setShowModal(false)
      setNewName('')
      navigate(`/project/${data.id}`)
    } catch (err) {
      console.error('Failed to create project:', err)
    }
  }

  return (
    <div>
      <div className="topbar">
        <div className="topbar-logo">HY<span>World</span></div>
        <div className="topbar-user">
          {user?.email}
          <Link to="/login" onClick={onLogout}>Logout</Link>
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
              <div key={p.id} className="project-card" onClick={() => navigate(`/project/${p.id}`)}>
                {p.image ? (
                  <img className="project-thumb" src={p.image} alt={p.name} />
                ) : (
                  <div className="project-thumb-placeholder">🏗</div>
                )}
                <div className="project-body">
                  <div className="project-name">{p.name}</div>
                  <div className="project-meta">
                    <span className={`status status-${p.status}`}>{p.status}</span>
                    <span>{p.input_count} images</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {showModal && (
        <div className="modal-overlay" onClick={() => setShowModal(false)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <h2 style={{ fontSize: 18, marginBottom: 20 }}>New Project</h2>
            <input
              type="text"
              placeholder="Project name..."
              value={newName}
              onChange={e => setNewName(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && createProject()}
              autoFocus
              style={{
                width: '100%',
                background: '#1a1a24',
                border: '1px solid var(--border)',
                borderRadius: 8,
                padding: '12px 16px',
                color: '#fff',
                fontSize: 14,
                outline: 'none',
                marginBottom: 16,
              }}
            />
            <div style={{ display: 'flex', gap: 12, justifyContent: 'flex-end' }}>
              <button className="btn btn-outline" onClick={() => setShowModal(false)}>Cancel</button>
              <button className="btn" onClick={createProject}>Create</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}