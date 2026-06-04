import { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import { api } from '../lib/pocketbase'

export default function Project({ user }) {
  const { slug } = useParams()
  const [project, setProject] = useState(null)
  const [loading, setLoading] = useState(true)
  const [updating, setUpdating] = useState(false)

  useEffect(() => {
    const load = async () => {
      try {
        const all = await api.getProjects()
        const found = all.find(p => p.slug === slug)
        if (found) {
          const detail = await api.getProject(found.id)
          setProject({ ...found, files: detail.files })
        }
      } catch (err) {
        console.error(err)
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [slug])

  const toggleListo = async () => {
    if (!project) return
    setUpdating(true)
    try {
      await api.updateProjectStatus(project.id, !project.listo)
      setProject(p => ({ ...p, listo: !p.listo }))
    } catch (err) {
      console.error(err)
    } finally {
      setUpdating(false)
    }
  }

  if (loading) return (
    <div style={{ color: 'var(--text)', padding: 40, textAlign: 'center' }}>
      <div style={{ fontSize: 32, marginBottom: 16 }}>⏳</div>
      <div>Loading...</div>
    </div>
  )

  if (!project) return (
    <div style={{ color: 'var(--text)', padding: 40, textAlign: 'center' }}>
      <div style={{ fontSize: 32, marginBottom: 16 }}>❌</div>
      <div>Project not found</div>
      <Link to="/dashboard" style={{ color: 'var(--accent)', display: 'block', marginTop: 16 }}>← Back</Link>
    </div>
  )

  return (
    <div>
      <div className="topbar" style={{ height: 56 }}>
        <Link to="/dashboard" style={{ color: 'var(--accent)', fontSize: 20, textDecoration: 'none' }}>←</Link>
        <h1 style={{ fontSize: 16, fontWeight: 600, flex: 1 }}>{project.name}</h1>
        <span className={`status status-${project.status}`}>{project.status}</span>
      </div>

      <div style={{ padding: '32px 40px', maxWidth: 1200, margin: '0 auto' }}>
        {/* Meta info */}
        <div style={{ color: 'var(--text-dim)', fontSize: 13, marginBottom: 32 }}>
          Slug: <code style={{ background: 'var(--bg-dark)', padding: '2px 8px', borderRadius: 4 }}>/p/{project.slug}</code>
          &nbsp;|&nbsp; Created: {new Date(project.created).toLocaleString()}
        </div>

        {/* Listo toggle */}
        <div style={{
          background: 'var(--surface)',
          border: '1px solid var(--border)',
          borderRadius: 12,
          padding: '20px 24px',
          marginBottom: 32,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          maxWidth: 480,
        }}>
          <div>
            <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 4 }}>¿Listo para procesar?</div>
            <div style={{ fontSize: 13, color: 'var(--text-dim)' }}>
              {project.listo
                ? '✅ Proyecto listo — el worker local lo procesará'
                : '⏳ Pendiente — activa cuando quieras que empiece el procesamiento'}
            </div>
          </div>
          <button
            onClick={toggleListo}
            disabled={updating}
            style={{
              background: project.listo ? '#1d2b1a' : 'var(--bg-dark)',
              border: `1px solid ${project.listo ? 'var(--success)' : 'var(--border)'}`,
              borderRadius: 8,
              padding: '10px 24px',
              fontSize: 13,
              fontWeight: 600,
              color: project.listo ? 'var(--success)' : 'var(--text-dim)',
              cursor: updating ? 'not-allowed' : 'pointer',
              opacity: updating ? 0.6 : 1,
              transition: 'all 0.2s',
            }}
          >
            {updating ? '...' : project.listo ? 'ON' : 'OFF'}
          </button>
        </div>

        {/* Images */}
        {project.files?.length > 0 && (
          <div>
            <div style={{ fontSize: 11, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: 16 }}>
              Images ({project.files.length})
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 12 }}>
              {project.files.map((src, i) => (
                <img
                  key={i}
                  src={src}
                  alt={`${project.name} ${i}`}
                  onError={e => { e.target.style.display = 'none' }}
                  style={{
                    width: '100%',
                    borderRadius: 8,
                    aspectRatio: '1',
                    objectFit: 'cover',
                    border: '1px solid var(--border)',
                  }}
                />
              ))}
            </div>
          </div>
        )}

        {/* No images */}
        {(!project.files || project.files.length === 0) && (
          <div style={{ color: 'var(--text-faint)', textAlign: 'center', padding: 40 }}>
            No images yet
          </div>
        )}
      </div>
    </div>
  )
}