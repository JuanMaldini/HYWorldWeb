#!/usr/bin/env python
"""
hw_profile.py — Perfil adaptativo de hardware para el pipeline HYWorld 360.

Objetivo: que el MISMO worker corra desde una GPU de 8 GB hasta una de 24 GB
sin OOM, preservando la maxima calidad posible del GLB 360 completo en cada
maquina. No toca el codigo de HY-World-2.0: solo decide los parametros que el
worker pasa al pipeline (resolucion, n_views, residencia secuencial, etc.).

Palancas reales en una sola GPU (verificadas en el codigo del pipeline):
  - target_size / max_resolution : palanca dominante (cuadratica en VRAM)
  - n_views                      : la atencion cross-view de WorldMirror crece con N
  - save_gs                      : el gaussian-splat consume VRAM extra y NO afecta
                                   al GLB (la malla sale del depth map)
  - sequential_residency         : nunca tener HY-Pano y WorldMirror en VRAM a la vez
  - pano_steps / pano_height/width : coste de la difusion del panorama

OJO: el flag fsdp_cpu_offload del pipeline se IGNORA en single-GPU (lo desactiva
el propio from_pretrained), por eso aqui no dependemos de el. La RAM (y SSD como
pagefile) ayudan al lado host —caching y residencia secuencial— no a la VRAM.

El modulo es autonomo y testeable: no importa nada del worker.
"""

from dataclasses import dataclass, asdict

PATCH_SIZE = 14  # target_size debe ser multiplo de patch_size (WorldMirror/ViT)


@dataclass
class Profile:
    """Conjunto de parametros del pipeline para un tier de hardware."""
    tier: str                      # nombre del escalon
    min_vram_gb: float             # VRAM minima para entrar a este tier
    target_size: int               # resolucion de inferencia WorldMirror (mult. de 14)
    max_resolution: int            # tope de resolucion en compresion/proyeccion
    n_views: int                   # vistas extraidas del panorama
    compress_pts_max_points: int   # tope de puntos en points.ply
    save_gs: bool                  # guardar gaussian-splat (no afecta al GLB)
    sequential_residency: bool     # descargar HY-Pano antes de cargar WorldMirror
    pano_steps: int                # diff_infer_steps de HY-Pano
    pano_height: int               # alto del panorama equirectangular
    pano_width: int                # ancho del panorama equirectangular
    glb_step: int                  # submuestreo depth->malla (1 = maxima densidad)

    # Rellenados en runtime por select_profile()
    vram_gb: float = 0.0
    ram_gb: float = 0.0
    gpu_name: str = ""

    def as_world_settings(self):
        """Defaults que el worker pasa a WorldMirrorPipeline.__call__."""
        return {
            "target_size": self.target_size,
            "max_resolution": self.max_resolution,
            "compress_pts_max_points": self.compress_pts_max_points,
            "save_gs": self.save_gs,
        }

    def summary(self):
        return ("tier=%s vram=%.1fGB ram=%.1fGB | target=%d max_res=%d "
                "n_views=%d pts=%dk save_gs=%s seq_residency=%s "
                "pano=%dx%d/%dsteps glb_step=%d" % (
                    self.tier, self.vram_gb, self.ram_gb, self.target_size,
                    self.max_resolution, self.n_views,
                    self.compress_pts_max_points // 1000, self.save_gs,
                    self.sequential_residency, self.pano_width, self.pano_height,
                    self.pano_steps, self.glb_step))


# ─────────────────────────────────────────────────────────────────────
# Escalera de tiers, de mayor a menor VRAM.
# select_profile() elige el primero cuyo min_vram_gb <= VRAM detectada.
# downgrade_profile() salta al siguiente de menor VRAM (recuperacion de OOM).
# ─────────────────────────────────────────────────────────────────────
_TIERS = [
    Profile(  # 24 GB+  (RTX 4090 / A5000 / 3090...) — maxima calidad
        tier="ultra", min_vram_gb=22.0,
        target_size=1120, max_resolution=2560, n_views=9,
        compress_pts_max_points=4_000_000, save_gs=True,
        sequential_residency=False, pano_steps=50,
        pano_height=1024, pano_width=2048, glb_step=1,
    ),
    Profile(  # 14–22 GB (RTX 4080 / 16GB cards)
        tier="high", min_vram_gb=14.0,
        target_size=1022, max_resolution=2304, n_views=9,
        compress_pts_max_points=3_000_000, save_gs=True,
        sequential_residency=True, pano_steps=50,
        pano_height=1024, pano_width=2048, glb_step=2,
    ),
    Profile(  # 10–14 GB (RTX 3080 10/12GB)
        tier="mid", min_vram_gb=10.0,
        target_size=896, max_resolution=2048, n_views=8,
        compress_pts_max_points=2_500_000, save_gs=False,
        sequential_residency=True, pano_steps=45,
        pano_height=1024, pano_width=2048, glb_step=2,
    ),
    Profile(  # 7–10 GB (RTX 4060 Laptop 8GB / 3070)
        tier="low", min_vram_gb=7.0,
        target_size=700, max_resolution=1600, n_views=7,
        compress_pts_max_points=1_500_000, save_gs=False,
        sequential_residency=True, pano_steps=40,
        pano_height=768, pano_width=1536, glb_step=2,
    ),
    Profile(  # <7 GB — modo supervivencia (o CPU)
        tier="min", min_vram_gb=0.0,
        target_size=518, max_resolution=1280, n_views=5,
        compress_pts_max_points=1_000_000, save_gs=False,
        sequential_residency=True, pano_steps=30,
        pano_height=512, pano_width=1024, glb_step=3,
    ),
]


