import { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import { api } from '../lib/pocketbase'
import Viewer3D from '../components/Viewer3D'
import Viewer360 from '../components/Viewer360'

export default function Project({ user }) {
  const { slug } = useParams()
  const [project, setProject] = useState(null)
  const [loading, setLoading] = useState(true)
  const [updating, setUpdating] = useState(false)
  const [viewUrl, setViewUrl] = useState(null)
  const [view360Url, setView360Url] = useState(null)
  const [settings, setSettings] = useState({})
  const [gen, setGen] = useState(false)
  const [deleteFileTarget, setDeleteFileTarget] = useState(null) // { url, filename }
  const [deletingFile, setDeletingFile] = useState(false)

  useEffect(() => {
    const load = async () => {
      try {
        const all = await api.getProjects()
        const found = all.find(p => p.slug === slug)
        if (found) {
          const detail = await api.getProject(found.id)
          setProject({ ...found, files: detail.files })
          setSettings(detail.settings || found.settings || {})
        }
      } catch (err) {
        console.error(err)
      } finally {
        setLoading(false)
      }
    }
    load()
    const t = setInterval(async () => {
      try {
        const all = await api.getProjects()
        const found = all.find(p => p.slug === slug)
        if (found) {
          const d = await api.getProject(found.id)
          setProject(prev => prev ? { ...prev, status: found.status, listo: found.listo, files: d.files } : prev)
        }
      } catch (err) { /* silencioso */ }
    }, 4000)
    return () => clearInterval(t)
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

  const handleGenerate = async () => {
    setGen(true)
    try {
      await api.generateMesh(project.id)
      setProject(p => ({ ...p, status: 'pending' }))
    } catch (err) { console.error(err) }
    finally { setGen(false) }
  }

  const handleDeleteFile = async () => {
    if (!deleteFileTarget) return
    setDeletingFile(true)
    try {
      await api.deleteFile(project.id, deleteFileTarget.filename)
      setProject(p => ({ ...p, files: p.files.filter(f => f !== deleteFileTarget.url) }))
      setDeleteFileTarget(null)
    } catch (err) { console.error(err) }
    finally { setDeletingFile(false) }
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
      <Link to="/" style={{ color: 'var(--accent)', display: 'block', marginTop: 16 }}>← Back</Link>
    </div>
  )

  const sval = (k) => (settings[k] === undefined ? DEF[k] : settings[k])

  const isAsset = project.project_type === 'asset'

  const files = project.files || []
  const isImg = (u) => /\.(jpg|jpeg|png|webp)$/i.test(u.split('?')[0])
  const isModel = (u) => /\.(glb|gltf)$/i.test(u.split('?')[0])
  const isPano = (u) => isImg(u) && /_pano/i.test(decodeURIComponent(u.split('?')[0].split('/').pop()))
  const panos = files.filter(isPano)
  const imgs = files.filter(u => isImg(u) && !isPano(u))
  const outs = files.filter(isModel)

  return (
    <div>
      {/* Topbar */}
      <div className="topbar" style={{ height: 56 }}>
        <Link to="/" style={{ color: 'var(--accent)', fontSize: 20, textDecoration: 'none' }}>←</Link>
        <h1 style={{ fontSize: 16, fontWeight: 600, flex: 1 }}>{project.name}</h1>
        <span className={`status status-${project.status}`}>{project.status}</span>
        {user && (
          <button className="btn" onClick={handleGenerate}
            disabled={gen || project.status === 'processing' || project.status === 'pending'}
            style={{ marginLeft: 12 }}>
            {gen ? 'Enviando...' : project.status === 'processing' ? 'Generando...' : project.status === 'pending' ? 'En espera...' : 'Generate'}
          </button>
        )}
      </div>

      <div style={{ padding: '20px 40px', maxWidth: 1100, margin: '0 auto' }}>

        {/* Compact info strip */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          background: 'var(--surface)', border: '1px solid var(--border)',
          borderRadius: 10, padding: '10px 18px', marginBottom: 20,
          gap: 16,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap', minWidth: 0 }}>
            <span style={{ fontSize: 12, color: 'var(--text-dim)' }}>
              <span style={{ color: 'var(--text-faint)' }}>slug</span>{' '}
              <code style={{ background: 'var(--bg-dark)', padding: '2px 7px', borderRadius: 4, fontSize: 12, color: 'var(--text)' }}>
                /p/{project.slug}
              </code>
            </span>
          </div>

          {/* Listo toggle — solo si logueado */}
          {user && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexShrink: 0 }}>
              <span style={{ fontSize: 12, color: 'var(--text-dim)', whiteSpace: 'nowrap' }}>
                {project.listo ? '✅ Listo para procesar' : '⏳ En espera'}
              </span>
              <button
                onClick={toggleListo}
                disabled={updating}
                style={{
                  background: project.listo ? '#1d2b1a' : 'var(--bg-dark)',
                  border: `1px solid ${project.listo ? 'var(--success)' : 'var(--border)'}`,
                  borderRadius: 7,
                  padding: '6px 18px',
                  fontSize: 12,
                  fontWeight: 600,
                  color: project.listo ? 'var(--success)' : 'var(--text-dim)',
                  cursor: updating ? 'not-allowed' : 'pointer',
                  opacity: updating ? 0.6 : 1,
                  transition: 'all 0.2s',
                  whiteSpace: 'nowrap',
                }}
              >
                {updating ? '...' : project.listo ? 'ON' : 'OFF'}
              </button>
            </div>
          )}
        </div>

        {/* GenStatus */}
        <GenStatus status={project.status} hasPano={panos.length > 0} />

        {/* 2-column layout */}
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,340px) 1fr', gap: 24, alignItems: 'start' }}>

          {/* Left: Settings */}
          <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 12, padding: '18px 20px' }}>
            <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 14 }}>
              {isAsset ? 'Ajustes de asset' : 'Ajustes de reconstruccion'}
            </div>

            {isAsset ? (
              /* ── Asset settings: texture toggle ── */
              <>
                <div
                  onClick={async () => {
                    const newTex = !sval('texture')
                    const newSettings = { ...settings, texture: newTex }
                    setSettings(newSettings)
                    try { await api.updateProjectSettings(project.id, newSettings) } catch (e) { console.error(e) }
                  }}
                  style={{
                    display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12,
                    background: 'var(--bg-dark)',
                    border: `1px solid ${sval('texture') ? 'var(--accent)' : 'var(--border)'}`,
                    borderRadius: 8, padding: '12px 14px', cursor: 'pointer', userSelect: 'none',
                  }}
                >
                  <span>
                    <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)' }}>Textura</div>
                    <div style={{ fontSize: 12, color: 'var(--text-dim)', marginTop: 2 }}>
                      {sval('texture')
                        ? 'ON — GLB con colores reales (más lento)'
                        : 'OFF — solo geometría (más rápido)'}
                    </div>
                  </span>
                  <input type="checkbox" checked={!!sval('texture')} readOnly
                    style={{ width: 20, height: 20, accentColor: 'var(--accent)', flexShrink: 0 }} />
                </div>
                <div style={{ marginTop: 12, fontSize: 11, color: 'var(--text-faint)' }}>
                  Hunyuan3D-2 mini-turbo · objeto desde imagen
                </div>
              </>
            ) : (
              /* ── Space settings: 360 toggle (disabled) ── */
              <>
                <div style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12,
                  background: 'var(--bg-dark)', border: `1px solid ${sval('full_360') ? 'var(--accent)' : 'var(--border)'}`,
                  borderRadius: 8, padding: '12px 14px',
                  pointerEvents: 'none', opacity: 0.5, cursor: 'default', userSelect: 'none',
                }}>
                  <span>
                    <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)' }}>Generacion 360 completa</div>
                    <div style={{ fontSize: 12, color: 'var(--text-dim)', marginTop: 2 }}>
                      {sval('full_360')
                        ? 'ON — panorama 360 + multiview + GLB completo'
                        : 'OFF — solo imagen de frente'}
                    </div>
                  </span>
                  <input type="checkbox" checked={!!sval('full_360')} readOnly
                    style={{ width: 20, height: 20, accentColor: 'var(--accent)', flexShrink: 0 }} />
                </div>
                <div style={{ marginTop: 12, fontSize: 11, color: 'var(--text-faint)' }}>
                  Calidad máxima · Resolución máxima
                </div>
              </>
            )}
          </div>

          {/* Right: Output */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>

            {/* Panorama 360 */}
            {panos.length > 0 && (
              <div>
                <div style={{ fontSize: 11, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: 10 }}>
                  Vista 360
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {panos.map((src, i) => {
                    const rawName = src.split('/').pop()
                    const fname = decodeURIComponent(rawName.split('?')[0])
                    return (
                      <div key={i} style={{
                        display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12,
                        background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, padding: '11px 16px',
                      }}>
                        <span style={{ fontSize: 13, fontFamily: 'monospace', color: 'var(--text)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          🌐 {fname}
                        </span>
                        <span style={{ display: 'flex', gap: 12, flexShrink: 0, alignItems: 'center' }}>
                          <button onClick={() => setView360Url(src)}
                            style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 12, color: 'var(--cyan)', fontWeight: 600, padding: 0 }}>
                            Ver 360
                          </button>
                          <a href={src} download style={{ fontSize: 12, color: 'var(--accent)', fontWeight: 600, textDecoration: 'none' }}>
                            Descargar
                          </a>
                          {user && (
                            <button
                              onClick={() => setDeleteFileTarget({ url: src, filename: rawName.split('?')[0] })}
                              style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 12, color: 'var(--danger)', fontWeight: 600, padding: 0 }}
                              title="Eliminar panorama"
                            >
                              🗑
                            </button>
                          )}
                        </span>
                      </div>
                    )
                  })}
                </div>
              </div>
            )}

            {/* Models */}
            {outs.length > 0 && (
              <div>
                <div style={{ fontSize: 11, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: 10 }}>
                  Modelo 3D
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {outs.map((src, i) => {
                    const rawName = src.split('/').pop()
                    const fname = decodeURIComponent(rawName.split('?')[0])
                    return (
                      <div key={i} style={{
                        display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12,
                        background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, padding: '11px 16px',
                      }}>
                        <span style={{ fontSize: 13, fontFamily: 'monospace', color: 'var(--text)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {fname}
                        </span>
                        <span style={{ display: 'flex', gap: 12, flexShrink: 0, alignItems: 'center' }}>
                          <button onClick={() => setViewUrl(src)}
                            style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 12, color: 'var(--cyan)', fontWeight: 600, padding: 0 }}>
                            Ver
                          </button>
                          <a href={src} download style={{ fontSize: 12, color: 'var(--accent)', fontWeight: 600, textDecoration: 'none' }}>
                            Descargar
                          </a>
                          {user && (
                            <button
                              onClick={() => setDeleteFileTarget({ url: src, filename: rawName.split('?')[0] })}
                              style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 12, color: 'var(--danger)', fontWeight: 600, padding: 0 }}
                              title="Eliminar modelo"
                            >
                              🗑
                            </button>
                          )}
                        </span>
                      </div>
                    )
                  })}
                </div>
              </div>
            )}

            {/* Images */}
            {imgs.length > 0 && (
              <div>
                <div style={{ fontSize: 11, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: 10 }}>
                  Imágenes ({imgs.length})
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 8 }}>
                  {imgs.map((src, i) => (
                    <img key={i} src={src} alt={`${project.name} ${i}`}
                      onError={e => { e.target.style.display = 'none' }}
                      style={{ width: '100%', borderRadius: 8, aspectRatio: '1', objectFit: 'cover', border: '1px solid var(--border)' }} />
                  ))}
                </div>
              </div>
            )}

            {imgs.length === 0 && outs.length === 0 && (
              <div style={{ color: 'var(--text-faint)', textAlign: 'center', padding: 32 }}>
                No files yet
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Delete file warning modal */}
      {deleteFileTarget && (
        <div className="modal-overlay" onClick={() => !deletingFile && setDeleteFileTarget(null)}>
          <div className="modal" onClick={e => e.stopPropagation()} style={{ maxWidth: 380 }}>
            <div style={{ textAlign: 'center', marginBottom: 24 }}>
              <div style={{ fontSize: 36, marginBottom: 12 }}>⚠️</div>
              <h2 style={{ fontSize: 18, marginBottom: 8 }}>¿Eliminar archivo?</h2>
              <p style={{ color: 'var(--text-dim)', fontSize: 14 }}>
                <strong>{decodeURIComponent(deleteFileTarget.filename)}</strong> será eliminado permanentemente.
              </p>
            </div>
            <div style={{ display: 'flex', gap: 12 }}>
              <button className="btn btn-outline" onClick={() => setDeleteFileTarget(null)} disabled={deletingFile} style={{ flex: 1 }}>
                Cancelar
              </button>
              <button onClick={handleDeleteFile} disabled={deletingFile} style={{
                flex: 1, background: 'var(--danger, #c0392b)', color: '#fff',
                border: 'none', borderRadius: 8, padding: '12px 20px',
                fontSize: 14, fontWeight: 600, cursor: deletingFile ? 'not-allowed' : 'pointer',
                opacity: deletingFile ? 0.6 : 1,
              }}>
                {deletingFile ? 'Eliminando...' : 'Eliminar'}
              </button>
            </div>
          </div>
        </div>
      )}

      {viewUrl && <Viewer3D url={viewUrl} onClose={() => setViewUrl(null)} />}
      {view360Url && <Viewer360 url={view360Url} onClose={() => setView360Url(null)} />}
    </div>
  )
}

