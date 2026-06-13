import { useEffect, useRef, useState } from 'react'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'

// Visor de panorama 360 equirectangular: esfera invertida + orbit controls.
export default function Viewer360({ url, onClose }) {
  const mountRef = useRef(null)
  const [status, setStatus] = useState('Cargando 360...')

  useEffect(() => {
    const mount = mountRef.current
    if (!mount) return
    const w = mount.clientWidth || 800
    const h = mount.clientHeight || 600

    const scene = new THREE.Scene()
    const camera = new THREE.PerspectiveCamera(75, w / h, 0.1, 200)
    camera.position.set(0, 0, 0.1)

    const renderer = new THREE.WebGLRenderer({ antialias: true })
    renderer.setPixelRatio(window.devicePixelRatio)
    renderer.setSize(w, h)
    mount.appendChild(renderer.domElement)

    const controls = new OrbitControls(camera, renderer.domElement)
    controls.enableDamping = true
    controls.dampingFactor = 0.08
    controls.enableZoom = false
    controls.enablePan = false
    controls.rotateSpeed = -0.35 // invertido: arrastrar = mirar (estandar visores 360)

    // Esfera invertida con la textura equirectangular
    const geo = new THREE.SphereGeometry(50, 64, 48)
    geo.scale(-1, 1, 1)
    const mat = new THREE.MeshBasicMaterial()
    const sphere = new THREE.Mesh(geo, mat)
    scene.add(sphere)

    new THREE.TextureLoader().load(
      url,
      (tex) => {
        tex.colorSpace = THREE.SRGBColorSpace
        mat.map = tex
        mat.needsUpdate = true
        setStatus(`${tex.image.width}×${tex.image.height}`)
      },
      undefined,
      () => setStatus('Error al cargar el panorama')
    )

    // Zoom = FOV con la rueda
    const onWheel = (e) => {
      e.preventDefault()
      camera.fov = THREE.MathUtils.clamp(camera.fov + e.deltaY * 0.04, 30, 100)
      camera.updateProjectionMatrix()
    }
    renderer.domElement.addEventListener('wheel', onWheel, { passive: false })

    let id
    const animate = () => {
      id = requestAnimationFrame(animate)
      controls.update()
      renderer.render(scene, camera)
    }
    animate()

    const onResize = () => {
      const W = mount.clientWidth, H = mount.clientHeight
      renderer.setSize(W, H); camera.aspect = W / H; camera.updateProjectionMatrix()
    }
    window.addEventListener('resize', onResize)

    return () => {
      cancelAnimationFrame(id)
      window.removeEventListener('resize', onResize)
      renderer.domElement.removeEventListener('wheel', onWheel)
      controls.dispose()
      mat.map?.dispose()
      geo.dispose(); mat.dispose()
      renderer.dispose()
      if (renderer.domElement.parentNode === mount) mount.removeChild(renderer.domElement)
    }
  }, [url])

  const btn = { background: 'var(--surface)', border: '1px solid var(--border)', color: 'var(--text)', borderRadius: 7, padding: '6px 11px', cursor: 'pointer', fontSize: 12 }

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(13,14,22,.92)', zIndex: 100, display: 'flex', flexDirection: 'column' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '12px 20px', borderBottom: '1px solid var(--border)' }}>
        <span style={{ fontSize: 13, color: 'var(--text-dim)', fontFamily: 'monospace' }}>
          🌐 {decodeURIComponent(url.split('/').pop().split('?')[0])} &nbsp;·&nbsp; {status}
        </span>
        <button onClick={onClose} style={btn}>Cerrar</button>
      </div>
      <div ref={mountRef} style={{ flex: 1, minHeight: 0, cursor: 'grab' }} />
      <div style={{ textAlign: 'center', padding: '8px 16px', borderTop: '1px solid var(--border)', fontSize: 11, color: 'var(--text-dim)' }}>
        Arrastrar para mirar · Rueda para zoom
      </div>
    </div>
  )
}
