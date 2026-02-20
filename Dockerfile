FROM nvidia/cuda:12.1.1-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV CKPT_NAME=sd_xl_base_1.0.safetensors
ENV WORKFLOW_JSON=""

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv git wget curl \
    libgl1 libglib2.0-0 libsm6 libxrender1 libxext6 \
    && rm -rf /var/lib/apt/lists/*

RUN ln -sf /usr/bin/python3 /usr/bin/python

RUN git clone https://github.com/comfyanonymous/ComfyUI.git /workspace/ComfyUI

WORKDIR /workspace/ComfyUI
RUN pip install --no-cache-dir -r requirements.txt

COPY requirements.txt /workspace/requirements.txt
RUN pip install --no-cache-dir -r /workspace/requirements.txt

COPY handler.py /workspace/handler.py
COPY start.sh /workspace/start.sh
RUN chmod +x /workspace/start.sh

WORKDIR /workspace

EXPOSE 8188

CMD ["/workspace/start.sh"]
