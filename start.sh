#!/bin/bash
set -e

echo "[start.sh] === PocketLove Worker Starting ==="

VOLUME_PATH="/runpod-volume"
COMFY_DIR="/workspace/ComfyUI"
COMFY_MODELS="$COMFY_DIR/models"

echo "[start.sh] Checking Network Volume..."
if [ -d "$VOLUME_PATH" ]; then
  echo "[start.sh] Network Volume found at $VOLUME_PATH"
  ls -la "$VOLUME_PATH/" 2>/dev/null
  echo "[start.sh] Volume checkpoints:"
  ls -la "$VOLUME_PATH/checkpoints/" 2>/dev/null || echo "  No checkpoints dir"
  echo "[start.sh] Volume LoRAs:"
  ls -la "$VOLUME_PATH/loras/" 2>/dev/null || echo "  No loras dir"
else
  echo "[start.sh] WARNING: Network Volume not found at $VOLUME_PATH"
  echo "[start.sh] Checking alternative paths..."
  ls -la /workspace/ 2>/dev/null
  ls -la / 2>/dev/null | grep -i vol
fi

echo "[start.sh] Copying models from Network Volume to ComfyUI models dir..."
if [ -d "$VOLUME_PATH/checkpoints" ]; then
  cp -v "$VOLUME_PATH/checkpoints"/*.safetensors "$COMFY_MODELS/checkpoints/" 2>/dev/null && echo "  Checkpoints copied!" || echo "  No checkpoints to copy"
fi

if [ -d "$VOLUME_PATH/loras" ]; then
  cp -v "$VOLUME_PATH/loras"/*.safetensors "$COMFY_MODELS/loras/" 2>/dev/null && echo "  LoRAs copied!" || echo "  No loras to copy"
fi

echo "[start.sh] ComfyUI models directory contents:"
echo "  Checkpoints:"
ls -la "$COMFY_MODELS/checkpoints/" 2>/dev/null || echo "    empty"
echo "  LoRAs:"
ls -la "$COMFY_MODELS/loras/" 2>/dev/null || echo "    empty"

echo "[start.sh] Starting ComfyUI on 127.0.0.1:8188..."
cd "$COMFY_DIR"
python main.py --listen 127.0.0.1 --port 8188 --disable-auto-launch 2>&1 &
COMFY_PID=$!

echo "[start.sh] Waiting for ComfyUI to be ready (PID=$COMFY_PID)..."
MAX_WAIT=300
ELAPSED=0
while [ $ELAPSED -lt $MAX_WAIT ]; do
  if curl -s http://127.0.0.1:8188/system_stats > /dev/null 2>&1; then
    echo "[start.sh] ComfyUI is ready! (${ELAPSED}s)"

    echo "[start.sh] Querying available models..."
    curl -s http://127.0.0.1:8188/object_info/CheckpointLoaderSimple 2>/dev/null | python -c "
import sys, json
try:
    data = json.load(sys.stdin)
    ckpts = data.get('CheckpointLoaderSimple', {}).get('input', {}).get('required', {}).get('ckpt_name', [[]])[0]
    print(f'  Available checkpoints ({len(ckpts)}): {ckpts}')
except Exception as e:
    print(f'  Could not parse: {e}')
" 2>/dev/null || echo "  Could not query checkpoints"

    curl -s http://127.0.0.1:8188/object_info/LoraLoader 2>/dev/null | python -c "
import sys, json
try:
    data = json.load(sys.stdin)
    loras = data.get('LoraLoader', {}).get('input', {}).get('required', {}).get('lora_name', [[]])[0]
    print(f'  Available loras ({len(loras)}): {loras}')
except Exception as e:
    print(f'  Could not parse: {e}')
" 2>/dev/null || echo "  Could not query loras"

    break
  fi
  sleep 2
  ELAPSED=$((ELAPSED + 2))
  if [ $((ELAPSED % 30)) -eq 0 ]; then
    echo "[start.sh] Still waiting... (${ELAPSED}s)"
  fi
done

if [ $ELAPSED -ge $MAX_WAIT ]; then
  echo "[start.sh] ERROR: ComfyUI did not start within ${MAX_WAIT}s"
  kill $COMFY_PID 2>/dev/null
  exit 1
fi

echo "[start.sh] Starting RunPod handler..."
cd /workspace
python -c "import runpod; from handler import handler; runpod.serverless.start({'handler': handler, 'concurrency_modifier': lambda x: 1})"
