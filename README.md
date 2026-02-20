# pocketlove-worker

RunPod Serverless GPU worker — ComfyUI headless (sin UI) para generación de imágenes de Pocketlove.ai.

## Arquitectura

Cada worker GPU ejecuta ComfyUI localmente en `127.0.0.1:8188` y expone un handler compatible con `runpod.serverless`. El handler recibe jobs JSON, ejecuta un workflow por API de ComfyUI, y devuelve la imagen en base64.

## Archivos

| Archivo | Descripción |
|---|---|
| `Dockerfile` | Ubuntu + CUDA 12.1, clona ComfyUI, instala dependencias |
| `start.sh` | Arranca ComfyUI headless, espera ready, lanza handler RunPod |
| `handler.py` | Handler serverless: queue prompt → poll history → fetch image → base64 |
| `requirements.txt` | `runpod==1.7.13`, `requests==2.31.0` |
| `.dockerignore` | Exclusiones del Docker build |

## Deploy en RunPod

### 1. Crear Template (Serverless → New Template)

| Campo | Valor |
|---|---|
| **Build Context** | `.` |
| **Dockerfile Path** | `Dockerfile` |
| **Container Disk** | 20 GB mínimo |

### 2. Crear Endpoint

| Campo | Valor |
|---|---|
| **GPU** | RTX 4090 24GB (recomendado) |
| **Concurrency per worker** | 1 |
| **Max workers** | 10 (ajustar según necesidad) |
| **Timeout** | 180s – 300s |

### 3. Modelos / Checkpoints

Coloca tu checkpoint SDXL en:
```
/workspace/ComfyUI/models/checkpoints/
```

Opciones:
- **Network Volume**: Monta un volumen con los modelos pre-descargados
- **ENV `CKPT_NAME`**: Nombre del archivo checkpoint (default: `sd_xl_base_1.0.safetensors`)

Carpetas disponibles:
```
/workspace/ComfyUI/models/checkpoints/   ← checkpoints
/workspace/ComfyUI/models/loras/         ← LoRAs
/workspace/ComfyUI/input/                ← imágenes de entrada
/workspace/ComfyUI/output/               ← imágenes generadas
```

## Variables de Entorno

| Variable | Descripción | Default |
|---|---|---|
| `CKPT_NAME` | Nombre del archivo checkpoint | `sd_xl_base_1.0.safetensors` |
| `WORKFLOW_JSON` | Ruta a archivo JSON de workflow custom, o string JSON inline | (vacío) |

## API — Formato del Job

### Request (POST al endpoint RunPod)

```bash
curl -X POST "https://api.runpod.ai/v2/TU_ENDPOINT_ID/runsync" \
  -H "Authorization: Bearer TU_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "input": {
      "prompt": "candid photo of a beautiful woman, natural lighting, photorealistic",
      "negative_prompt": "anime, cartoon, blurry, deformed, low quality",
      "width": 768,
      "height": 1024,
      "num_inference_steps": 30,
      "guidance_scale": 5.0,
      "seed": 42
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
      "width": 768,
      "height": 1024,
      "filename": "job_a1b2c3d4_00001_.png"
    }
  }
}
```

### Decodificar la imagen (Python)

```python
import base64

b64 = response["output"]["image_base64"]
with open("output.png", "wb") as f:
    f.write(base64.b64decode(b64))
```

### Decodificar la imagen (bash)

```bash
echo "$IMAGE_BASE64" | base64 -d > output.png
```

## Input fields

| Campo | Tipo | Default | Descripción |
|---|---|---|---|
| `prompt` | str | `"a beautiful woman"` | Prompt positivo |
| `negative_prompt` | str | `"bad quality, blurry, deformed"` | Prompt negativo |
| `width` | int | 768 | Ancho de la imagen |
| `height` | int | 1024 | Alto de la imagen |
| `num_inference_steps` | int | 30 | Pasos de sampling |
| `guidance_scale` | float | 5.0 | CFG scale |
| `seed` | int | -1 (random) | Seed para reproducibilidad |
| `ckpt_name` | str | ENV `CKPT_NAME` | Nombre del checkpoint |
| `workflow` | dict\|str | (ninguno) | Workflow custom de ComfyUI (override total) |

## Modo CLI: --wait-only

Para verificar que ComfyUI arrancó correctamente:

```bash
python handler.py --wait-only
```

Espera hasta 180s a que `/system_stats` responda. Sale con código 0 si está listo, 1 si timeout.

## Concurrency

Forzada a 1 job por GPU via `concurrency_modifier`. Cada worker procesa un job a la vez.

## NO incluido

- No se descargan modelos durante el build (usar Network Volume o manual upload)
- No hay API keys en el repo