def _round_patch(n):
    """Redondea a la baja al multiplo de PATCH_SIZE mas cercano (min 2*patch)."""
    return max((int(n) // PATCH_SIZE) * PATCH_SIZE, PATCH_SIZE * 2)


def detect_hardware():
    """Devuelve (vram_gb, ram_gb, gpu_name, cuda_available).

    No lanza excepciones: si algo falla, devuelve ceros y cuda=False.
    """
    vram_gb, ram_gb, gpu_name, cuda = 0.0, 0.0, "", False
    try:
        import torch
        cuda = bool(torch.cuda.is_available())
        if cuda:
            props = torch.cuda.get_device_properties(0)
            vram_gb = props.total_memory / 1e9
            gpu_name = props.name
    except Exception:
        pass
    if not cuda or vram_gb == 0.0:
        # Fallback: nvidia-smi (por si torch no ve la GPU pero existe)
        try:
            import subprocess
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=8)
            line = (out.stdout or "").strip().splitlines()
            if line:
                name, mem = line[0].split(",")
                gpu_name = gpu_name or name.strip()
                vram_gb = vram_gb or float(mem.strip()) / 1024.0
                cuda = True
        except Exception:
            pass
    try:
        import psutil
        ram_gb = psutil.virtual_memory().total / 1e9
    except Exception:
        pass
    return vram_gb, ram_gb, gpu_name, cuda


def select_profile(vram_gb, ram_gb=0.0, gpu_name="", cuda=True):
    """Elige el Profile adecuado para la VRAM detectada.

    Si no hay CUDA, fuerza el tier 'min' (CPU: solo viable a baja resolucion).
    """
    import copy
    if not cuda or vram_gb <= 0:
        prof = copy.deepcopy(_TIERS[-1])
    else:
        prof = None
        for t in _TIERS:
            if vram_gb >= t.min_vram_gb:
                prof = copy.deepcopy(t)
                break
        if prof is None:
            prof = copy.deepcopy(_TIERS[-1])
    prof.vram_gb = round(float(vram_gb), 1)
    prof.ram_gb = round(float(ram_gb), 1)
    prof.gpu_name = gpu_name
    prof.target_size = _round_patch(prof.target_size)
    return prof


def downgrade_profile(prof):
    """Devuelve el siguiente tier de MENOR VRAM (para reintento tras OOM),
    conservando la info de hardware detectada. Si ya es el minimo, devuelve None.
    """
    import copy
    idx = next((i for i, t in enumerate(_TIERS) if t.tier == prof.tier), None)
    if idx is None or idx >= len(_TIERS) - 1:
        return None
    nxt = copy.deepcopy(_TIERS[idx + 1])
    nxt.vram_gb, nxt.ram_gb, nxt.gpu_name = prof.vram_gb, prof.ram_gb, prof.gpu_name
    nxt.target_size = _round_patch(nxt.target_size)
    return nxt


def clamp_settings_to_profile(user_settings, prof):
    """Acota los settings que vienen del frontend al techo del perfil de hardware.

    El frontend (generateMesh) pide calidad maxima (p.ej. target_size=1120). En
    una GPU chica eso reventaria; aqui la peticion del usuario se respeta como
    'deseo' pero el hardware manda: effective = min(deseo, tope del perfil).
    Devuelve un dict listo para WorldMirrorPipeline.
    """
    out = dict(prof.as_world_settings())
    u = dict(user_settings or {})
    # Resoluciones: nunca por encima del perfil
    if u.get("target_size") is not None:
        out["target_size"] = _round_patch(min(int(u["target_size"]), prof.target_size))
    if u.get("max_resolution") is not None:
        out["max_resolution"] = min(int(u["max_resolution"]), prof.max_resolution)
    # max_points: alias del frontend (max_points) o nombre real
    mp = u.get("compress_pts_max_points", u.get("max_points"))
    if mp is not None:
        out["compress_pts_max_points"] = min(int(mp), prof.compress_pts_max_points)
    # save_gs: solo si el perfil lo permite (en VRAM baja se fuerza a False)
    if u.get("save_gs") is not None:
        out["save_gs"] = bool(u["save_gs"]) and prof.save_gs
    # Flags de mascara que el worker ya pasaba: respetar si vienen
    for k in ("apply_sky_mask", "apply_edge_mask", "apply_confidence_mask",
              "save_points", "save_depth", "save_normal", "save_camera"):
        if u.get(k) is not None:
            out[k] = u[k]
    return out


if __name__ == "__main__":
    # Smoke test rapido por linea de comandos
    for v in (24, 16, 12, 8, 6, 0):
        p = select_profile(v, ram_gb=64, gpu_name="test", cuda=(v > 0))
        print("VRAM %2dGB -> %s" % (v, p.summary()))
    print("\nLadder de downgrade desde 'low':")
    cur = select_profile(8, 64, "RTX 4060 Laptop")
    while cur is not None:
        print("  ", cur.tier, "target=%d" % cur.target_size, "n_views=%d" % cur.n_views)
        cur = downgrade_profile(cur)
