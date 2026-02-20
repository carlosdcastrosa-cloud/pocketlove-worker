"""
RunPod Serverless Handler for ComfyUI.
Receives a job, submits a workflow to ComfyUI local API,
polls for completion, and returns the generated image as base64.
"""
import runpod
import requests
import json
import time
import base64
import os
import sys
import uuid

COMFY_URL = "http://127.0.0.1:8188"
CKPT_NAME = os.environ.get("CKPT_NAME", "sd_xl_base_1.0.safetensors")
WORKFLOW_JSON = os.environ.get("WORKFLOW_JSON", "")

_env_workflow = None
if WORKFLOW_JSON:
    try:
        if os.path.isfile(WORKFLOW_JSON):
            with open(WORKFLOW_JSON, "r") as f:
                _env_workflow = json.load(f)
            print(f"[handler] Loaded workflow from file: {WORKFLOW_JSON}")
        else:
            _env_workflow = json.loads(WORKFLOW_JSON)
            print(f"[handler] Loaded workflow from ENV string")
    except Exception as e:
        print(f"[handler] WARNING: Failed to parse WORKFLOW_JSON: {e}")

DEFAULT_WORKFLOW = {
    "3": {
        "class_type": "KSampler",
        "inputs": {
            "seed": 42,
            "steps": 30,
            "cfg": 5.0,
            "sampler_name": "dpmpp_2m",
            "scheduler": "karras",
            "denoise": 1.0,
            "model": ["4", 0],
            "positive": ["6", 0],
            "negative": ["7", 0],
            "latent_image": ["5", 0]
        }
    },
    "4": {
        "class_type": "CheckpointLoaderSimple",
        "inputs": {
            "ckpt_name": CKPT_NAME
        }
    },
    "5": {
        "class_type": "EmptyLatentImage",
        "inputs": {
            "width": 768,
            "height": 1024,
            "batch_size": 1
        }
    },
    "6": {
        "class_type": "CLIPTextEncode",
        "inputs": {
            "text": "a beautiful woman",
            "clip": ["4", 1]
        }
    },
    "7": {
        "class_type": "CLIPTextEncode",
        "inputs": {
            "text": "bad quality, blurry, deformed",
            "clip": ["4", 1]
        }
    },
    "8": {
        "class_type": "VAEDecode",
        "inputs": {
            "samples": ["3", 0],
            "vae": ["4", 2]
        }
    },
    "9": {
        "class_type": "SaveImage",
        "inputs": {
            "filename_prefix": "output",
            "images": ["8", 0]
        }
    }
}


def build_workflow(inp: dict) -> dict:
    """Build a ComfyUI workflow from job input, ENV workflow, or built-in default."""
    custom_workflow = inp.get("workflow")
    if custom_workflow:
        if isinstance(custom_workflow, str):
            return json.loads(custom_workflow)
        return json.loads(json.dumps(custom_workflow))

    if _env_workflow:
        return json.loads(json.dumps(_env_workflow))

    wf = json.loads(json.dumps(DEFAULT_WORKFLOW))

    prompt_text = inp.get("prompt", "a beautiful woman")
    negative_prompt = inp.get("negative_prompt", "bad quality, blurry, deformed")
    width = inp.get("width", 768)
    height = inp.get("height", 1024)
    steps = inp.get("num_inference_steps", 30)
    cfg = inp.get("guidance_scale", 5.0)
    seed = inp.get("seed", -1)
    if seed is None or seed <= 0:
        seed = int.from_bytes(os.urandom(4), "big")
    ckpt = inp.get("ckpt_name", CKPT_NAME)

    wf["4"]["inputs"]["ckpt_name"] = ckpt
    wf["6"]["inputs"]["text"] = prompt_text
    wf["7"]["inputs"]["text"] = negative_prompt
    wf["5"]["inputs"]["width"] = width
    wf["5"]["inputs"]["height"] = height
    wf["3"]["inputs"]["steps"] = steps
    wf["3"]["inputs"]["cfg"] = cfg
    wf["3"]["inputs"]["seed"] = seed
    wf["9"]["inputs"]["filename_prefix"] = f"job_{uuid.uuid4().hex[:8]}"

    return wf


def wait_for_comfyui(timeout_sec: int = 180):
    """Wait until ComfyUI /system_stats responds."""
    start = time.time()
    while time.time() - start < timeout_sec:
        try:
            resp = requests.get(f"{COMFY_URL}/system_stats", timeout=5)
            if resp.ok:
                print(f"[handler] ComfyUI ready ({int(time.time() - start)}s)")
                return True
        except requests.RequestException:
            pass
        time.sleep(1)
    return False


