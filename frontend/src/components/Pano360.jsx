import { useEffect, useRef } from 'react'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'

// Visor 360: esfera invertida con el panorama equirectangular como textura.
// Click/drag para mirar alrededor, auto-rotacion suave.
export default function Pano360({ url }) {
  const mountRef = useRef(null)

  useEffect(() => {
    const mount = mountRef.current
    if (!mount) return
    const w = mount.clientWidth || 800
    const h = mount.clientHeight || 400

    const scene = new THREE.Scene()
    const camera = new THREE.PerspectiveCamera(75, w / h, 0.1, 1100)
    camera.position.set(0, 0, 0.1)

    const renderer = new THREE.WebGLRenderer({ antialias: true })
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    renderer.setSize(w, h)
    mount.appendChild(renderer.domElement)

    // Esfera invertida: se ve desde adentro
    const geometry = new THREE.SphereGeometry(500, 60, 40)
    geometry.scale(-1, 1, 1)
    const texture = new THREE.TextureLoader().load(url)
    texture.colorSpace = THREE.SRGBColorSpace
    const material = new THREE.MeshBasicMaterial({ map: texture })
    scene.add(new THREE.Mesh(geometry, material))

    const controls = new OrbitControls(camera, renderer.domElement)
    controls.enableZoom = false
    controls.enablePan = false
    controls.enableDamping = true
    controls.dampingFactor = 0.08
    controls.rotateSpeed = -0.3   // negativo: arrastrar se siente como mover la vista
    controls.autoRotate = true
    controls.autoRotateSpeed = 0.4

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
      controls.dispose()
      geometry.dispose(); material.dispose(); texture.dispose()
      renderer.dispose()
      if (renderer.domElement.parentNode === mount) mount.removeChild(renderer.domElement)
    }
  }, [url])

  return (
    <div ref={mountRef} style={{
      width: '100%', height: 400, borderRadius: 8, overflow: 'hidden',
      border: '1px solid var(--border)', background: 'var(--bg-dark)', cursor: 'grab',
    }} />
  )
}
