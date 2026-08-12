"""ComfyUI local image generation tool.

Calls a local ComfyUI instance (default http://localhost:8188) to generate
images via Stable Diffusion. Supports a default txt2img workflow that can
be customized via environment variables.

Configuration:
    COMFYUI_URL — base URL of the ComfyUI instance (default http://localhost:8188)
    COMFYUI_MODEL — checkpoint name to use (default: anything-v5-fp16.safetensors,
                    or whatever is available)
    COMFYUI_TIMEOUT — per-job timeout in seconds (default: 120)

The tool discovers available checkpoints on startup and picks the first one
if COMFYUI_MODEL is not set. If ComfyUI is not running, the tool reports
unavailable and the romance pipeline falls back to zai_image.
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
import urllib.error
import uuid
from pathlib import Path
from typing import Any

from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    RetryPolicy,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolStatus,
    ToolTier,
)


DEFAULT_URL = os.environ.get("COMFYUI_URL", "http://localhost:8188")
DEFAULT_TIMEOUT = int(os.environ.get("COMFYUI_TIMEOUT", "120"))


def _comfy_get(path: str, timeout: int = 10) -> dict | None:
    """GET from ComfyUI, return parsed JSON or None on failure."""
    try:
        url = f"{DEFAULT_URL}{path}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def _comfy_post(path: str, data: dict, timeout: int = 10) -> dict | None:
    """POST to ComfyUI, return parsed JSON or None on failure."""
    try:
        url = f"{DEFAULT_URL}{path}"
        body = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def _discover_model() -> str | None:
    """Discover an available checkpoint on the ComfyUI instance."""
    info = _comfy_get("/object_info")
    if not info:
        return None
    checkpoints = info.get("CheckpointLoaderSimple", {}).get("input", {}).get("required", {})
    if isinstance(checkpoints, dict):
        models = checkpoints.get("ckpt_name", [])
    else:
        models = checkpoints if isinstance(checkpoints, list) else []
    if models:
        return models[0]
    return None


# Aspect ratio → ComfyUI dimensions (keep under 1024 for speed)
ASPECT_TO_DIMS = {
    "16:9": (1024, 576),
    "9:16": (576, 1024),
    "1:1": (768, 768),
    "4:5": (614, 768),
    "5:4": (768, 614),
    "21:9": (1024, 440),
    "9:21": (440, 1024),
}


def _build_workflow(prompt: str, negative_prompt: str, width: int, height: int, seed: int, model_name: str) -> dict:
    """Build a ComfyUI txt2img workflow (API format).

    This is a standard SD1.5/SDXL txt2img workflow:
    - Load checkpoint → CLIPTextEncode (pos+neg) → EmptyLatentImage → KSampler → VAE Decode → Save
    """
    return {
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed,
                "steps": 25,
                "cfg": 7.0,
                "sampler_name": "dpmpp_2m",
                "scheduler": "karras",
                "denoise": 1.0,
                "model": ["4", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["5", 0],
            },
        },
        "4": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": model_name},
        },
        "5": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": width, "height": height, "batch_size": 1},
        },
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": prompt, "clip": ["4", 1]},
        },
        "7": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": negative_prompt or "bad quality, low resolution, blurry", "clip": ["4", 1]},
        },
        "8": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["3", 0], "vae": ["4", 2]},
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {"images": ["8", 0], "filename_prefix": "romance"},
        },
    }


class ComfyImage(BaseTool):
    name = "comfy_image"
    version = "0.1.0"
    tier = ToolTier.GENERATE
    capability = "image_generation"
    provider = "comfyui"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.LOCAL

    dependencies = ["service:comfyui"]
    install_instructions = (
        "ComfyUI must be running locally. Install:\n"
        "  git clone https://github.com/comfyanonymous/ComfyUI\n"
        "  cd ComfyUI && pip install -r requirements.txt\n"
        "  python main.py --listen  # starts on http://localhost:8188\n"
        "Or use the portable build from https://github.com/comfyanonymous/ComfyUI/releases\n"
        "Set COMFYUI_URL env var if not on default port."
    )
    agent_skills = ["image-generation", "stable-diffusion"]

    capabilities = ["generate_image", "text_to_image"]
    supports = {
        "aspect_ratios": list(ASPECT_TO_DIMS.keys()),
        "negative_prompts": True,
        "seed_control": True,
        "offline": True,
    }
    best_for = [
        "local image generation (no API costs)",
        "character reference images with negative prompts",
        "scene images with full control over model + sampler",
        "privacy-sensitive workflows",
    ]
    not_good_for = [
        "use without a local ComfyUI instance running",
        "use without a downloaded checkpoint model",
    ]
    fallback_tools = ["zai_image", "pixabay_image", "pexels_image"]

    input_schema = {
        "type": "object",
        "required": ["prompt", "output_path"],
        "properties": {
            "prompt": {"type": "string", "description": "Image description / prompt"},
            "negative_prompt": {"type": "string", "description": "What to avoid"},
            "output_path": {"type": "string", "description": "Output PNG path"},
            "aspect_ratio": {
                "type": "string",
                "enum": list(ASPECT_TO_DIMS.keys()),
                "default": "16:9",
            },
            "width": {"type": "integer", "description": "Override width"},
            "height": {"type": "integer", "description": "Override height"},
            "seed": {"type": "integer", "description": "Random seed (default: random)"},
            "steps": {"type": "integer", "description": "Sampling steps (default: 25)"},
            "cfg": {"type": "number", "description": "CFG scale (default: 7.0)"},
        },
    }

    resource_profile = ResourceProfile(cpu_cores=2, ram_mb=512, vram_mb=4096, disk_mb=10, network_required=False)
    retry_policy = RetryPolicy(max_retries=1, retryable_errors=["timeout"])
    idempotency_key_fields = ["prompt", "aspect_ratio", "seed"]
    side_effects = ["writes PNG to output_path"]
    user_visible_verification = ["Open the PNG and check it matches the prompt"]

    def get_status(self) -> ToolStatus:
        # Check if ComfyUI is reachable
        info = _comfy_get("/system_stats", timeout=3)
        if info and "system" in info:
            return ToolStatus.AVAILABLE
        return ToolStatus.UNAVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.0  # local, free

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        start = time.time()

        # Validate inputs
        prompt = inputs.get("prompt", "")
        if not prompt:
            return ToolResult(success=False, error="Missing required input: prompt")
        output_path_str = inputs.get("output_path")
        if not output_path_str:
            return ToolResult(success=False, error="Missing required input: output_path")
        output_path = Path(output_path_str)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Check ComfyUI is running
        stats = _comfy_get("/system_stats", timeout=5)
        if not stats:
            return ToolResult(success=False, error=f"ComfyUI not reachable at {DEFAULT_URL}. " + self.install_instructions)

        # Determine dimensions
        aspect = inputs.get("aspect_ratio", "16:9")
        default_w, default_h = ASPECT_TO_DIMS.get(aspect, (1024, 576))
        width = inputs.get("width", default_w)
        height = inputs.get("height", default_h)

        # Determine model
        model_name = os.environ.get("COMFYUI_MODEL", "")
        if not model_name:
            model_name = _discover_model() or ""
            if not model_name:
                return ToolResult(success=False, error="No checkpoints found in ComfyUI. Place a .safetensors model in ComfyUI/models/checkpoints/")

        # Build workflow
        seed = inputs.get("seed") or int(time.time() * 1000) % (2**32)
        workflow = _build_workflow(
            prompt=prompt,
            negative_prompt=inputs.get("negative_prompt", ""),
            width=width,
            height=height,
            seed=seed,
            model_name=model_name,
        )

        # Override steps/cfg if provided
        if inputs.get("steps"):
            workflow["3"]["inputs"]["steps"] = inputs["steps"]
        if inputs.get("cfg"):
            workflow["3"]["inputs"]["cfg"] = inputs["cfg"]

        # Queue the prompt
        client_id = str(uuid.uuid4())
        queue_resp = _comfy_post("/prompt", {"prompt": workflow, "client_id": client_id}, timeout=15)
        if not queue_resp:
            return ToolResult(success=False, error="Failed to queue prompt in ComfyUI")
        if "error" in queue_resp:
            return ToolResult(success=False, error=f"ComfyUI rejected workflow: {queue_resp.get('error','')[:300]}")

        prompt_id = queue_resp.get("prompt_id", "")
        if not prompt_id:
            return ToolResult(success=False, error="ComfyUI did not return a prompt_id")

        # Poll for completion
        timeout = DEFAULT_TIMEOUT
        deadline = time.time() + timeout
        while time.time() < deadline:
            history = _comfy_get(f"/history/{prompt_id}", timeout=5)
            if history and prompt_id in history:
                outputs = history[prompt_id].get("outputs", {})
                if outputs:
                    # Find the SaveImage output
                    for node_id, node_output in outputs.items():
                        images = node_output.get("images", [])
                        if images:
                            img_info = images[0]
                            filename = img_info.get("filename", "")
                            subfolder = img_info.get("subfolder", "")
                            img_type = img_info.get("type", "output")
                            # Download the image
                            download_url = f"{DEFAULT_URL}/view?filename={filename}&subfolder={subfolder}&type={img_type}"
                            try:
                                urllib.request.urlretrieve(download_url, str(output_path))
                                if output_path.exists() and output_path.stat().st_size > 0:
                                    return ToolResult(
                                        success=True,
                                        data={
                                            "provider": self.provider,
                                            "prompt": prompt,
                                            "model": model_name,
                                            "seed": seed,
                                            "width": width,
                                            "height": height,
                                            "output": str(output_path),
                                            "format": "png",
                                        },
                                        artifacts=[str(output_path)],
                                        duration_seconds=round(time.time() - start, 2),
                                    )
                            except Exception as exc:
                                return ToolResult(success=False, error=f"Failed to download image: {exc}")
            time.sleep(2)

        return ToolResult(success=False, error=f"ComfyUI job timed out after {timeout}s")
