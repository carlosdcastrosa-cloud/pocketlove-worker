# pocketlove-worker

RunPod Serverless GPU worker — ComfyUI headless for Pocketlove.ai image generation.

## Architecture
- **Dockerfile**: Ubuntu + CUDA 12.1, clones ComfyUI, installs deps
- **start.sh**: Starts ComfyUI headless on 127.0.0.1:8188, waits for ready, launches handler
- **handler.py**: RunPod serverless handler — submits workflows to ComfyUI API, polls for completion, returns base64 image

## Environment Variables
- `CKPT_NAME`: Checkpoint filename (default: `sd_xl_base_1.0.safetensors`)
- `WORKFLOW_JSON`: Path to a custom workflow JSON file, or inline JSON string

## RunPod Setup
1. Create a new Serverless Template:
   - Build context: `.`
   - Dockerfile path: `Dockerfile`
   - Container Disk: 20 GB
2. Create an Endpoint:
   - GPU: RTX A5000/A6000 (24GB VRAM min)
   - Volume: Mount checkpoints to `/workspace/ComfyUI/models/checkpoints`
3. Test:
```bash
curl -X POST "https://api.runpod.ai/v2/YOUR_ENDPOINT_ID/runsync" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d @test_input.json
```

## Concurrency
Enforced at 1 per GPU via `concurrency_modifier`.