// Defaults — siempre máxima calidad y resolución
const DEF = {
  full_360: false,
  target_size: 1120,
  max_resolution: 2560,
  apply_sky_mask: true,
  apply_edge_mask: true,
  apply_confidence_mask: false,
  save_gs: true,
  save_points: true,
  // asset settings
  texture: false,
}

function GenStatus({ status, hasPano }) {
  const [sec, setSec] = useState(0)
  useEffect(() => {
    if (status !== 'processing') { setSec(0); return }
    const t0 = Date.now()
    const id = setInterval(() => setSec(Math.floor((Date.now() - t0) / 1000)), 1000)
    return () => clearInterval(id)
  }, [status])

  if (!status || status === 'completed') return null
  const mm = String(Math.floor(sec / 60)).padStart(2, '0')
  const ss = String(sec % 60).padStart(2, '0')
  const cfg = {
    pending:    { t: 'En espera de procesamiento', d: 'El worker lo tomará en el próximo ciclo.', dot: 'dot-wait', bar: false },
    processing: { t: `Generando 3D — ${mm}:${ss}`, d: hasPano ? 'Reconstruyendo en GPU. El panorama 360 ya está disponible abajo mientras tanto.' : 'Reconstruyendo en GPU. Puede tardar varios minutos.', dot: 'dot-proc', bar: true },
    error:      { t: 'Error en la última generación', d: 'Se conservó el resultado anterior. Pulsa Generate para reintentar.', dot: '', bar: false },
  }[status] || { t: status, d: '', dot: '', bar: false }

  return (
    <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10, padding: '14px 18px', marginBottom: 20 }}>
      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 4 }}>
        {cfg.dot && <span className={`dot ${cfg.dot}`} />}{cfg.t}
      </div>
      <div style={{ fontSize: 12, color: 'var(--text-dim)', marginBottom: cfg.bar ? 10 : 0 }}>{cfg.d}</div>
      {cfg.bar && <div className="bar"><span /></div>}
    </div>
  )
}
