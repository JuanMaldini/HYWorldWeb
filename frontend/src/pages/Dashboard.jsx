import { useState, useEffect } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { api } from '../lib/pocketbase'
import '../App.css'

export default function Dashboard({ user, onLogout, onLogin }) {
  const [projects, setProjects] = useState([])
  const [loading, setLoading] = useState(true)
  const [showModal, setShowModal] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState(null)
  const [files, setFiles] = useState([])
  const [preview, setPreview] = useState(null)
  const [fileType, setFileType] = useState(null)
  const [projectType, setProjectType] = useState(null)
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState('')
  const [dragOver, setDragOver] = useState(false)
  const [deleting, setDeleting] = useState(false)
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
    const t = setInterval(fetchProjects, 5000)
    return () => clearInterval(t)
  }, [])

  const handleFileChange = (selected) => {
    if (!selected.length) return
    const f = selected[0]
    const isPly = f.name.toLowerCase().endsWith('.ply')
    setFiles(selected)
    setFileType(isPly ? 'ply' : 'image')
    setPreview(isPly ? null : URL.createObjectURL(f))
    setError('')
  }

  const handleDrop = (e) => {
    e.preventDefault()
    setDragOver(false)
    const all = Array.from(e.dataTransfer.files)
    const selected = all.filter(f =>
      f.type.startsWith('image/') || f.name.toLowerCase().endsWith('.ply')
    )
    handleFileChange(selected)
  }

  const handleCreate = async () => {
    if (!projectType) { setError('Seleccioná Generate Space o Generate Asset'); return }
    if (files.length === 0) { setError('Se requiere una imagen' + (projectType === 'space' ? ' o archivo .ply' : '')); return }
    setError('')
    setCreating(true)
    try {
      const firstFile = files[0]
      const record = await api.createProject(firstFile.name, files, fileType === 'ply' ? 'ply' : 'image', projectType)
      const slug = (() => {
        try {
          const j = typeof record.json === 'string' ? JSON.parse(record.json) : record.json
          return j.slug || record.id
        } catch { return record.id }
      })()
      setShowModal(false)
      setFiles([])
      setPreview(null)
      navigate(`/p/${slug}`)
    } catch (err) {
      console.error(err)
      setError('Failed to create project. Please try again.')
    } finally {
      setCreating(false)
    }
  }

  const closeModal = () => {
    setShowModal(false)
    setFiles([])
    setPreview(null)
    setFileType(null)
    setProjectType(null)
    setError('')
  }

  const handleDelete = async () => {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      await api.deleteProject(deleteTarget.id)
      setProjects(ps => ps.filter(p => p.id !== deleteTarget.id))
      setDeleteTarget(null)
    } catch (err) {
      console.error(err)
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div>
      {/* Topbar */}
      <div className="topbar">
        <div className="topbar-logo">HY<span>World</span></div>
        <div className="topbar-user">
          {user ? (
            <>
              <span>{user.email}</span>
              <button
                onClick={onLogout}
                style={{ background: 'none', border: '1px solid var(--border)', color: 'var(--text-dim)', cursor: 'pointer', marginLeft: 16, fontSize: 12, padding: '5px 14px', borderRadius: 7 }}
              >
                Logout
              </button>
            </>
          ) : (
            <Link
              to="/login"
              style={{ background: 'var(--accent)', color: 'var(--bg-dark)', border: 'none', padding: '6px 18px', borderRadius: 7, fontSize: 13, fontWeight: 600, textDecoration: 'none' }}
            >
              Login
            </Link>
          )}
        </div>
      </div>

      <div className="container">
        {/* Hero */}
        <div className="hero-banner">
          <div className="hero-icon">🌍</div>
          <div className="hero-text">
            <strong>HYWorld</strong> — Reconstruction 3D desde una imagen o nube de puntos.
            Genera espacios panorámicos o assets digitales en segundos.
          </div>
          <a
            href="https://github.com/Tencent-Hunyuan/HY-World-2.0"
            target="_blank"
            rel="noopener noreferrer"
            className="hero-link"
          >
            🔗 GitHub
          </a>
        </div>

        <div className="dashboard-header">
          <h1>Projects</h1>
          {user && (
            <button className="btn" onClick={() => setShowModal(true)}>+ New Project</button>
          )}
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
                  <div className="card-header">
                    <div className="project-name">{p.name}</div>
                    {user && (
                      <button
                        className="btn-delete"
                        onClick={(e) => { e.stopPropagation(); setDeleteTarget(p) }}
                        title="Delete project"
                      >🗑</button>
                    )}
                  </div>
                  <div className="project-meta">
                    <Status s={p.status} />
                    <span>{new Date(p.created).toLocaleDateString()}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Delete confirmation popup */}
      {deleteTarget && (
        <div className="modal-overlay" onClick={() => !deleting && setDeleteTarget(null)}>
          <div className="modal" onClick={e => e.stopPropagation()} style={{ maxWidth: 380 }}>
            <div style={{ textAlign: 'center', marginBottom: 24 }}>
              <div style={{ fontSize: 36, marginBottom: 12 }}>⚠️</div>
              <h2 style={{ fontSize: 18, marginBottom: 8 }}>Delete Project?</h2>
              <p style={{ color: 'var(--text-dim)', fontSize: 14 }}>
                <strong>{deleteTarget.name}</strong> will be permanently deleted. This cannot be undone.
              </p>
            </div>
            <div style={{ display: 'flex', gap: 12 }}>
              <button
                className="btn btn-outline"
                onClick={() => setDeleteTarget(null)}
                disabled={deleting}
                style={{ flex: 1 }}
              >
                Cancel
              </button>
              <button
                onClick={handleDelete}
                disabled={deleting}
                style={{
                  flex: 1,
                  background: 'var(--accent)',
                  color: 'var(--bg-dark)',
                  border: 'none',
                  borderRadius: 8,
                  padding: '12px 20px',
                  fontSize: 14,
                  fontWeight: 600,
                  cursor: deleting ? 'not-allowed' : 'pointer',
                  opacity: deleting ? 0.6 : 1,
                }}
              >
                {deleting ? 'Deleting...' : 'Delete'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal */}
      {showModal && (
        <div className="modal-overlay" onClick={closeModal}>
          <div className="modal" onClick={e => e.stopPropagation()}>

            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
              <h2 style={{ fontSize: 18, fontWeight: 600 }}>New Project</h2>
              <button onClick={closeModal} style={{ background: 'none', border: 'none', color: 'var(--text-dim)', fontSize: 20, cursor: 'pointer' }}>✕</button>
            </div>

            {error && (
              <div style={{ background: '#2d1b26', border: '1px solid #5a2a3a', borderRadius: 8, padding: '10px 14px', color: 'var(--danger)', fontSize: 13, marginBottom: 16 }}>
                {error}
              </div>
            )}

            {/* ── Tipo de proyecto ── */}
            <div style={{ marginBottom: 20 }}>
              <label style={{ display: 'block', fontSize: 12, color: 'var(--text-dim)', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                Tipo <span style={{ color: 'var(--accent)' }}>*</span>
              </label>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                {[
                  { key: 'space', icon: '🌍', label: 'Generate Space', desc: 'Panorama 3D desde imagen' },
                  { key: 'asset', icon: '🧊', label: 'Generate Asset', desc: 'Objeto 3D desde imagen' },
                ].map(({ key, icon, label, desc }) => (
                  <button
                    key={key}
                    onClick={() => { setProjectType(key); setFiles([]); setPreview(null); setFileType(null); setError('') }}
                    style={{
                      background: projectType === key ? 'var(--surface-2, #1e2a1e)' : 'var(--bg-dark)',
                      border: `2px solid ${projectType === key ? 'var(--accent)' : 'var(--border)'}`,
                      borderRadius: 10, padding: '14px 12px', cursor: 'pointer',
                      textAlign: 'left', transition: 'all 0.15s',
                    }}
                  >
                    <div style={{ fontSize: 22, marginBottom: 4 }}>{icon}</div>
                    <div style={{ fontSize: 13, fontWeight: 600, color: projectType === key ? 'var(--accent)' : 'var(--text)' }}>{label}</div>
                    <div style={{ fontSize: 11, color: 'var(--text-faint)', marginTop: 2 }}>{desc}</div>
                  </button>
                ))}
              </div>
            </div>

            {/* ── Archivo (solo si se eligió tipo) ── */}
            {projectType && (
            <div style={{ marginBottom: 24 }}>
              <label style={{ display: 'block', fontSize: 12, color: 'var(--text-dim)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                Archivo <span style={{ color: 'var(--accent)' }}>*</span>
              </label>

              {!files.length ? (
                <div
                  onDragOver={e => { e.preventDefault(); setDragOver(true) }}
                  onDragLeave={() => setDragOver(false)}
                  onDrop={handleDrop}
                  onClick={() => document.getElementById('fileInput').click()}
                  style={{
                    border: `2px dashed ${dragOver ? 'var(--accent)' : 'var(--border)'}`,
                    borderRadius: 12,
                    padding: 32,
                    textAlign: 'center',
                    cursor: 'pointer',
                    background: dragOver ? 'var(--surface-2)' : 'transparent',
                    transition: 'all 0.2s',
                  }}
                >
                  <div style={{ fontSize: 32, marginBottom: 8 }}>📁</div>
                  <div style={{ fontSize: 13, color: 'var(--text-dim)' }}>
                    Drag & drop o <span style={{ color: 'var(--accent)' }}>seleccionar</span>
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--text-faint)', marginTop: 4 }}>
                    Imagen (PNG, JPG, WEBP) · o nube de puntos (.ply)
                  </div>
                  <input
                    id="fileInput"
                    type="file"
                    accept={projectType === 'asset' ? 'image/*' : 'image/*,.ply'}
                    onChange={e => handleFileChange(Array.from(e.target.files))}
                    style={{ display: 'none' }}
                  />
                </div>
              ) : fileType === 'ply' ? (
                <div style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  background: 'var(--bg-dark)', border: '1px solid var(--accent)',
                  borderRadius: 10, padding: '14px 18px',
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <span style={{ fontSize: 22 }}>🗂</span>
                    <div>
                      <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', fontFamily: 'monospace' }}>
                        {files[0].name}
                      </div>
                      <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 2 }}>
                        {(files[0].size / 1e6).toFixed(1)} MB · nube de puntos
                      </div>
                    </div>
                  </div>
                  <button
                    onClick={() => { setFiles([]); setFileType(null) }}
                    style={{ background: 'none', border: '1px solid var(--border)', borderRadius: 6, color: 'var(--text-dim)', cursor: 'pointer', padding: '4px 10px', fontSize: 12 }}
                  >Quitar</button>
                </div>
              ) : (
                <div style={{ position: 'relative' }}>
                  <img src={preview} alt="preview" style={{ width: '100%', height: 180, objectFit: 'cover', borderRadius: 8 }} />
                  <button
                    onClick={() => { setFiles([]); setPreview(null); setFileType(null) }}
                    style={{
                      position: 'absolute', top: 8, right: 8,
                      background: 'var(--bg-dark)', border: '1px solid var(--border)',
                      borderRadius: 6, color: 'var(--text-dim)', cursor: 'pointer',
                      padding: '4px 8px', fontSize: 12,
                    }}
                  >Quitar</button>
                </div>
              )}
            </div>
            )}

            <div style={{ display: 'flex', gap: 12, justifyContent: 'flex-end' }}>
              <button
                className="btn btn-outline"
                onClick={closeModal}
                disabled={creating}
              >
                Cancel
              </button>
              <button
                className="btn"
                onClick={handleCreate}
                disabled={creating || !projectType}
              >
                {creating ? 'Creating...' : 'Create Project'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function Status({ s }) {
  const map = {
    pending:    ['En espera', 'dot-wait'],
    processing: ['Generando', 'dot-proc'],
    completed:  ['Listo', ''],
    error:      ['Error', ''],
  }
  const [label, dot] = map[s] || [s, '']
  return (
    <span className={`status status-${s}`}>
      {dot && <span className={`dot ${dot}`} />}{label}
    </span>
  )
}