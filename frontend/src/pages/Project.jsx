import { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import { api } from '../lib/pocketbase'
import Viewer3D from '../components/Viewer3D'
import Viewer360 from '../components/Viewer360'
import Pano360 from '../components/Pano360'

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
          setProject({ ...found, files: detail.files, hw: detail.hw,
                       stage: detail.stage, degraded: detail.degraded })
          setSettings(detail.settings || found.settings || {})
        }
      } catch (err) {
        console.error(err)
      } finally {
        setLoading(false)
      }
    }
    load()
    // Realtime (SSE): el worker publica status, stage, hw y degraded en el
    // record y la vista los refleja al instante, sin el retardo de hasta 4 s
    // del sondeo anterior — que ademas disparaba 2 peticiones por ciclo.
    const stop = api.subscribeProjects((action, record) => {
      if (!record || record.slug !== slug) return
      if (action === 'delete') return
      setProject(prev => prev ? {
        ...prev, ...record,
        // hw solo se publica al arrancar una generacion: no lo borres entre corridas.
        hw: record.hw ?? prev.hw,
      } : record)
    })
    return stop
  }, [slug])

  const toggleListo = async () => {
    if (!project) return
    setUpdating(true)
    try {
      const on = !project.listo
      await api.updateProjectStatus(project.id, on)
      setProject(p => ({ ...p, listo: on, status: on ? 'pending' : p.status }))
    } catch (err) {
      console.error(err)
    } finally {
      setUpdating(false)
    }
  }

  // Un solo escritor de settings: evita que dos handlers pisen el estado.
  const patchSettings = async (patch) => {
    // Se limpian las claves absolutas heredadas (target_size/max_resolution/
    // max_points). Ahora la calidad viaja como `quality` y es el worker quien
    // la resuelve contra el hardware real; dejar las viejas fijaria una
    // resolucion antigua por debajo del preset elegido.
    const rest = { ...settings }
    for (const k of LEGACY_SETTING_KEYS) delete rest[k]
    const next = { ...rest, ...patch }
    setSettings(next)
    try { await api.updateProjectSettings(project.id, next) } catch (e) { console.error(e) }
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
  // Panorama equirectangular subido por el worker: <nombre>_pano.png
  // (PocketBase agrega sufijo aleatorio: <nombre>_pano_xxxxxxxx.png)
  const isPano = (u) => {
    const f = decodeURIComponent(u.split('?')[0].split('/').pop()).toLowerCase()
    return f.includes('_pano') && f.endsWith('.png')
  }
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
        <button className="btn" onClick={handleGenerate}
          disabled={!user || gen || project.status === 'processing'}
          style={{ marginLeft: 12, ...(!user && { opacity: 0.5, pointerEvents: 'none' }) }}>
          {gen ? 'Enviando...' : project.status === 'processing' ? 'Generando...' : project.status === 'pending' ? 'En cola — reenviar' : 'Generate'}
        </button>
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
        {/* key={status}: al cambiar de estado el componente se remonta y el
            cronometro arranca de cero sin tocar estado dentro del efecto. */}
        <GenStatus key={project.status} status={project.status} hasPano={panos.length > 0}
          stage={project.stage} degraded={project.degraded} />

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
              /* ── Space settings: modo de generacion + presets de calidad ── */
              <>
                <ModeSwitch
                  value={!!sval('full_360')}
                  disabled={!user}
                  onChange={(on) => patchSettings({ full_360: on })}
                />

                <QualityPresets
                  value={String(sval('quality'))}
                  disabled={!user}
                  hw={project.hw}
                  full360={!!sval('full_360')}
                  onChange={(q) => patchSettings({ quality: q })}
                />

                <HardwareNote hw={project.hw} />
              </>
            )}
          </div>

          {/* Right: Output */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>

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

            {/* 360 panorama viewer */}
            {panos.length > 0 && (
              <div>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
                  <span style={{ fontSize: 11, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                    360°
                  </span>
                  <span style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
                    <button onClick={() => setView360Url(panos[0])}
                      style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 12, color: 'var(--cyan)', fontWeight: 600, padding: 0 }}>
                      Pantalla completa
                    </button>
                    <a href={panos[0]} download style={{ fontSize: 12, color: 'var(--accent)', fontWeight: 600, textDecoration: 'none' }}>
                      Descargar
                    </a>
                    {user && (
                      <button
                        onClick={() => setDeleteFileTarget({ url: panos[0], filename: panos[0].split('/').pop().split('?')[0] })}
                        style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 12, color: 'var(--danger)', fontWeight: 600, padding: 0 }}
                        title="Eliminar panorama"
                      >
                        🗑
                      </button>
                    )}
                  </span>
                </div>
                <Pano360 url={panos[0]} />
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

            {imgs.length === 0 && outs.length === 0 && panos.length === 0 && (
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

// Presets de calidad. Ya NO llevan valores absolutos: la calidad viaja como
// `quality` y el worker la resuelve contra el hardware real (hw_profile.
// apply_preset). Aqui solo vive lo que se muestra en pantalla.
const PRESETS = [
  { id: 'min', label: 'Mínima',  hint: 'Vista previa rápida' },
  { id: 'med', label: 'Media',   hint: 'Equilibrio detalle/tiempo' },
  { id: 'max', label: 'Máxima',  hint: 'Todo el detalle que dé la GPU' },
]

// Claves de settings de la version anterior: valores absolutos de resolucion
// que hoy resuelve el worker a partir de `quality` y del hardware detectado.
// Se purgan al guardar para que un proyecto viejo no quede clavado en ellas.
const LEGACY_SETTING_KEYS = ['target_size', 'max_resolution', 'max_points']

const DEF = {
  full_360: false,
  quality: 'max',
  apply_sky_mask: true,
  apply_edge_mask: true,
  apply_confidence_mask: false,
  save_points: true,
  // asset settings
  texture: false,
}

/* ── Modo de generación ────────────────────────────────────────────────
   Dos tarjetas grandes en vez de un checkbox: es la decisión que más cambia
   el resultado (y el tiempo) de toda la pantalla, así que se ve como tal. */
function ModeSwitch({ value, disabled, onChange }) {
  const opts = [
    {
      on: true, icon: '🌐', title: 'Espacio 360 completo',
      desc: 'Panorama equirectangular + vistas de paredes, techo y suelo → geometría 3D de la esfera entera.',
    },
    {
      on: false, icon: '🖼', title: 'Solo frente',
      desc: 'Reconstruye únicamente lo que se ve en la imagen subida. Mucho más rápido.',
    },
  ]
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 18 }}>
      <div style={{ fontSize: 11, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
        Modo de generación
      </div>
      {opts.map(o => {
        const active = value === o.on
        return (
          <div key={String(o.on)} role="radio" aria-checked={active} tabIndex={disabled ? -1 : 0}
            onClick={disabled ? undefined : () => onChange(o.on)}
            onKeyDown={disabled ? undefined : e => {
              if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onChange(o.on) }
            }}
            style={{
              display: 'flex', gap: 12, alignItems: 'flex-start',
              background: active ? 'color-mix(in srgb, var(--accent) 12%, var(--bg-dark))' : 'var(--bg-dark)',
              border: `1.5px solid ${active ? 'var(--accent)' : 'var(--border)'}`,
              boxShadow: active ? '0 0 0 3px color-mix(in srgb, var(--accent) 18%, transparent)' : 'none',
              borderRadius: 10, padding: '13px 14px', userSelect: 'none',
              cursor: disabled ? 'default' : 'pointer', transition: 'all 0.18s',
              ...(disabled && { opacity: 0.5, pointerEvents: 'none' }),
            }}>
            <span style={{ fontSize: 19, lineHeight: 1.1, flexShrink: 0 }}>{o.icon}</span>
            <span style={{ minWidth: 0, flex: 1 }}>
              <div style={{ fontSize: 13, fontWeight: 700, color: active ? 'var(--accent)' : 'var(--text)' }}>
                {o.title}
              </div>
              <div style={{ fontSize: 11.5, color: 'var(--text-dim)', marginTop: 3, lineHeight: 1.45 }}>
                {o.desc}
              </div>
            </span>
            {/* Radio dibujado a mano: hereda el color de acento del tema */}
            <span style={{
              width: 16, height: 16, borderRadius: '50%', flexShrink: 0, marginTop: 2,
              border: `2px solid ${active ? 'var(--accent)' : 'var(--border)'}`,
              display: 'grid', placeItems: 'center', transition: 'all 0.18s',
            }}>
              {active && <span style={{ width: 7, height: 7, borderRadius: '50%', background: 'var(--accent)' }} />}
            </span>
          </div>
        )
      })}
    </div>
  )
}

/* ── Presets de calidad ────────────────────────────────────────────────
   Muestran el valor EFECTIVO en el hardware detectado (project.hw, que
   publica el worker). "Máxima" no significa lo mismo en una 3080 de 10 GB
   que en una 4090, y la UI lo dice en vez de fingir. */
function QualityPresets({ value, disabled, hw, full360, onChange }) {
  const caps = hw?.presets?.[value] || null
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ fontSize: 11, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: 8 }}>
        Calidad
      </div>
      <div style={{ display: 'flex', gap: 6 }}>
        {PRESETS.map(p => {
          const active = value === p.id
          return (
            <button key={p.id} onClick={() => onChange(p.id)} disabled={disabled}
              title={p.hint}
              style={{
                flex: 1, padding: '9px 0', fontSize: 12, fontWeight: 700,
                background: active ? 'var(--accent)' : 'var(--bg-dark)',
                color: active ? '#fff' : 'var(--text-dim)',
                border: `1.5px solid ${active ? 'var(--accent)' : 'var(--border)'}`,
                borderRadius: 8, transition: 'all 0.18s',
                cursor: disabled ? 'default' : 'pointer',
                ...(disabled && { opacity: 0.5, pointerEvents: 'none' }),
              }}>
              {p.label}
            </button>
          )
        })}
      </div>
      <div style={{ fontSize: 11.5, color: 'var(--text-dim)', marginTop: 8, lineHeight: 1.5 }}>
        {PRESETS.find(p => p.id === value)?.hint}
        {caps && (
          <div style={{ color: 'var(--text-faint)', marginTop: 4 }}>
            {full360
              ? `${caps.n_views} vistas · panorama ${caps.pano_width}×${caps.pano_height} · ${Math.round(caps.max_points / 1000)}k pts`
              : `${caps.target_size}px · ${Math.round(caps.max_points / 1000)}k pts`}
          </div>
        )}
      </div>
    </div>
  )
}

