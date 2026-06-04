# ============================================================
# HYWorld — Docker Image
# Base: NVIDIA CUDA 12.8 + Ubuntu 22.04 + Python 3.11
# ============================================================

FROM nvidia/cuda:12.8.1-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive

# ── System dependencies ────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.11 \
    python3.11-dev \
    python3-pip \
    curl \
    git \
    git-lfs \
    wget \
    libatomic1 \
    libgl1-mesa-glx \
    libgl1-mesa-dri \
    libegl1 \
    libglib2.0-0 \
    && git lfs install \
    && rm -rf /var/lib/apt/lists/*

# ── pnpm ────────────────────────────────────────────────────
ENV SHELL=/bin/bash
RUN curl -fsSL https://get.pnpm.io/install.sh | sh -

ENV PATH="/root/.local/share/pnpm:$PATH"
ENV PNPM_HOME="/root/.local/share/pnpm"

# ── Python pip upgrade ─────────────────────────────────────
RUN python3.11 -m pip install --upgrade pip setuptools wheel

# ── PyTorch + CUDA ─────────────────────────────────────────
RUN pip install --no-cache-dir torch==2.7.1 torchvision==0.22.1 --index-url https://download.pytorch.org/whl/cu126

# ── Python deps (sin torch que ya está) ────────────────────
RUN pip install --no-cache-dir \
    diffusers==0.36.0 transformers==5.2.0 accelerate peft==0.18.1 \
    safetensors zim_anything tensorboard omegaconf einops kornia openai \
    easydict scipy==1.14.1 timm==1.0.11 \
    Pillow imageio[ffmpeg] decord imagesize opencv-python-headless==4.10.0.84 \
    matplotlib==3.10.3 scikit-image==0.25.2 ftfy regex \
    trimesh plyfile open3d==0.18.0 pycolmap==3.10.0 \
    torchmetrics loguru==0.7.3 tqdm viser tyro==1.0.8 splines \
    pymeshlab==2023.12.post2 scikit-build-core nanobind pybind11 \
    numpy==1.26.4 psutil requests

# ── cupy (requerido por hyworld2/worldrecon) ──────────────
RUN pip install --no-cache-dir cupy-cuda12x==13.6.0

# ── gsplat (REQUERIDO por worldrecon — sin esto ML=NO LISTO) ──
# Arch de compilacion: Ampere (RTX 3080 = 8.6); ajustar si usas otra GPU.
ENV TORCH_CUDA_ARCH_LIST="8.6"
RUN pip install --no-build-isolation git+https://github.com/nerfstudio-project/gsplat.git

# ── Git-based deps + flash-attn (optional, ignore failures) ──
RUN pip install --no-build-isolation \
    git+https://github.com/rahul-goel/fused-ssim@328dc9836f513d00c4b5bc38fe30478b4435cbb5 \
    git+https://github.com/nianticlabs/spz.git@v3.0.0 || true

# ── flash-attn (requires CUDA kernel compilation — may fail on some GPUs) ──
RUN pip install flash-attn --no-build-isolation || true

# ── Entry point ────────────────────────────────────────────
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]