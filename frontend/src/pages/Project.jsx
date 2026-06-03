import { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import { api } from '../lib/pocketbase'

export default function Project({ user }) {
  const { slug } = useParams()
  const [project, setProject] = useState(null)
  const [loading, setLoading] = useState(true)
  const [files, setFiles] = useState([])

  useEffect(() => {
    const load = async () => {
      try {
        const all = await api.getProjects()
        const found = all.find(p => p.slug === slug)
        if (found) {
          setProject(found)
          // Load file details
          const detail = await api.getProject(found.id)
          setFiles((detail.files || []).map(f => api.fileUrl(found.id, f)))
        }
      } catch (err) {
        console.error(err)
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [slug])

  if (loading) return <div style={{ color: '#fff', padding: 40 }}>Loading...</div>
  if (!project) return <div style={{ color: '#fff', padding: 40 }}>Project not found</div>

  return (
    <div>
      <div className="topbar" style={{ height: 56 }}>
        <Link to="/dashboard" style={{ color: 'var(--accent)', fontSize: 20, textDecoration: 'none' }}>←</Link>
        <h1 style={{ fontSize: 16, fontWeight: 600, flex: 1 }}>{project.name}</h1>
        <span className={`status status-${project.status}`}>{project.status}</span>
      </div>

      <div style={{ padding: 40, maxWidth: 1200, margin: '0 auto' }}>
        <div style={{ marginBottom: 24, color: '#888', fontSize: 13 }}>
          Slug: <code style={{ background: '#1a1a24', padding: '2px 8px', borderRadius: 4 }}>/p/{project.slug}</code>
          &nbsp;|&nbsp; Created: {new Date(project.created).toLocaleString()}
        </div>

        {files.length > 0 && (
          <div>
            <div className="section-title">Images ({files.length})</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 12 }}>
              {files.map((src, i) => (
                <img key={i} src={src} alt={`${project.name} ${i}`} style={{ width: '100%', borderRadius: 8, aspectRatio: '1', objectFit: 'cover', border: '1px solid var(--border)' }} />
              ))}
            </div>
          </div>
        )}

        {project.status === 'pending' && (
          <div style={{ marginTop: 32 }}>
            <button className="btn" onClick={async () => {
              await api.triggerProcessing(project.id)
              setProject(p => ({ ...p, status: 'processing' }))
            }}>
              🚀 Process
            </button>
          </div>
        )}
      </div>
    </div>
  )
}