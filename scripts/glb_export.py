"""
glb_export.py — Convierte depth maps + camera params a malla 3D GLB.
Importado por worker.py. Sin CUDA, sin re-inferencia.
"""
import os
import glob
import json
import logging
import numpy as np

log = logging.getLogger("worker")


def export_glb(slug, projects_dir):
    """Genera mesh.glb desde depth map + imagen de vista.

    Proyecta cada pixel del depth map a 3D usando los intrínsecos de cámara,
    conecta píxeles adyacentes con triángulos filtrando discontinuidades de
    profundidad (flying triangles en bordes de objetos).

    Fallback automático a nube de puntos si faltan depth maps.
    """
    import trimesh
    from PIL import Image

    output_dir = os.path.join(projects_dir, slug, "output")
    views_dir  = os.path.join(projects_dir, slug, "views")
    glb_path   = os.path.join(output_dir, "mesh.glb")

    depth_files = sorted(glob.glob(os.path.join(output_dir, "depth", "depth_*.npy")))
    view_files  = sorted(
        glob.glob(os.path.join(views_dir, "*.png")) +
        glob.glob(os.path.join(views_dir, "*.jpg"))
    )
    cam_path = os.path.join(output_dir, "camera_params.json")

    if not depth_files or not view_files or not os.path.exists(cam_path):
        log.warning("  [%s] glb: sin depth maps — fallback nube de puntos" % slug)
        return _export_pointcloud(slug, projects_dir, glb_path)

    try:
        with open(cam_path) as f:
            cam_data = json.load(f)
    except Exception as e:
        log.warning("  [%s] glb: camera_params.json no legible: %s — fallback" % (slug, e))
        return _export_pointcloud(slug, projects_dir, glb_path)

    log.info("  [%s] glb: reconstruyendo malla desde %d depth map(s)..." % (
        slug, len(depth_files)))

    all_verts  = []
    all_colors = []
    all_faces  = []
    total_verts = 0

    for i, (depth_path, view_path) in enumerate(zip(depth_files, view_files)):
        STEP = 2  # submuestreo 2x → 4x menos triangulos, ~7 MB vs 28 MB
        depth = np.load(depth_path).astype(np.float32)
        if depth.ndim == 3:
            depth = depth[..., 0]
        depth = depth[::STEP, ::STEP]

        img = np.array(Image.open(view_path).convert("RGB"))
        if img.shape[:2] != depth.shape:
            img = np.array(Image.fromarray(img).resize(
                (depth.shape[1], depth.shape[0]), Image.BILINEAR))

        H, W = depth.shape

        ci   = min(i, len(cam_data["intrinsics"]) - 1)
        intr = cam_data["intrinsics"][ci]["matrix"]
        fx, fy = float(intr[0][0]) / STEP, float(intr[1][1]) / STEP
        cx, cy = float(intr[0][2]) / STEP, float(intr[1][2]) / STEP

        ei   = min(i, len(cam_data["extrinsics"]) - 1)
        E    = np.array(cam_data["extrinsics"][ei]["matrix"], dtype=np.float64)
        Rt, t = E[:3, :3].T, E[:3, 3]

        # Desproyectar pixels a espacio cámara
        ys, xs = np.mgrid[0:H, 0:W]
        Z = depth
        X = (xs - cx) * Z / fx
        Y = (ys - cy) * Z / fy

        # Transformar a espacio mundo
        pts_cam   = np.stack([X, Y, Z], axis=-1).reshape(-1, 3)
        pts_world = (pts_cam - t) @ Rt

        # Máscara válidos
        valid_2d   = (Z > 0.05) & (Z < 100.0)
        valid_flat = valid_2d.ravel()

        # Índice de vértice por pixel
        idx_grid = np.full(H * W, -1, dtype=np.int32)
        idx_grid[valid_flat] = (
            np.arange(int(valid_flat.sum()), dtype=np.int32) + total_verts
        )
        idx_grid = idx_grid.reshape(H, W)

        # Crear triángulos vectorizado (quad → 2 triángulos)
        yy, xx = np.mgrid[0:H-1, 0:W-1]
        v00 = idx_grid[yy,   xx  ]
        v10 = idx_grid[yy+1, xx  ]
        v01 = idx_grid[yy,   xx+1]
        v11 = idx_grid[yy+1, xx+1]

        # Filtrar flying triangles (salto de profundidad > 15% o > 10cm)
        Z00 = Z[yy,   xx  ]; Z10 = Z[yy+1, xx  ]
        Z01 = Z[yy,   xx+1]; Z11 = Z[yy+1, xx+1]

        ref1 = np.maximum(np.maximum(Z00, Z10), Z01)
        thr1 = np.maximum(ref1 * 0.15, 0.1)
        ok1  = ((v00 >= 0) & (v10 >= 0) & (v01 >= 0) &
                (np.abs(Z00 - Z10) < thr1) &
                (np.abs(Z00 - Z01) < thr1) &
                (np.abs(Z10 - Z01) < thr1))

        ref2 = np.maximum(np.maximum(Z10, Z11), Z01)
        thr2 = np.maximum(ref2 * 0.15, 0.1)
        ok2  = ((v10 >= 0) & (v11 >= 0) & (v01 >= 0) &
                (np.abs(Z10 - Z11) < thr2) &
                (np.abs(Z10 - Z01) < thr2) &
                (np.abs(Z11 - Z01) < thr2))

        tri1 = np.stack([v00[ok1], v10[ok1], v01[ok1]], axis=1)
        tri2 = np.stack([v10[ok2], v11[ok2], v01[ok2]], axis=1)

        verts  = pts_world[valid_flat].astype(np.float32)
        colors = img.reshape(-1, 3)[valid_flat]

        all_verts.append(verts)
        all_colors.append(colors)
        if tri1.shape[0]: all_faces.append(tri1)
        if tri2.shape[0]: all_faces.append(tri2)
        total_verts += len(verts)

        log.info("  [%s] glb: vista %d → %d verts | %d tris" % (
            slug, i, len(verts), tri1.shape[0] + tri2.shape[0]))

    if not all_verts:
        return _export_pointcloud(slug, projects_dir, glb_path)

    vertices = np.concatenate(all_verts)
    colors   = np.concatenate(all_colors)
    faces    = (np.concatenate(all_faces) if all_faces
                else np.zeros((0, 3), dtype=np.int32))

    colors_rgba = np.concatenate(
        [colors, np.full((len(colors), 1), 255, dtype=np.uint8)], axis=1)

    try:
        mesh = trimesh.Trimesh(
            vertices=vertices, faces=faces,
            vertex_colors=colors_rgba, process=False)
        mesh.export(glb_path)
    except Exception as e:
        log.error("  [%s] glb: export fallido: %s — fallback" % (slug, e))
        return _export_pointcloud(slug, projects_dir, glb_path)

    if not os.path.exists(glb_path) or os.path.getsize(glb_path) == 0:
        return _export_pointcloud(slug, projects_dir, glb_path)

    log.info("  [%s] glb: mesh.glb generado — %d verts | %d tris | %.2f MB" % (
        slug, len(vertices), len(faces),
        os.path.getsize(glb_path) / 1e6))
    return glb_path


def _export_pointcloud(slug, projects_dir, glb_path):
    """Fallback: exporta points.ply como nube de puntos GLB."""
    import trimesh
    ply_path = os.path.join(projects_dir, slug, "output", "points.ply")
    if not os.path.exists(ply_path):
        log.error("  [%s] glb: points.ply tampoco existe" % slug)
        return None
    try:
        cloud = trimesh.load(ply_path, process=False)
        cloud.export(glb_path)
        log.info("  [%s] glb: fallback nube de puntos (%.2f MB)" % (
            slug, os.path.getsize(glb_path) / 1e6))
        return glb_path
    except Exception as e:
        log.error("  [%s] glb: fallback fallo: %s" % (slug, e))
        return None
