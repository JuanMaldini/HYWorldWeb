#!/usr/bin/env python
"""
hw_profile.py — Perfil adaptativo de hardware para el pipeline HYWorld 360.

Objetivo: que el MISMO worker corra desde una GPU de 8 GB hasta una de 24 GB
sin OOM, preservando SIEMPRE el espacio 360 completo (esfera entera: paredes,
techo y suelo). No toca el codigo de HY-World-2.0: solo decide los parametros
que el worker pasa al pipeline.

Palancas reales en una sola GPU (verificadas en el codigo del pipeline):
  - target_size / max_resolution : palanca dominante (cuadratica en VRAM)
  - n_views                      : la atencion cross-view de WorldMirror crece con N
  - save_gs                      : el gaussian-splat consume VRAM extra y NO afecta
                                   al GLB (la malla sale del depth map)
  - sequential_residency         : nunca tener HY-Pano y WorldMirror en VRAM a la vez
  - pano_steps / pano_height/width : coste de la difusion del panorama

MODELO DE COSTE — "presupuesto de tokens"
-----------------------------------------
La VRAM de WorldMirror la domina el numero total de parches ViT en juego:

    tokens = n_views * (target_size / PATCH_SIZE) ** 2

Por eso cada tier declara un `token_budget` y el numero de vistas del layout
esferico; `target_size` se DERIVA para caber en ese presupuesto. Asi, anadir
las vistas de techo/suelo no dispara la VRAM: se paga bajando resolucion por
vista, que es justo donde sobraba (ver nota de sobremuestreo abajo).

NOTA DE SOBREMUESTREO (por que bajar target_size no cuesta calidad real):
un panorama equirectangular de PANO_W px cubre 360°. Una vista de FOV grados
contiene, como maximo, PANO_W * FOV / 360 pixeles de informacion REAL. Con
PANO_W=2048 y FOV=65 son ~370 px. Renderizar esa vista a 1024 px (como hacia
la version anterior) es interpolar aire: triplica el coste sin anadir detalle.
`view_resolution()` calcula la resolucion honesta a partir del panorama.

OJO: el flag fsdp_cpu_offload del pipeline se IGNORA en single-GPU (lo desactiva
el propio from_pretrained), por eso aqui no dependemos de el. La RAM (y SSD como
pagefile) ayudan al lado host —caching y residencia secuencial— no a la VRAM.

El modulo es autonomo y testeable: no importa nada del worker.
"""

import math
from dataclasses import dataclass, field

PATCH_SIZE = 14  # target_size debe ser multiplo de patch_size (WorldMirror/ViT)

# Resolucion minima de inferencia por vista (por debajo WorldMirror degrada mucho)
MIN_TARGET_SIZE = 322   # 23 parches

# ── Geometria del layout esferico ────────────────────────────────────
# Estos tres valores NO son arbitrarios: salen de un barrido que mide, sobre
# ~20.000 direcciones repartidas por la esfera, que fraccion no cae dentro del
# frustum de ninguna vista. Con RING_ELEVATION=55 y MIN_FOV=75 la fraccion sin
# cubrir es 0.00% para todos los recuentos de vistas soportados; bajando el FOV
# a 65 aparecia un hueco anular en torno a |el|~41 grados (1.06% de la esfera).
#
# El detalle que lo explica: una vista cuadrada NO alcanza la misma elevacion en
# su eje que en sus esquinas. Con FOV F, en el eje llega a F/2, pero en la
# esquina solo a asin(tan(F/2) / sqrt(1 + 2*tan^2(F/2))), sensiblemente menos.
# El solape hay que calcularlo contra las ESQUINAS, no contra el eje.
RING_ELEVATION = 55.0
# Margen de solape horizontal: FOV = (360/N) * OVERLAP_FACTOR
OVERLAP_FACTOR = 1.35
MIN_FOV, MAX_FOV = 75.0, 100.0