/* ── Hardware detectado ────────────────────────────────────────────────
   El worker manda: si pides más de lo que cabe, se acota. Decirlo aquí
   evita la sorpresa de elegir "Máxima" y recibir otra cosa. */
function HardwareNote({ hw }) {
  if (!hw) {
    return (
      <div style={{ fontSize: 11, color: 'var(--text-faint)', lineHeight: 1.5 }}>
        El hardware se detecta en la primera generación.
      </div>
    )
  }
  return (
    <div style={{
      fontSize: 11, color: 'var(--text-faint)', lineHeight: 1.5,
      borderTop: '1px solid var(--border)', paddingTop: 10,
    }}>
      <div style={{ color: 'var(--text-dim)', fontWeight: 600 }}>
        {hw.gpu || 'GPU'} · {hw.vram_gb ? `${hw.vram_gb} GB` : 'VRAM ?'}
      </div>
      <div style={{ marginTop: 2 }}>
        Perfil <code style={{ color: 'var(--text-dim)' }}>{hw.tier}</code> — la calidad
        se acota a lo que esta GPU admite.
      </div>
    </div>
  )
}

// Etapas que publica el worker en json.stage. Sin esto, los minutos que tarda
// el panorama se veían como un contador mudo y parecían un cuelgue.
const STAGES = [
  { id: 'pano',      label: 'Panorama 360' },
  { id: 'multiview', label: 'Vistas del espacio' },
  { id: 'recon',     label: 'Reconstrucción 3D' },
]

