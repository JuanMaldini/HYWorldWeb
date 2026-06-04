import { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import { api } from '../lib/pocketbase'
import Viewer3D from '../components/Viewer3D'

export default function Project({ user }) {
  const { slug } = useParams()
  const [project, setProject] = useState(null)
  const [loading, setLoading] = useState(true)
  const [updating, setUpdating] = useState(false)
  const [viewUrl, setViewUrl] = useState(null)
  const [settings, setSettings] = useState({})
  const [savingS, setSavingS] = useState(false)
  const [savedS, setSavedS] = useState(false)
  const [gen, setGen] = useState(false)

  useEffect(() => {
    const load = async () => {
      try {
        const all = await api.getProjects()
        const found = all.find(p => p.slug === slug)
        if (found) {
          const detail = await api.getProject(found.id)
          console.debug('[HYWorld] Project load', slug, 'files=', detail.files)
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

  const DEF = { target_size: 952, max_resolution: 1920, apply_sky_mask: true, apply_edge_mask: true, apply_confidence_mask: false, save_gs: true, save_points: true }
  const sval = (k) => (settings[k] === undefined ? DEF[k] : settings[k])
  const setS = (k, v) => { setSettings(s => ({ ...s, [k]: v })); setSavedS(false) }
  const saveSettings = async () => {
    setSavingS(true)
    try { await api.updateProjectSettings(project.id, settings); setSavedS(true) }
    catch (err) { console.error(err) }
    finally { setSavingS(false) }
  }

  const handleGenerate = async () => {
    setGen(true)
    try {
      // Genera PLY + malla GLB en la mejor resolucion posible
      await api.generateMesh(project.id)
      setProject(p => ({ ...p, status: 'pending' }))
    } catch (err) { console.error(err) }
    finally { setGen(false) }
  }

  const files = project.files || []
  const isImg = (u) => /\.(jpg|jpeg|png|webp)$/i.test(u.split('?')[0])
  const isModel = (u) => /\.(glb|gltf)$/i.test(u.split('?')[0])
  const imgs = files.filter(isImg)
  const outs = files.filter(isModel)

  return (
    <div>
      <div className="topbar" style={{ height: 56 }}>
        <Link to="/dashboard" style={{ color: 'var(--accent)', fontSize: 20, textDecoration: 'none' }}>←</Link>
        <h1 style={{ fontSize: 16, fontWeight: 600, flex: 1 }}>{project.name}</h1>
        <span className={`status status-${project.status}`}>{project.status}</span>
        <button className="btn" onClick={handleGenerate}
          disabled={gen || project.status === 'processing' || project.status === 'pending'}
          style={{ marginLeft: 12 }}>
          {gen ? 'Enviando...' : project.status === 'processing' ? 'Generando...' : project.status === 'pending' ? 'En espera...' : 'Generate'}
        </button>

      </div>

      <div style={{ padding: '32px 40px', maxWidth: 1200, margin: '0 auto' }}>
        {/* Meta info */}
        <div style={{ color: 'var(--text-dim)', fontSize: 13, marginBottom: 32 }}>
          Slug: <code style={{ background: 'var(--bg-dark)', padding: '2px 8px', borderRadius: 4 }}>/p/{project.slug}</code>
          &nbsp;|&nbsp; Created: {new Date(project.created).toLocaleString()}
        </div>

        <GenStatus status={project.status} />

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

        {/* Settings de reconstruccion */}
        <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 12, padding: '20px 24px', marginBottom: 32, maxWidth: 560 }}>
          <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 4 }}>Ajustes de reconstruccion</div>
          <div style={{ fontSize: 12, color: 'var(--text-dim)', marginBottom: 18 }}>Se aplican la proxima vez que el worker procese (activa "Listo" despues de guardar).</div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 18 }}>
            <label style={{ fontSize: 13 }}>
              <div style={{ color: 'var(--text-dim)', marginBottom: 6 }}>Calidad (resolucion)</div>
              <select value={sval('target_size')} onChange={e => setS('target_size', Number(e.target.value))}
                style={{ width: '100%', background: 'var(--bg-dark)', border: '1px solid var(--border)', borderRadius: 8, padding: '9px 12px', color: 'var(--text)', fontSize: 13 }}>
                <option value={518}>Rapida (518)</option>
                <option value={728}>Media (728)</option>
                <option value={952}>Alta (952)</option>
                <option value={1120}>Maxima (1120)</option>
              </select>
            </label>
            <label style={{ fontSize: 13 }}>
              <div style={{ color: 'var(--text-dim)', marginBottom: 6 }}>Resolucion max. salida</div>
              <select value={sval('max_resolution')} onChange={e => setS('max_resolution', Number(e.target.value))}
                style={{ width: '100%', background: 'var(--bg-dark)', border: '1px solid var(--border)', borderRadius: 8, padding: '9px 12px', color: 'var(--text)', fontSize: 13 }}>
                <option value={1280}>1280</option>
                <option value={1920}>1920</option>
                <option value={2560}>2560</option>
              </select>
            </label>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {[
              ['apply_sky_mask', 'Quitar cielo'],
              ['apply_edge_mask', 'Mascara de bordes'],
              ['apply_confidence_mask', 'Mascara de confianza'],
              ['save_gs', 'Generar Gaussian Splat (.ply)'],
              ['save_points', 'Generar nube de puntos (.ply)'],
            ].map(([k, label]) => (
              <label key={k} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: 13, cursor: 'pointer' }}>
                <span style={{ color: 'var(--text)' }}>{label}</span>
                <input type="checkbox" checked={!!sval(k)} onChange={e => setS(k, e.target.checked)}
                  style={{ width: 18, height: 18, accentColor: 'var(--accent)', cursor: 'pointer' }} />
              </label>
            ))}
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginTop: 20 }}>
            <button onClick={saveSettings} disabled={savingS} className="btn">
              {savingS ? 'Guardando...' : 'Guardar ajustes'}
            </button>
            {savedS && <span style={{ fontSize: 13, color: 'var(--success)' }}>Guardado</span>}
          </div>
        </div>

        {/* Modelo 3D (GLB) */}
        {outs.length > 0 && (
          <div style={{ marginBottom: 32 }}>
            <div style={{ fontSize: 11, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: 12 }}>
              Modelo 3D
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxWidth: 480 }}>
              {outs.map((src, i) => {
                const fname = decodeURIComponent(src.split('/').pop().split('?')[0])
                return (
                  <div key={i}
                    style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12,
                      background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, padding: '12px 16px' }}>
                    <span style={{ fontSize: 13, fontFamily: 'monospace', color: 'var(--text)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{fname}</span>
                    <span style={{ display: 'flex', gap: 14, flexShrink: 0 }}>
                      <button onClick={() => setViewUrl(src)}
                        style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 12, color: 'var(--cyan)', fontWeight: 600 }}>Ver modelo</button>
                      <a href={src} download style={{ fontSize: 12, color: 'var(--accent)', fontWeight: 600, textDecoration: 'none' }}>Descargar modelo</a>
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
            <div style={{ fontSize: 11, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: 16 }}>
              Images ({imgs.length})
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 12 }}>
              {imgs.map((src, i) => (
                <img key={i} src={src} alt={`${project.name} ${i}`} onError={e => { e.target.style.display = 'none' }}
                  style={{ width: '100%', borderRadius: 8, aspectRatio: '1', objectFit: 'cover', border: '1px solid var(--border)' }} />
              ))}
            </div>
          </div>
        )}

        {imgs.length === 0 && outs.length === 0 && (
          <div style={{ color: 'var(--text-faint)', textAlign: 'center', padding: 40 }}>
            No files yet
          </div>
        )}
      </div>

      {viewUrl && <Viewer3D url={viewUrl} onClose={() => setViewUrl(null)} />}
    </div>
  )
}

function GenStatus({ status }) {
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
    pending:    { t: 'En espera de procesamiento', d: 'El worker lo tomara en el proximo ciclo.', dot: 'dot-wait', bar: false },
    processing: { t: `Generando 3D - ${mm}:${ss}`, d: 'Reconstruyendo en GPU. Puede tardar varios minutos.', dot: 'dot-proc', bar: true },
    error:      { t: 'Error en la ultima generacion', d: 'Se conservo el resultado anterior. Pulsa Generate para reintentar.', dot: '', bar: false },
  }[status] || { t: status, d: '', dot: '', bar: false }

  return (
    <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 12, padding: '16px 20px', marginBottom: 24, maxWidth: 560 }}>
      <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>
        {cfg.dot && <span className={`dot ${cfg.dot}`} />}{cfg.t}
      </div>
      <div style={{ fontSize: 12, color: 'var(--text-dim)', marginBottom: cfg.bar ? 12 : 0 }}>{cfg.d}</div>
      {cfg.bar && <div className="bar"><span /></div>}
    </div>
  )
}
