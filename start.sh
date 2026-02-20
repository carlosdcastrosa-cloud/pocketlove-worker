#!/bin/bash
set -e

echo "[start.sh] Linking Network Volume models to ComfyUI..."

VOLUME_PATH="/runpod-volume"
COMFY_MODELS="/workspace/ComfyUI/models"

if [ -d "$VOLUME_PATH/checkpoints" ]; then
  for f in "$VOLUME_PATH/checkpoints"/*.safetensors; do
    [ -f "$f" ] && ln -sf "$f" "$COMFY_MODELS/checkpoints/" && echo "  Linked checkpoint: $(basename $f)"
  done
fi

if [ -d "$VOLUME_PATH/loras" ]; then
  for f in "$VOLUME_PATH/loras"/*.safetensors; do
    [ -f "$f" ] && ln -sf "$f" "$COMFY_MODELS/loras/" && echo "  Linked lora: $(basename $f)"
  done
fi

echo "[start.sh] Model links:"
ls -la "$COMFY_MODELS/checkpoints/" 2>/dev/null || echo "  No checkpoints dir"
ls -la "$COMFY_MODELS/loras/" 2>/dev/null || echo "  No loras dir"

echo "[start.sh] Starting ComfyUI on 127.0.0.1:8188..."
cd /workspace/ComfyUI
python main.py --listen 127.0.0.1 --port 8188 --disable-auto-launch --dont-print-server &
COMFY_PID=$!

echo "[start.sh] Waiting for ComfyUI to be ready..."
MAX_WAIT=180
ELAPSED=0
while [ $ELAPSED -lt $MAX_WAIT ]; do
  if curl -s http://127.0.0.1:8188/system_stats > /dev/null 2>&1; then
    echo "[start.sh] ComfyUI is ready! (${ELAPSED}s)"
    break
  fi
  sleep 1
  ELAPSED=$((ELAPSED + 1))
done

if [ $ELAPSED -ge $MAX_WAIT ]; then
  echo "[start.sh] ERROR: ComfyUI did not start within ${MAX_WAIT}s"
  kill $COMFY_PID 2>/dev/null
  exit 1
fi

echo "[start.sh] Starting RunPod handler..."
cd /workspace
python -c "import runpod; from handler import handler; runpod.serverless.start({'handler': handler, 'concurrency_modifier': lambda x: 1})"