@dataclass
class Profile:
    """Conjunto de parametros del pipeline para un tier de hardware."""
    tier: str                      # nombre del escalon
    min_vram_gb: float             # VRAM minima para entrar a este tier
    token_budget: int              # parches ViT totales (n_views * (ts/14)^2)
    n_horizontal: int              # vistas del anillo ecuatorial (el=0)
    max_target_size: int           # techo de resolucion de inferencia
    max_resolution: int            # tope de resolucion en compresion/proyeccion
    compress_pts_max_points: int   # tope de puntos en points.ply
    save_gs: bool                  # guardar gaussian-splat (no afecta al GLB)
    sequential_residency: bool     # descargar un modelo antes de cargar el otro
    pano_steps: int                # diff_infer_steps de HY-Pano
    pano_height: int               # alto del panorama equirectangular
    pano_width: int                # ancho del panorama equirectangular
    glb_step: int                  # submuestreo depth->malla (1 = maxima densidad)

    # Rellenados en runtime por select_profile()
    vram_gb: float = 0.0
    ram_gb: float = 0.0
    gpu_name: str = ""

    # ── Derivados ────────────────────────────────────────────────────
    @property
    def n_ring(self):
        """Vistas de CADA anillo polar (techo y suelo), derivado del ecuatorial.

        Se DERIVA a proposito, en vez de guardarse como campo independiente: el
        barrido de cobertura muestra que la pareja (n_horizontal, n_ring) tiene
        que ir acompasada, y cuando un preset las escalaba por separado aparecia
        un hueco (n_h=6 con n_ring=3 dejaba 0.02% de la esfera sin cubrir).
        Derivandolo, ningun preset puede volver a desincronizarlas.
        """
        if self.n_horizontal <= 5:
            return 3
        return max(4, int(round(self.n_horizontal / 2.0)))

    @property
    def n_views(self):
        """Total de vistas del layout esferico completo."""
        return self.n_horizontal + 2 * self.n_ring

    @property
    def fov(self):
        """FOV (grados) derivado del numero de vistas horizontales.

        Se calcula para GARANTIZAR solape: nunca deja huecos entre vistas
        contiguas, que era el fallo del FOV fijo de 60 grados con n_views bajo.
        """
        return max(MIN_FOV, min(MAX_FOV, (360.0 / self.n_horizontal) * OVERLAP_FACTOR))

    @property
    def target_size(self):
        """Resolucion de inferencia por vista.

        Es el minimo de tres topes, y ese orden importa:
          1. el presupuesto de tokens (VRAM disponible),
          2. el techo del tier,
          3. la INFORMACION REAL que el panorama aporta en el FOV de la vista.

        El tercer tope es el que la version anterior ignoraba: alimentar a
        WorldMirror con 658 px cuando el panorama solo aporta 364 px reales
        cuesta 3.3x los tokens para reconstruir pixeles interpolados. Atarlo a
        `_honest_view_px` baja la VRAM sin perder ni un detalle real.
        """
        per_view = self.token_budget / float(max(1, self.n_views))
        side = int(math.sqrt(max(per_view, 1.0))) * PATCH_SIZE
        side = min(_round_patch(side), self.max_target_size, self._honest_view_px)
        return max(MIN_TARGET_SIZE, side)

    @property
    def _honest_view_px(self):
        """Pixeles reales que el panorama aporta dentro del FOV de una vista.

        Un equirectangular de pano_width px cubre 360 grados; una vista de FOV
        grados contiene como maximo pano_width * FOV / 360 pixeles de detalle.
        """
        return _round_patch(self.pano_width * (self.fov / 360.0))

    def view_layout(self):
        """Lista de (azimuth, elevacion) que cubre la ESFERA COMPLETA.

        - Anillo ecuatorial: n_horizontal vistas repartidas en 360 grados.
        - Anillo superior e inferior: n_ring vistas cada uno a +-RING_ELEVATION,
          desfasadas media division para maximizar cobertura.

        A |el|=RING_ELEVATION la circunferencia se encoge por cos(el), asi que
        cada vista cubre FOV/cos(el) grados de azimut: por eso n_ring < n_horizontal
        basta para cerrar el anillo con solape.
        """
        out = []
        step = 360.0 / self.n_horizontal
        for i in range(self.n_horizontal):
            out.append((round(i * step, 2), 0.0))
        if self.n_ring > 0:
            rstep = 360.0 / self.n_ring
            for i in range(self.n_ring):
                az = round(i * rstep + rstep / 2.0, 2)
                out.append((az, RING_ELEVATION))
            for i in range(self.n_ring):
                az = round(i * rstep + rstep / 2.0, 2)
                out.append((az, -RING_ELEVATION))
        return out

    def view_resolution(self):
        """Resolucion (px) a la que extraer cada vista del panorama.

        Coincide con target_size: extraer por encima solo interpola (gasta
        RAM/disco sin detalle) y extraer por debajo obligaria a WorldMirror a
        reescalar hacia arriba. Igualarlos evita los dos resampleos.
        """
        return self.target_size

    def as_world_settings(self):
        """Defaults que el worker pasa a WorldMirrorPipeline.__call__."""
        return {
            "target_size": self.target_size,
            "max_resolution": self.max_resolution,
            "compress_pts_max_points": self.compress_pts_max_points,
            "save_gs": self.save_gs,
        }

    def caps(self):
        """Techos publicables al frontend (para mostrar el valor EFECTIVO)."""
        return {
            "tier": self.tier,
            "gpu": self.gpu_name,
            "vram_gb": self.vram_gb,
            "target_size": self.target_size,
            "max_resolution": self.max_resolution,
            "max_points": self.compress_pts_max_points,
            "n_views": self.n_views,
            "pano_width": self.pano_width,
            "pano_height": self.pano_height,
            "save_gs": self.save_gs,
        }

    def summary(self):
        return ("tier=%s vram=%.1fGB ram=%.1fGB | target=%d max_res=%d "
                "views=%d (%dh+2x%d) fov=%.0f view_px=%d pts=%dk save_gs=%s "
                "seq_res=%s pano=%dx%d/%dsteps glb_step=%d tokens=%dk" % (
                    self.tier, self.vram_gb, self.ram_gb, self.target_size,
                    self.max_resolution, self.n_views, self.n_horizontal,
                    self.n_ring, self.fov, self.view_resolution(),
                    self.compress_pts_max_points // 1000, self.save_gs,
                    self.sequential_residency, self.pano_width, self.pano_height,
                    self.pano_steps, self.glb_step,
                    (self.n_views * (self.target_size // PATCH_SIZE) ** 2) // 1000))


# ─────────────────────────────────────────────────────────────────────
# Escalera de tiers, de mayor a menor VRAM.
# select_profile() elige el primero cuyo min_vram_gb <= VRAM detectada.
# downgrade_profile() salta al siguiente de menor VRAM (recuperacion de OOM).
#
# token_budget calibrado para que el tier 'mid' (RTX 3080 10GB) quede en el
# mismo consumo que la version anterior (8 vistas x 64^2 parches = 32.7k), pero
# gastandolo en 16 vistas que SI cubren la esfera completa.
# ─────────────────────────────────────────────────────────────────────
_TIERS = [
    Profile(  # 24 GB+  (RTX 4090 / A5000 / 3090...) — maxima calidad
        tier="ultra", min_vram_gb=22.0,
        token_budget=153_600, n_horizontal=12,
        max_target_size=1120, max_resolution=2560,
        compress_pts_max_points=4_000_000, save_gs=True,
        sequential_residency=False, pano_steps=50,
        pano_height=1536, pano_width=3072, glb_step=1,
    ),
    Profile(  # 14–22 GB (RTX 4080 / 16GB cards)
        tier="high", min_vram_gb=14.0,
        token_budget=106_000, n_horizontal=10,
        max_target_size=1022, max_resolution=2304,
        compress_pts_max_points=3_000_000, save_gs=True,
        sequential_residency=True, pano_steps=50,
        pano_height=1280, pano_width=2560, glb_step=2,
    ),
    Profile(  # 10–14 GB (RTX 3080 10/12GB)
        tier="mid", min_vram_gb=10.0,
        token_budget=36_800, n_horizontal=8,
        max_target_size=896, max_resolution=2048,
        compress_pts_max_points=2_500_000, save_gs=False,
        sequential_residency=True, pano_steps=45,
        pano_height=1024, pano_width=2048, glb_step=2,
    ),
    Profile(  # 7–10 GB (RTX 4060 Laptop 8GB / 3070)
        tier="low", min_vram_gb=7.0,
        token_budget=22_400, n_horizontal=6,
        max_target_size=700, max_resolution=1600,
        compress_pts_max_points=1_500_000, save_gs=False,
        sequential_residency=True, pano_steps=40,
        pano_height=1024, pano_width=2048, glb_step=2,
    ),
    Profile(  # <7 GB — modo supervivencia (o CPU)
        tier="min", min_vram_gb=0.0,
        token_budget=11_300, n_horizontal=5,
        max_target_size=518, max_resolution=1280,
        compress_pts_max_points=1_000_000, save_gs=False,
        sequential_residency=True, pano_steps=30,
        pano_height=768, pano_width=1536, glb_step=3,
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
    return nxt


def pano_fallback_ladder(prof):
    """Escalera de degradacion del PANORAMA para recuperarse de un OOM.

    Devuelve una lista de dicts (height, width, steps) de mas a menos exigente,
    empezando por los parametros del perfil. El objetivo es NO perder nunca el
    360: antes de rendirse y caer a "solo frente", se intenta el panorama con
    menos pasos de difusion y luego con menos resolucion.

    Orden de las palancas: primero `steps` (lineal en tiempo, casi plano en
    VRAM pico) y despues la resolucion (cuadratica en VRAM).
    """
    h, w, s = prof.pano_height, prof.pano_width, prof.pano_steps
    ladder = [{"height": h, "width": w, "steps": s}]
    # 1) menos pasos, misma resolucion
    if s > 30:
        ladder.append({"height": h, "width": w, "steps": max(30, int(s * 0.6))})
    # 2) media resolucion (siempre 2:1 equirectangular)
    while h > 512:
        h, w = h // 2, w // 2
        ladder.append({"height": h, "width": w, "steps": max(25, int(s * 0.6))})
    return ladder


def apply_preset(prof, preset):
    """Aplica un preset del frontend ('min'|'med'|'max') sobre el perfil.

    El preset es un dial de VELOCIDAD/CALIDAD, NO de cobertura: la esfera
    completa (anillo ecuatorial + anillos de techo y suelo) se mantiene SIEMPRE.

    QUE escala el preset, y por que en ese orden:

      1. `pano_width/height` — es la palanca de DETALLE real. Con muestreo
         honesto, el panorama fija los px/grado disponibles; ninguna otra
         palanca puede inventar detalle que el panorama no tenga.
      2. `n_horizontal` / `n_ring` — densidad angular de vistas (geometria).
      3. `pano_steps` — calidad de la difusion (la etapa mas lenta del pipeline).
      4. `max_points` / `save_gs` — peso del resultado.

    OJO — por que NO se escala `target_size` directamente: al derivarse de los
    px/grado del panorama y del FOV, bajar el numero de vistas SUBE el FOV y por
    tanto SUBE los px por vista. Escalar target_size a mano invertia el coste
    (MIN salia mas caro que MAX). Escalando el panorama, el coste total queda
    monotono: MIN < MED < MAX.

    El hardware sigue mandando: el preset solo baja, nunca sube por encima del tier.
    """
    import copy
    key = str(preset).lower()
    scale = {"min": 0.45, "med": 0.72, "max": 1.0}.get(key)
    if scale is None or scale >= 1.0:
        return prof
    out = copy.deepcopy(prof)
    # 1. Panorama: se mantiene la relacion 2:1 y multiplos de 128 (los VAE de
    #    difusion trabajan con factores de 8/16; 128 es seguro para todos).
    pw = max(1024, int(prof.pano_width * scale) // 128 * 128)
    out.pano_width, out.pano_height = pw, pw // 2
    # 2. Densidad de vistas. Nunca por debajo de 5 horizontales / 3 por anillo:
    #    menos que eso deja de ser un espacio reconstruible.
    out.n_horizontal = max(5, int(round(prof.n_horizontal * scale)))
    # 3. Difusion
    out.pano_steps = max(25, int(round(prof.pano_steps * (0.6 + 0.4 * scale))))
    # 4. Peso del resultado
    out.compress_pts_max_points = max(500_000, int(prof.compress_pts_max_points * scale))
    out.max_resolution = max(1024, _round_patch(int(prof.max_resolution * scale)))
    out.token_budget = int(prof.token_budget * scale)
    if scale < 0.6:
        out.save_gs = False
    return out


def clamp_settings_to_profile(user_settings, prof):
    """Acota los settings que vienen del frontend al techo del perfil de hardware.

    El frontend pide una calidad (preset); en una GPU chica eso reventaria, asi
    que la peticion del usuario se respeta como 'deseo' pero el hardware manda:
    effective = min(deseo, tope del perfil).
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


def publish_caps(prof):
    """Resumen del hardware + valores EFECTIVOS de los tres presets.

    El worker lo escribe en el record y el frontend lo muestra, de forma que
    "Maxima" no mienta: en una GPU de 10 GB el usuario ve exactamente cuantas
    vistas y que panorama va a obtener antes de lanzar la generacion.
    """
    if prof is None:
        return None
    return {
        "tier": prof.tier,
        "gpu": prof.gpu_name,
        "vram_gb": prof.vram_gb,
        "ram_gb": prof.ram_gb,
        "presets": {q: apply_preset(prof, q).caps() for q in ("min", "med", "max")},
    }


def effective_profile(prof, settings):
    """Perfil EFECTIVO = perfil de hardware + preset del usuario.

    Es el que el worker debe usar para el layout de vistas y el panorama.
    `settings['quality']` puede ser 'min'|'med'|'max' (default 'max').
    """
    return apply_preset(prof, (settings or {}).get("quality", "max"))


if __name__ == "__main__":
    # Smoke test rapido por linea de comandos
    for v in (24, 16, 12, 8, 6, 0):
        p = select_profile(v, ram_gb=64, gpu_name="test", cuda=(v > 0))
        print("VRAM %2dGB -> %s" % (v, p.summary()))
        lay = p.view_layout()
        assert len(lay) == p.n_views, (len(lay), p.n_views)
        # Verificar que no hay huecos horizontales: paso < FOV
        assert 360.0 / p.n_horizontal < p.fov, "hueco horizontal en %s" % p.tier
        # Verificar cierre de polos: el anillo + medio FOV alcanza 90 grados
        assert RING_ELEVATION + p.fov / 2 >= 90.0, "cenit sin cubrir en %s" % p.tier

    print("\nPresets sobre 'mid' (RTX 3080 10GB):")
    base = select_profile(10.7, 64, "RTX 3080")
    _prev_cost = -1
    for q in ("min", "med", "max"):
        e = apply_preset(base, q)
        cost = e.n_views * (e.target_size // PATCH_SIZE) ** 2
        print("  %-4s -> %s" % (q, e.summary()))
        # El coste DEBE crecer con el preset (min < med < max). Si no, el dial
        # de calidad esta invertido y el usuario paga mas por pedir menos.
        assert cost > _prev_cost, "preset %s no es monotono (%d <= %d)" % (
            q, cost, _prev_cost)
        assert len(e.view_layout()) == e.n_views
        assert 360.0 / e.n_horizontal < e.fov, "hueco horizontal en preset %s" % q
        assert RING_ELEVATION + e.fov / 2 >= 90.0, "cenit sin cubrir en preset %s" % q
        _prev_cost = cost

    print("\nLadder de downgrade desde 'low':")
    cur = select_profile(8, 64, "RTX 4060 Laptop")
    while cur is not None:
        print("   %-5s target=%4d views=%2d fov=%.0f" % (
            cur.tier, cur.target_size, cur.n_views, cur.fov))
        cur = downgrade_profile(cur)

    print("\nLadder de panorama desde 'mid':")
    for stepcfg in pano_fallback_ladder(base):
        print("  ", stepcfg)
