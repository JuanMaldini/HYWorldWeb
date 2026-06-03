import { useState, useEffect, useRef, useCallback } from 'react'
import { useParams, Link } from 'react-router-dom'
import { api } from '../lib/pocketbase'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import './App.css'

export default function Viewer() {
  const { pid } = useParams()
  const [meta, setMeta] = useState({})
  const [inputImages, setInputImages] = useState([])
  const [outputFiles, setOutputFiles] = useState([])
  const [uploading, setUploading] = useState(false)
  const [loading3d, setLoading3d] = useState(false)
  const [loadingText, setLoadingText] = useState('Loading...')
  const [progress, setProgress] = useState(0)
  const canvasRef = useRef(null)
  const rendererRef = useRef(null)
  const sceneRef = useRef(null)
  const cameraRef = useRef(null)
  const controlsRef = useRef(null)
  const meshRef = useRef(null)
  const fileInputRef = useRef(null)

  // Init Three.js
  useEffect(() => {
    if (!canvasRef.current) return

    const canvas = canvasRef.current
    const container = canvas.parentElement

    // Renderer
    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true })
    renderer.setPixelRatio(window.devicePixelRatio)
    renderer.setClearColor(0x0a0a0f, 1)
    rendererRef.current = renderer

    // Scene
    const scene = new THREE.Scene()
    scene.background = new THREE.Color(0x0a0a0f)
    sceneRef.current = scene

    // Camera
    const camera = new THREE.PerspectiveCamera(60, 1, 0.01, 1000)
    camera.position.set(0, 0, 3)
    cameraRef.current = camera

    // Controls
    const controls = new OrbitControls(camera, renderer.domElement)
    controls.enableDamping = true
    controls.dampingFactor = 0.05
    controlsRef.current = controls

    // Lights
    scene.add(new THREE.AmbientLight(0xffffff, 0.5))
    const dirLight = new THREE.DirectionalLight(0xffffff, 1)
    dirLight.position.set(5, 10, 5)
    scene.add(dirLight)
    scene.add(new THREE.GridHelper(10, 20, 0x222222, 0x181818))

    // Resize
    const resize = () => {
      const w = container.clientWidth
      const h = container.clientHeight
      renderer.setSize(w, h)
      camera.aspect = w / h
      camera.updateProjectionMatrix()
    }
    resize()
    const ro = new ResizeObserver(resize)
    ro.observe(container)

    // Animation loop
    let animId
    const animate = () => {
      animId = requestAnimationFrame(animate)
      controls.update()
      renderer.render(scene, camera)
    }
    animate()

    return () => {
      cancelAnimationFrame(animId)
      ro.disconnect()
      renderer.dispose()
    }
  }, [])

  // Load project
  const loadProject = useCallback(async () => {
    try {
      const r = await fetch(`/project/${pid}`)
      if (r.ok) {
        const html = await r.text()
        // Parse images and outputs from HTML
        const imgMatches = html.match(/src="(\/projects\/[^"]+input\/[^"]+)"/g) || []
        const imgs = imgMatches.map(m => m.match(/src="([^"]+)"/)[1])
        setInputImages(imgs)

        const outMatches = html.match(/href="(\/projects\/[^"]+output\/[^"]+)"/g) || []
        const outs = outMatches.map(m => {
          const url = m.match(/href="([^"]+)"/)[1]
          const fname = url.split('/').pop()
          return { name: fname, url }
        })
        setOutputFiles(outs)

        // Try parse meta from HTML
        const nameMatch = html.match(/<h1>([^<]+)<\/h1>/)
        const statusMatch = html.match(/status-badge status-(\w+)/)
        setMeta({
          name: nameMatch ? nameMatch[1] : pid,
          status: statusMatch ? statusMatch[1] : 'unknown'
        })
      }
    } catch (err) {
      console.error('Failed to load project:', err)
    }
  }, [pid])

  useEffect(() => { loadProject() }, [loadProject])

  // Auto-refresh status
  useEffect(() => {
    const interval = setInterval(async () => {
      const data = await api.refreshStatus(pid)
      if (data.status === 'completed') {
        setMeta(m => ({ ...m, status: 'completed' }))
        loadProject()
      }
    }, 30000)
    return () => clearInterval(interval)
  }, [pid, loadProject])

  // Load 3D model from output
  const loadModel = async (url) => {
    setLoading3d(true)
    setLoadingText('Loading 3D model...')
    setProgress(30)
    try {
      const ext = url.split('.').pop().toLowerCase()
      const response = await fetch(url)
      const text = await response.text()
      setProgress(60)

      if (ext === 'ply') {
        parsePLY(text)
      } else if (ext === 'obj') {
        parseOBJ(text)
      } else {
        console.warn('Unsupported 3D format:', ext)
      }
      setProgress(100)
    } catch (err) {
      console.error('Load error:', err)
      setLoadingText('Error loading model')
    } finally {
      setTimeout(() => setLoading3d(false), 500)
    }
  }

  const parsePLY = (text) => {
    const lines = text.split('\n')
    const vertices = [], faces = []
    let readingVertices = false, readingFaces = false

    for (const line of lines) {
      if (line.startsWith('end_header')) { readingVertices = true; continue }
      if (line.startsWith('property')) continue
      if (readingVertices && !readingFaces) {
        const parts = line.trim().split(/\s+/)
        if (parts.length >= 3) vertices.push(+parts[0], +parts[1], +parts[2])
        else readingFaces = true
      }
      if (readingFaces) {
        const parts = line.trim().split(/\s+/)
        if (parts.length >= 3) faces.push(+parts[0], +parts[1], +parts[2])
      }
    }

    const geometry = new THREE.BufferGeometry()
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(vertices, 3))
    geometry.setIndex(faces)
    geometry.computeVertexNormals()
    addMesh(new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({ color: 0x8866cc, roughness: 0.7, metalness: 0.1 })))
  }

  const parseOBJ = (text) => {
    const vertices = [], faces = []
    for (const line of text.split('\n')) {
      if (line.startsWith('v ')) {
        const p = line.split(' ').slice(1).map(Number)
        vertices.push(p[0], p[1], p[2])
      }
      if (line.startsWith('f ')) {
        const p = line.split(' ').slice(1).map(x => +x.split('/')[0] - 1)
        faces.push(...p)
      }
    }
    const geometry = new THREE.BufferGeometry()
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(vertices, 3))
    geometry.setIndex(faces)
    geometry.computeVertexNormals()
    addMesh(new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({ color: 0x8866cc, roughness: 0.7, metalness: 0.1 })))
  }

  const addMesh = (mesh) => {
    if (meshRef.current) sceneRef.current.remove(meshRef.current)
    meshRef.current = mesh
    const box = new THREE.Box3().setFromObject(mesh)
    const center = box.getCenter(new THREE.Vector3())
    mesh.position.sub(center)
    const size = box.getSize(new THREE.Vector3()).length()
    cameraRef.current.position.set(0, 0, size * 2)
    controlsRef.current.update()
    sceneRef.current.add(mesh)
    // Hide placeholder
    const ph = document.getElementById('viewerPlaceholder')
    if (ph) ph.style.display = 'none'
  }

  const handleUpload = async (files) => {
    if (!files.length) return
    setUploading(true)
    setLoadingText('Uploading images...')
    setLoading3d(true)
    try {
      await api.uploadImages(pid, files)
      await loadProject()
    } catch (err) {
      console.error('Upload failed:', err)
    } finally {
      setUploading(false)
      setLoading3d(false)
    }
  }

  const handleTrigger = async () => {
    setLoading3d(true)
    setLoadingText('Triggering processing...')
    try {
      await api.triggerProcessing(pid)
      setMeta(m => ({ ...m, status: 'processing' }))
    } catch (err) {
      console.error('Trigger failed:', err)
    } finally {
      setLoading3d(false)
    }
  }

  const handleRefresh = async () => {
    const data = await api.refreshStatus(pid)
    setMeta(m => ({ ...m, status: data.status }))
    if (data.status === 'completed') loadProject()
  }

  // Auto-load first output 3D file if completed
  useEffect(() => {
    if (meta.status === 'completed' && outputFiles.length > 0) {
      const first3d = outputFiles.find(f => ['ply', 'obj', 'glb'].includes(f.name.split('.').pop()))
      if (first3d) loadModel(first3d.url)
    }
  }, [meta.status, outputFiles.length])

  return (
    <div style={{ height: '100vh', display: 'flex', flexDirection: 'column' }}>
      {/* Topbar */}
      <div className="topbar" style={{ height: 56 }}>
        <Link to="/dashboard" style={{ color: 'var(--accent)', fontSize: 20, textDecoration: 'none' }}>←</Link>
        <h1 style={{ fontSize: 16, fontWeight: 600, flex: 1 }}>{meta.name}</h1>
        <span className={`status status-${meta.status}`}>{meta.status}</span>
      </div>

      <div className="viewer-layout">
        {/* Sidebar */}
        <div className="viewer-sidebar">
          <div className="section-title">Input Images</div>
          <div className="upload-area" onClick={() => fileInputRef.current?.click()}>
            <div className="upload-icon">📤</div>
            <div className="upload-text">Drop images or <span>browse</span></div>
          </div>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept="image/*"
            style={{ display: 'none' }}
            onChange={e => handleUpload(e.target.files)}
          />

          <div className="image-list">
            {inputImages.map((src, i) => (
              <div key={i} className="image-thumb">
                <img src={src} alt={`input ${i}`} />
              </div>
            ))}
          </div>

          <div className="sidebar-actions">
            <button
              className="btn"
              onClick={handleTrigger}
              disabled={meta.status === 'processing' || meta.status === 'completed'}
            >
              🚀 Process
            </button>
            <button className="btn btn-outline" onClick={handleRefresh}>↻ Refresh</button>

            {outputFiles.length > 0 && (
              <div style={{ marginTop: 16 }}>
                <div className="section-title">Output Files</div>
                {outputFiles.map((f, i) => (
                  <div key={i} style={{ fontSize: 12, color: '#666', padding: '4px 0', display: 'flex', justifyContent: 'space-between' }}>
                    <span>{f.name}</span>
                    {['ply', 'obj'].includes(f.name.split('.').pop()) && (
                      <button
                        onClick={() => loadModel(f.url)}
                        style={{ background: 'none', border: 'none', color: 'var(--accent)', cursor: 'pointer', fontSize: 12 }}
                      >
                        3D
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* 3D Viewer */}
        <div className="viewer-main">
          <div id="canvas-container" style={{ flex: 1, position: 'relative' }}>
            <canvas ref={canvasRef} id="viewer-canvas" />
            <div className="viewer-placeholder" id="viewerPlaceholder">
              {meta.status === 'completed' ? (
                <>
                  <div className="icon">🌍</div>
                  <div className="text">3D Reconstruction Ready</div>
                  <div className="sub">Click a 3D file to load</div>
                </>
              ) : (
                <>
                  <div className="icon">⏳</div>
                  <div className="text">Awaiting Processing</div>
                  <div className="sub">Upload images and click Process</div>
                </>
              )}
            </div>
          </div>

          <div className="viewer-toolbar">
            <button className="toolbar-btn" title="Front" onClick={() => animateCamera(0, 0)}>▶</button>
            <button className="toolbar-btn" title="Top" onClick={() => animateCamera(-Math.PI/2, 0)}>▲</button>
            <button className="toolbar-btn" title="Wireframe" onClick={toggleWireframe}>◇</button>
            <button className="toolbar-btn" title="Reset" onClick={resetCamera}>⟲</button>
          </div>
        </div>
      </div>

      {/* Loading overlay */}
      <div className={`loading-overlay ${uploading || loading3d ? 'active' : ''}`}>
        <div className="spinner" />
        <div>{loadingText}</div>
        <div className="progress-bar">
          <div className="progress-fill" style={{ width: `${progress}%` }} />
        </div>
      </div>
    </div>
  )
}

// Camera animation helper
function animateCamera(axis, value) {
  // Simplified: just set rotation on mesh if present
}

// Wireframe toggle
let wireframeMode = false
function toggleWireframe() {
  wireframeMode = !wireframeMode
}

// Reset camera
function resetCamera() {
  // Reset handled via camera position update in Viewer
}