function GenStatus({ status, hasPano, stage, degraded }) {
  const [sec, setSec] = useState(0)
  useEffect(() => {
    // Sin setSec(0) aqui: el contador se reinicia remontando el componente
    // (el padre le pasa key={status}). Poner estado en el cuerpo del efecto
    // encadena renders innecesarios.
    if (status !== 'processing') return undefined
    const t0 = Date.now()
    const id = setInterval(() => setSec(Math.floor((Date.now() - t0) / 1000)), 1000)
    return () => clearInterval(id)
  }, [status])

  if (!status || status === 'completed') return degraded ? <DegradedNote text={degraded} /> : null
  const mm = String(Math.floor(sec / 60)).padStart(2, '0')
  const ss = String(sec % 60).padStart(2, '0')
  const at = STAGES.findIndex(s => s.id === stage)
  const cfg = {
    pending:    { t: 'En espera de procesamiento', d: 'El worker lo tomará en el próximo ciclo.', dot: 'dot-wait', bar: false },
    processing: { t: `Generando 3D — ${mm}:${ss}`, d: hasPano ? 'El panorama 360 ya está disponible abajo.' : 'Reconstruyendo en GPU. Puede tardar varios minutos.', dot: 'dot-proc', bar: true },
    error:      { t: 'Error en la última generación', d: 'Se conservó el resultado anterior. Pulsa Generate para reintentar.', dot: '', bar: false },
  }[status] || { t: status, d: '', dot: '', bar: false }

  return (
    <>
      <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10, padding: '14px 18px', marginBottom: 20 }}>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 4 }}>
          {cfg.dot && <span className={`dot ${cfg.dot}`} />}{cfg.t}
        </div>
        <div style={{ fontSize: 12, color: 'var(--text-dim)', marginBottom: cfg.bar ? 10 : 0 }}>{cfg.d}</div>
        {cfg.bar && <div className="bar"><span /></div>}
        {status === 'processing' && at >= 0 && (
          <div style={{ display: 'flex', gap: 6, marginTop: 12, flexWrap: 'wrap' }}>
            {STAGES.map((s, i) => (
              <span key={s.id} style={{
                fontSize: 11, padding: '3px 9px', borderRadius: 20,
                border: `1px solid ${i <= at ? 'var(--accent)' : 'var(--border)'}`,
                color: i < at ? 'var(--text-dim)' : i === at ? 'var(--accent)' : 'var(--text-faint)',
                fontWeight: i === at ? 700 : 500,
                background: i === at ? 'color-mix(in srgb, var(--accent) 12%, transparent)' : 'transparent',
              }}>
                {i < at ? '✓ ' : ''}{s.label}
              </span>
            ))}
          </div>
        )}
      </div>
      {degraded && <DegradedNote text={degraded} />}
    </>
  )
}

// Aviso de degradación: el worker agotó la escalera del 360 y entregó menos de
// lo pedido. Antes esto pasaba en silencio y el usuario no sabía por qué su
// "espacio completo" era una sola pared.
function DegradedNote({ text }) {
  return (
    <div style={{
      background: 'color-mix(in srgb, var(--danger, #c0392b) 10%, var(--surface))',
      border: '1px solid color-mix(in srgb, var(--danger, #c0392b) 40%, var(--border))',
      borderRadius: 10, padding: '12px 16px', marginBottom: 20,
      fontSize: 12, color: 'var(--text-dim)',
    }}>
      <strong style={{ color: 'var(--text)' }}>⚠ Resultado degradado</strong>
      <div style={{ marginTop: 3 }}>{text}</div>
    </div>
  )
}
