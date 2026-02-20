# pocketlove-worker

RunPod Serverless GPU worker — ComfyUI headless para generación de imágenes de Pocketlove.ai.

## Arquitectura

Cada worker GPU ejecuta ComfyUI localmente en `127.0.0.1:8188` y expone un handler compatible con `runpod.serverless`. El handler recibe jobs JSON, ejecuta el workflow por API de ComfyUI, y devuelve la imagen en base64.

## Pipeline del Workflow

```
CheckpointLoaderSimple (bigLust_v16.safetensors)
  → LoraLoader (dmd2_sdxl_4step - velocidad)
    → LoraLoader (character LoRA - personalidad)
      → EmptyLatentImage (1024x1024)
      → CLIPTextEncode (prompt positivo)
      → CLIPTextEncode (prompt negativo)
        → KSamplerAdvanced (lcm, 10 pasos, cfg 1)
          → VAEDecode
            → SaveImage
```

Ultra-rápido: **10 pasos** con sampler LCM + scheduler Karras + CFG 1 (gracias al LoRA DMD2 de destilación).

## Archivos

| Archivo | Descripción |
|---|---|
| `Dockerfile` | Ubuntu + CUDA 12.1, clona ComfyUI, instala dependencias |
| `workflow_api.json` | Workflow en formato API de ComfyUI (9 nodos) |
| `handler.py` | Handler serverless: build workflow → queue → poll → fetch → base64 |
| `start.sh` | Arranca ComfyUI headless, espera ready, lanza handler RunPod |
| `requirements.txt` | `runpod==1.7.13`, `requests==2.31.0` |

## Deploy en RunPod

### 1. Crear Network Volume

Crear un Network Volume y subir estos archivos:

```
/workspace/ComfyUI/models/checkpoints/
  └── bigLust_v16.safetensors          ← Checkpoint principal (SDXL NSFW)

/workspace/ComfyUI/models/loras/
  ├── dmd2_sdxl_4step_lora.safetensors ← DMD2 distillation (velocidad, siempre ON)
  ├── valentina-000003.safetensors      ← LoRA personaje: Valentina
  ├── lexi-000003.safetensors           ← LoRA personaje: Lexi
  └── [otros-personajes].safetensors    ← LoRAs adicionales
```

### 2. Crear Template (Serverless → New Template)

| Campo | Valor |
|---|---|
| **Docker Image** | Build desde este repo o pre-build |
| **Container Disk** | 20 GB mínimo |
| **Volume Mount** | Montar Network Volume en `/workspace/ComfyUI/models` |

### 3. Crear Endpoint

| Campo | Valor |
|---|---|
| **GPU** | RTX 4090 24GB (recomendado) |
| **Concurrency per worker** | 1 |
| **Max workers** | 10 (ajustar según necesidad) |
| **Timeout** | 180s – 300s |
| **Idle Timeout** | 300s (5 min, ajustar según presupuesto) |

## Variables de Entorno

| Variable | Default | Descripción |
|---|---|---|
| `CKPT_NAME` | `bigLust_v16.safetensors` | Nombre del checkpoint |
| `DMD2_LORA` | `dmd2_sdxl_4step_lora.safetensors` | LoRA de velocidad |
| `DMD2_STRENGTH` | `0.7` | Fuerza del DMD2 LoRA |
| `DEFAULT_STEPS` | `10` | Pasos de sampling |
| `DEFAULT_CFG` | `1` | CFG scale |
| `DEFAULT_SAMPLER` | `lcm` | Sampler |
| `DEFAULT_SCHEDULER` | `karras` | Scheduler |

## API — Formato del Job

### Request

```bash
curl -X POST "https://api.runpod.ai/v2/TU_ENDPOINT_ID/run" \
  -H "Authorization: Bearer TU_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "input": {
      "prompt": "valentina, 1girl, looking at viewer, blonde hair, blue eyes, photorealistic, detailed face",
      "negative_prompt": "blur, deformed, ugly, bad anatomy",
      "lora_name": "valentina-000003.safetensors",
      "lora_strength": 1.0,
      "width": 1024,
      "height": 1024,
      "seed": -1
    }
  }'
```

### Response

```json
{
  "id": "job-xxxxx",
  "status": "COMPLETED",
  "output": {
    "image_base64": "iVBORw0KGgo...",
    "prompt_id": "abc123-...",
    "meta": {
      "seed": 42,
      "width": 1024,
      "height": 1024,
      "lora_name": "valentina-000003.safetensors",
      "steps": 10,
      "cfg": 1,
      "filename": "job_a1b2c3d4_00001_.png"
    }
  }
}
```

## Input Fields

| Campo | Tipo | Default | Descripción |
|---|---|---|---|
| `prompt` | str | `"1girl, looking at viewer..."` | Prompt positivo |
| `negative_prompt` | str | `"reflections errors, blur..."` | Prompt negativo |
| `lora_name` | str | (ninguno) | Nombre del LoRA de personaje |
| `lora_strength` | float | 1.0 | Fuerza del LoRA de personaje |
| `width` | int | 1024 | Ancho de la imagen |
| `height` | int | 1024 | Alto de la imagen |
| `num_inference_steps` | int | 10 | Pasos de sampling |
| `guidance_scale` | float | 1 | CFG scale |
| `sampler_name` | str | `lcm` | Sampler |
| `scheduler` | str | `karras` | Scheduler |
| `seed` | int | -1 (random) | Seed para reproducibilidad |
| `ckpt_name` | str | ENV `CKPT_NAME` | Nombre del checkpoint |
| `dmd2_lora` | str | ENV `DMD2_LORA` | LoRA de velocidad |
| `dmd2_strength` | float | 0.7 | Fuerza del DMD2 LoRA |
| `workflow` | dict\|str | (ninguno) | Workflow custom (override total) |

## Cómo funciona el LoRA dinámico

Cada personaje de Pocketlove tiene un LoRA entrenado. Cuando el usuario genera una imagen:

1. La app envía `lora_name: "valentina-000003.safetensors"` al worker
2. El handler inyecta ese LoRA en el nodo 3 del workflow
3. El LoRA DMD2 (nodo 2) siempre está activo para velocidad
4. Si no se envía `lora_name`, el nodo 3 se desactiva (strength 0)

## Agregar nuevo personaje

1. Entrenar un LoRA con Kohya o similar (SDXL format)
2. Subir el `.safetensors` al Network Volume en `/workspace/ComfyUI/models/loras/`
3. Agregar `lora_name` al personaje en la base de datos de Supabase
4. Listo — el worker lo carga automáticamente

## Concurrency

Forzada a 1 job por GPU. Cada worker procesa un job a la vez.

## NO incluido

- No se descargan modelos durante el build (usar Network Volume)
- No hay API keys en el repo
- Los archivos `.safetensors` NO se suben a GitHub (demasiado grandes)
