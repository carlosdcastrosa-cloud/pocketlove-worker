FROM nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV CKPT_NAME=bigLust_v16.safetensors
ENV DMD2_LORA=dmd2_sdxl_4step_lora.safetensors
ENV DMD2_STRENGTH=0.7
ENV DEFAULT_STEPS=10
ENV DEFAULT_CFG=1
ENV DEFAULT_SAMPLER=lcm
ENV DEFAULT_SCHEDULER=karras
ENV WORKFLOW_JSON=""

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-dev git curl ca-certificates \
    libgl1 libglib2.0-0 libsm6 libxrender1 libxext6 \
    && rm -rf /var/lib/apt/lists/*

RUN ln -sf /usr/bin/python3 /usr/bin/python

RUN pip install --no-cache-dir --upgrade pip

RUN pip install --no-cache-dir \
    torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

RUN git clone https://github.com/comfyanonymous/ComfyUI.git /workspace/ComfyUI

WORKDIR /workspace/ComfyUI
RUN pip install --no-cache-dir -r requirements.txt

COPY requirements.txt /workspace/requirements.txt
RUN pip install --no-cache-dir -r /workspace/requirements.txt

RUN mkdir -p /workspace/ComfyUI/models/checkpoints \
    /workspace/ComfyUI/models/loras \
    /workspace/ComfyUI/input \
    /workspace/ComfyUI/output

COPY workflow_api.json /workspace/workflow_api.json
COPY handler.py /workspace/handler.py
COPY start.sh /workspace/start.sh
RUN chmod +x /workspace/start.sh

WORKDIR /workspace

CMD ["/workspace/start.sh"]