def queue_prompt(workflow: dict) -> str:
    """Submit workflow to ComfyUI and return prompt_id."""
    client_id = str(uuid.uuid4())
    payload = {
        "prompt": workflow,
        "client_id": client_id
    }
    resp = requests.post(f"{COMFY_URL}/prompt", json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    prompt_id = data.get("prompt_id")
    if not prompt_id:
        raise RuntimeError(f"No prompt_id in response: {json.dumps(data)[:300]}")
    return prompt_id


def poll_completion(prompt_id: str, timeout_sec: int = 600) -> dict:
    """Poll /history/{prompt_id} until the job completes or times out."""
    start = time.time()
    poll_interval = 2.0
    while time.time() - start < timeout_sec:
        try:
            resp = requests.get(f"{COMFY_URL}/history/{prompt_id}", timeout=10)
            if resp.ok:
                history = resp.json()
                if prompt_id in history:
                    return history[prompt_id]
        except requests.RequestException:
            pass
        time.sleep(poll_interval)
    raise TimeoutError(f"ComfyUI job {prompt_id} timed out after {timeout_sec}s")


def fetch_image(filename: str, subfolder: str = "", img_type: str = "output") -> bytes:
    """Download a generated image from ComfyUI /view endpoint."""
    params = {
        "filename": filename,
        "subfolder": subfolder,
        "type": img_type,
    }
    resp = requests.get(f"{COMFY_URL}/view", params=params, timeout=30)
    resp.raise_for_status()
    return resp.content


def handler(job: dict) -> dict:
    """
    RunPod handler. Receives job input, runs ComfyUI workflow, returns base64 image.

    Input fields:
      - prompt (str): Positive prompt text
      - negative_prompt (str): Negative prompt text
      - width (int): Image width (default 768)
      - height (int): Image height (default 1024)
      - num_inference_steps (int): Sampling steps (default 30)
      - guidance_scale (float): CFG scale (default 5.0)
      - seed (int): Seed (-1 for random)
      - ckpt_name (str): Checkpoint filename (default from ENV)
      - workflow (dict|str): Full custom ComfyUI workflow (overrides all above)

    Returns:
      - image_base64 (str): Base64-encoded PNG
      - prompt_id (str): ComfyUI prompt ID
      - meta (dict): seed, width, height
    """
    try:
        inp = job.get("input", {})
        print(f"[handler] Job received. prompt={str(inp.get('prompt',''))[:100]}...")

        workflow = build_workflow(inp)
        seed_used = workflow.get("3", {}).get("inputs", {}).get("seed", -1)
        w = workflow.get("5", {}).get("inputs", {}).get("width", 768)
        h = workflow.get("5", {}).get("inputs", {}).get("height", 1024)

        print(f"[handler] Queuing prompt: {w}x{h}, seed={seed_used}")
        prompt_id = queue_prompt(workflow)
        print(f"[handler] prompt_id={prompt_id}, polling...")

        result = poll_completion(prompt_id, timeout_sec=600)

        outputs = result.get("outputs", {})
        image_data = None
        filename_out = ""
        for node_id, node_output in outputs.items():
            if "images" in node_output:
                for img_info in node_output["images"]:
                    filename_out = img_info.get("filename", "")
                    subfolder = img_info.get("subfolder", "")
                    img_type = img_info.get("type", "output")
                    print(f"[handler] Fetching image: {filename_out}")
                    image_data = fetch_image(filename_out, subfolder, img_type)
                    break
            if image_data:
                break

        if not image_data:
            return {"error": "No image generated by ComfyUI workflow"}

        image_b64 = base64.b64encode(image_data).decode("utf-8")
        print(f"[handler] Done. Image size: {len(image_b64)} chars base64")

        return {
            "image_base64": image_b64,
            "prompt_id": prompt_id,
            "meta": {
                "seed": seed_used,
                "width": w,
                "height": h,
                "filename": filename_out,
            },
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"error": str(e)}


if __name__ == "__main__":
    if "--wait-only" in sys.argv:
        print("[handler] --wait-only mode: waiting for ComfyUI...")
        ok = wait_for_comfyui(timeout_sec=180)
        sys.exit(0 if ok else 1)
    else:
        runpod.serverless.start({
            "handler": handler,
            "concurrency_modifier": lambda x: 1,
        })
