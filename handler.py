"""
RunPod Serverless Handler for ComfyUI.
Receives a job, builds a workflow from workflow_api.json,
submits it to ComfyUI local API, polls for completion,
and returns the generated image as base64.

Workflow pipeline:
  CheckpointLoaderSimple (bigLust_v16) →
  LoraLoader (dmd2_sdxl_4step) →
  LoraLoader (character lora) →
  EmptyLatentImage →
  CLIPTextEncode (positive) →
  CLIPTextEncode (negative) →
  KSamplerAdvanced (lcm, 10 steps, cfg 1) →
  VAEDecode →
  SaveImage
"""
import runpod
import requests
import json
import time
import base64
import os
import sys
import uuid
import copy

COMFY_URL = "http://127.0.0.1:8188"
CKPT_NAME = os.environ.get("CKPT_NAME", "bigLust_v16.safetensors")
DMD2_LORA = os.environ.get("DMD2_LORA", "dmd2_sdxl_4step_lora.safetensors")
DMD2_STRENGTH = float(os.environ.get("DMD2_STRENGTH", "0.7"))
DEFAULT_STEPS = int(os.environ.get("DEFAULT_STEPS", "10"))
DEFAULT_CFG = float(os.environ.get("DEFAULT_CFG", "1"))
DEFAULT_SAMPLER = os.environ.get("DEFAULT_SAMPLER", "lcm")
DEFAULT_SCHEDULER = os.environ.get("DEFAULT_SCHEDULER", "karras")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WORKFLOW_PATH = os.path.join(SCRIPT_DIR, "workflow_api.json")

_base_workflow = None

def load_base_workflow():
    """Load the base workflow JSON (once)."""
    global _base_workflow
    if _base_workflow is not None:
        return _base_workflow

    custom_path = os.environ.get("WORKFLOW_JSON", "")
    if custom_path and os.path.isfile(custom_path):
        with open(custom_path, "r") as f:
            _base_workflow = json.load(f)
        print(f"[handler] Loaded workflow from ENV: {custom_path}")
        return _base_workflow

    if os.path.isfile(WORKFLOW_PATH):
        with open(WORKFLOW_PATH, "r") as f:
            _base_workflow = json.load(f)
        print(f"[handler] Loaded workflow from: {WORKFLOW_PATH}")
        return _base_workflow

    raise FileNotFoundError(f"No workflow found at {WORKFLOW_PATH} or WORKFLOW_JSON env")


def build_workflow(inp: dict) -> dict:
    """
    Build a ComfyUI API workflow from job input.

    Accepts a full custom workflow override, or modifies the base workflow with:
      - prompt / negative_prompt
      - lora_name / lora_strength (character LoRA)
      - width / height
      - steps / cfg / sampler_name / scheduler
      - seed
      - ckpt_name
      - dmd2_lora / dmd2_strength
    """
    custom_workflow = inp.get("workflow")
    if custom_workflow:
        if isinstance(custom_workflow, str):
            return json.loads(custom_workflow)
        return copy.deepcopy(custom_workflow)

    base = load_base_workflow()
    wf = copy.deepcopy(base)

    ckpt = inp.get("ckpt_name", CKPT_NAME)
    wf["1"]["inputs"]["ckpt_name"] = ckpt

    dmd2_lora = inp.get("dmd2_lora", DMD2_LORA)
    dmd2_str = inp.get("dmd2_strength", DMD2_STRENGTH)
    wf["2"]["inputs"]["lora_name"] = dmd2_lora
    wf["2"]["inputs"]["strength_model"] = dmd2_str
    wf["2"]["inputs"]["strength_clip"] = dmd2_str

    lora_name = inp.get("lora_name", "")
    lora_strength = inp.get("lora_strength", 1.0)
    if lora_name:
        wf["3"]["inputs"]["lora_name"] = lora_name
        wf["3"]["inputs"]["strength_model"] = lora_strength
        wf["3"]["inputs"]["strength_clip"] = lora_strength
    else:
        wf["3"]["inputs"]["lora_name"] = dmd2_lora
        wf["3"]["inputs"]["strength_model"] = 0.0
        wf["3"]["inputs"]["strength_clip"] = 0.0

    width = inp.get("width", 1024)
    height = inp.get("height", 1024)
    wf["4"]["inputs"]["width"] = width
    wf["4"]["inputs"]["height"] = height

    prompt_text = inp.get("prompt", "1girl, looking at viewer, photorealistic, detailed face")
    negative_prompt = inp.get("negative_prompt", "reflections errors, blur, oversharpening, poor composition, deformed, ugly, bad anatomy")
    wf["5"]["inputs"]["text"] = prompt_text
    wf["6"]["inputs"]["text"] = negative_prompt

    seed = inp.get("seed", -1)
    if seed is None or seed <= 0:
        seed = int.from_bytes(os.urandom(4), "big")

    steps = inp.get("num_inference_steps", inp.get("steps", DEFAULT_STEPS))
    cfg = inp.get("guidance_scale", inp.get("cfg", DEFAULT_CFG))
    sampler = inp.get("sampler_name", DEFAULT_SAMPLER)
    scheduler = inp.get("scheduler", DEFAULT_SCHEDULER)

    wf["7"]["inputs"]["noise_seed"] = seed
    wf["7"]["inputs"]["steps"] = steps
    wf["7"]["inputs"]["cfg"] = cfg
    wf["7"]["inputs"]["sampler_name"] = sampler
    wf["7"]["inputs"]["scheduler"] = scheduler

    job_prefix = f"job_{uuid.uuid4().hex[:8]}"
    wf["9"]["inputs"]["filename_prefix"] = job_prefix

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
    RunPod handler entry point.

    Input fields:
      - prompt (str): Positive prompt
      - negative_prompt (str): Negative prompt
      - lora_name (str): Character LoRA filename (e.g. "valentina-000003.safetensors")
      - lora_strength (float): Character LoRA strength (default 1.0)
      - width (int): Image width (default 1024)
      - height (int): Image height (default 1024)
      - num_inference_steps (int): Sampling steps (default 10)
      - guidance_scale (float): CFG scale (default 1)
      - seed (int): Seed (-1 for random)
      - sampler_name (str): Sampler (default "lcm")
      - scheduler (str): Scheduler (default "karras")
      - ckpt_name (str): Checkpoint filename
      - dmd2_lora (str): DMD2 LoRA filename
      - dmd2_strength (float): DMD2 LoRA strength (default 0.7)
      - workflow (dict|str): Full custom ComfyUI workflow (overrides all above)

    Returns:
      - image_base64 (str): Base64-encoded PNG
      - prompt_id (str): ComfyUI prompt ID
      - meta (dict): seed, width, height, lora_name, steps, cfg
    """
    try:
        inp = job.get("input", {})
        lora = inp.get("lora_name", "none")
        print(f"[handler] Job received. lora={lora}, prompt={str(inp.get('prompt',''))[:80]}...")

        workflow = build_workflow(inp)

        seed_used = workflow.get("7", {}).get("inputs", {}).get("noise_seed", -1)
        w = workflow.get("4", {}).get("inputs", {}).get("width", 1024)
        h = workflow.get("4", {}).get("inputs", {}).get("height", 1024)
        steps = workflow.get("7", {}).get("inputs", {}).get("steps", 10)
        cfg = workflow.get("7", {}).get("inputs", {}).get("cfg", 1)

        print(f"[handler] Queuing: {w}x{h}, seed={seed_used}, steps={steps}, cfg={cfg}, lora={lora}")
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
                "lora_name": lora,
                "steps": steps,
                "cfg": cfg,
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
