#!/bin/bash
set -e

echo "[start.sh] Starting ComfyUI on 127.0.0.1:8188..."
python /workspace/ComfyUI/main.py \
  --listen 127.0.0.1 \
  --port 8188 \
  --dont-print-server &

COMFY_PID=$!

echo "[start.sh] Waiting for ComfyUI to be ready..."
MAX_WAIT=120
ELAPSED=0
while [ $ELAPSED -lt $MAX_WAIT ]; do
  if curl -s http://127.0.0.1:8188/system_stats > /dev/null 2>&1; then
    echo "[start.sh] ComfyUI is ready! (${ELAPSED}s)"
    break
  fi
  sleep 2
  ELAPSED=$((ELAPSED + 2))
done

if [ $ELAPSED -ge $MAX_WAIT ]; then
  echo "[start.sh] ERROR: ComfyUI did not start within ${MAX_WAIT}s"
  kill $COMFY_PID 2>/dev/null
  exit 1
fi

echo "[start.sh] Starting RunPod handler..."
python /workspace/handler.py
