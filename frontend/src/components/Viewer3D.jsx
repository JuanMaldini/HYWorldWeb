import { useEffect, useRef, useState } from 'react'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { PLYLoader } from 'three/examples/jsm/loaders/PLYLoader.js'
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js'

// Visor de nube de puntos / malla PLY con controles de orientacion.
export default function Viewer3D({ url, onClose }) {
  const mountRef = useRef(null)
  const groupRef = useRef(null)       // contiene el objeto (rotaciones del usuario)
  const controlsRef = useRef(null)
  const cameraRef = useRef(null)
  const fitRef = useRef(3)
  const autoRef = useRef(false)
  const [status, setStatus] = useState('Cargando 3D...')
  const [auto, setAuto] = useState(false)
  const [ptSize, setPtSize] = useState(0.012)
  const matRef = useRef(null)

  useEffect(() => {
    const mount = mountRef.current
    if (!mount) return
    const w = mount.clientWidth || 800
    const h = mount.clientHeight || 600

    const scene = new THREE.Scene()
    scene.background = new THREE.Color(0x16161e)

    const camera = new THREE.PerspectiveCamera(60, w / h, 0.001, 5000)
    camera.position.set(0, 0, 3)
    cameraRef.current = camera

    const renderer = new THREE.WebGLRenderer({ antialias: true })
    renderer.setPixelRatio(window.devicePixelRatio)
    renderer.setSize(w, h)
    mount.appendChild(renderer.domElement)

    const controls = new OrbitControls(camera, renderer.domElement)
    controls.enableDamping = true
    controls.dampingFactor = 0.08
    controlsRef.current = controls

    scene.add(new THREE.AmbientLight(0xffffff, 0.9))
    const dir = new THREE.DirectionalLight(0xffffff, 0.6)
    dir.position.set(5, 10, 7)
    scene.add(dir)

    const group = new THREE.Group()
    scene.add(group)
    groupRef.current = group

    const ext = url.split('?')[0].split('.').pop().toLowerCase()

    const fitAndAdd = (obj3d) => {
      const box = new THREE.Box3().setFromObject(obj3d)
      const center = box.getCenter(new THREE.Vector3())
      obj3d.position.sub(center)
      const size = box.getSize(new THREE.Vector3()).length() || 3
      fitRef.current = size * 0.8
      camera.position.set(0, 0, fitRef.current)
      camera.near = size / 1000
      camera.far = size * 100
      camera.updateProjectionMatrix()
      controls.target.set(0, 0, 0)
      controls.update()
      group.add(obj3d)
    }

    if (ext === 'glb' || ext === 'gltf') {
      new GLTFLoader().load(
        url,
        (gltf) => { fitAndAdd(gltf.scene); setStatus('malla GLB') },
        (e) => { if (e.total) setStatus(`Cargando 3D... ${Math.round((e.loaded / e.total) * 100)}%`) },
        (err) => { console.error('GLB load error', err); setStatus('Error al cargar el modelo') }
      )
      let id2
      const animate2 = () => {
        id2 = requestAnimationFrame(animate2)
        if (autoRef.current && groupRef.current) groupRef.current.rotation.y += 0.005
        controls.update(); renderer.render(scene, camera)
      }
      animate2()
      const onResize2 = () => {
        const W = mount.clientWidth, H = mount.clientHeight
        renderer.setSize(W, H); camera.aspect = W / H; camera.updateProjectionMatrix()
      }
      window.addEventListener('resize', onResize2)
      return () => {
        cancelAnimationFrame(id2); window.removeEventListener('resize', onResize2)
        controls.dispose(); renderer.dispose()
        if (renderer.domElement.parentNode === mount) mount.removeChild(renderer.domElement)
      }
    }

    const loader = new PLYLoader()
    loader.load(
      url,
      (geometry) => {
        const hasColor = !!geometry.getAttribute('color')
        let object
        if (geometry.index) {
          geometry.computeVertexNormals()
          const m = new THREE.MeshStandardMaterial({ color: hasColor ? 0xffffff : 0x7aa2f7, vertexColors: hasColor, flatShading: true })
          matRef.current = m
          object = new THREE.Mesh(geometry, m)
        } else {
          const m = new THREE.PointsMaterial({ size: ptSize, sizeAttenuation: true, color: hasColor ? 0xffffff : 0x7aa2f7, vertexColors: hasColor })
          matRef.current = m
          object = new THREE.Points(geometry, m)
        }
        geometry.computeBoundingBox()
        const box = geometry.boundingBox
        const center = box.getCenter(new THREE.Vector3())
        object.position.sub(center)
        const size = box.getSize(new THREE.Vector3()).length() || 3
        fitRef.current = size * 0.8
        camera.position.set(0, 0, fitRef.current)
        camera.near = size / 1000
        camera.far = size * 100
        camera.updateProjectionMatrix()
        controls.target.set(0, 0, 0)
        controls.update()
        group.add(object)
        const n = geometry.getAttribute('position')?.count || 0
        setStatus(`${n.toLocaleString()} puntos`)
      },
      (e) => { if (e.total) setStatus(`Cargando 3D... ${Math.round((e.loaded / e.total) * 100)}%`) },
      (err) => { console.error('PLY load error', err); setStatus('Error al cargar el PLY') }
    )

    let id
    const animate = () => {
      id = requestAnimationFrame(animate)
      if (autoRef.current && groupRef.current) groupRef.current.rotation.y += 0.005
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
      controls.dispose()
      renderer.dispose()
      if (renderer.domElement.parentNode === mount) mount.removeChild(renderer.domElement)
    }
  }, [url])

  // Controles de orientacion
  const rot = (axis, deg) => {
    const g = groupRef.current; if (!g) return
    g.rotation[axis] += THREE.MathUtils.degToRad(deg)
  }
  const fixUp = () => { const g = groupRef.current; if (g) g.rotation.set(-Math.PI / 2, 0, 0) } // Z-up -> Y-up
  const resetOrient = () => { const g = groupRef.current; if (g) g.rotation.set(0, 0, 0) }
  const resetView = () => {
    const c = controlsRef.current, cam = cameraRef.current; if (!c || !cam) return
    cam.position.set(0, 0, fitRef.current); c.target.set(0, 0, 0); c.update()
  }
  const toggleAuto = () => { const v = !auto; setAuto(v); autoRef.current = v }
  const changeSize = (mult) => {
    const m = matRef.current; if (!m || m.size === undefined) return
    const v = Math.max(0.001, m.size * mult); m.size = v; setPtSize(v)
  }

  const btn = { background: 'var(--surface)', border: '1px solid var(--border)', color: 'var(--text)', borderRadius: 7, padding: '6px 11px', cursor: 'pointer', fontSize: 12 }

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(13,14,22,.92)', zIndex: 100, display: 'flex', flexDirection: 'column' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '12px 20px', borderBottom: '1px solid var(--border)' }}>
        <span style={{ fontSize: 13, color: 'var(--text-dim)', fontFamily: 'monospace' }}>
          {decodeURIComponent(url.split('/').pop().split('?')[0])} &nbsp;·&nbsp; {status}
        </span>
        <button onClick={onClose} style={btn}>Cerrar</button>
      </div>

      <div ref={mountRef} style={{ flex: 1, minHeight: 0 }} />

      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', justifyContent: 'center', alignItems: 'center', padding: '10px 16px', borderTop: '1px solid var(--border)' }}>
        <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>Rotar:</span>
        <button style={btn} onClick={() => rot('x', -90)}>X -90</button>
        <button style={btn} onClick={() => rot('x', 90)}>X +90</button>
        <button style={btn} onClick={() => rot('y', -90)}>Y -90</button>
        <button style={btn} onClick={() => rot('y', 90)}>Y +90</button>
        <button style={btn} onClick={() => rot('z', -90)}>Z -90</button>
        <button style={btn} onClick={() => rot('z', 90)}>Z +90</button>
        <span style={{ width: 1, height: 18, background: 'var(--border)', margin: '0 4px' }} />
        <button style={btn} onClick={fixUp}>Corregir eje vertical</button>
        <button style={btn} onClick={resetOrient}>Reset orient.</button>
        <button style={btn} onClick={resetView}>Centrar vista</button>
        <button style={{ ...btn, color: auto ? 'var(--cyan)' : 'var(--text)' }} onClick={toggleAuto}>Auto-rotar: {auto ? 'ON' : 'OFF'}</button>
        <span style={{ width: 1, height: 18, background: 'var(--border)', margin: '0 4px' }} />
        <button style={btn} onClick={() => changeSize(0.8)}>Puntos -</button>
        <button style={btn} onClick={() => changeSize(1.25)}>Puntos +</button>
      </div>
    </div>
  )
}
