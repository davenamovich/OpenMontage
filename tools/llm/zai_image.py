"""Z-AI Image generation tool — wraps `z-ai image` CLI.

Generates images from text prompts using the local z-ai SDK CLI.
Supports aspect-ratio sizes that the CLI supports (1024x1024, 768x1344,
864x1152, 1344x768, 1152x864, 1440x720, 720x1440).
"""

from __future__ import annotations

import shutil
import subprocess
import time
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


# Map our aspect ratios to z-ai image sizes
ASPECT_TO_SIZE = {
    "16:9": "1344x768",
    "9:16": "768x1344",
    "1:1": "1024x1024",
    "4:5": "864x1152",
    "5:4": "1152x864",
    "21:9": "1440x720",
    "9:21": "720x1440",
}


class ZaiImage(BaseTool):
    name = "zai_image"
    version = "0.1.0"
    tier = ToolTier.GENERATE
    capability = "image_generation"
    provider = "zai"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.API

    dependencies = ["cmd:z-ai"]
    install_instructions = (
        "z-ai CLI must be on PATH. See skills/LLM/SKILL.md for install."
    )
    agent_skills = ["image-generation"]

    capabilities = ["generate_image", "text_to_image"]
    supports = {
        "aspect_ratios": list(ASPECT_TO_SIZE.keys()),
        "negative_prompts": False,  # z-ai image doesn't take negative prompts natively
        "seed_control": False,
        "offline": False,
    }
    best_for = [
        "character reference images",
        "cinematic scene stills",
        "thumbnail concepts",
        "faceless YouTube romance visuals",
    ]
    not_good_for = [
        "pixel-perfect reproducibility",
        "offline generation",
    ]
    fallback_tools = ["pixabay_image", "pexels_image"]

    input_schema = {
        "type": "object",
        "required": ["prompt", "output_path"],
        "properties": {
            "prompt": {"type": "string", "description": "Image description / prompt"},
            "negative_prompt": {
                "type": "string",
                "description": "Not natively supported by z-ai — appended to prompt as 'avoid:' clause",
            },
            "output_path": {"type": "string", "description": "Output PNG path"},
            "aspect_ratio": {
                "type": "string",
                "enum": list(ASPECT_TO_SIZE.keys()),
                "default": "16:9",
            },
            "size": {
                "type": "string",
                "description": "Override exact size (e.g. 1024x1024)",
            },
        },
    }

    resource_profile = ResourceProfile(cpu_cores=1, ram_mb=256, vram_mb=0, disk_mb=10, network_required=True)
    retry_policy = RetryPolicy(max_retries=2, retryable_errors=["timeout", "rate_limit"])
    idempotency_key_fields = ["prompt", "aspect_ratio"]
    side_effects = ["writes PNG to output_path"]
    user_visible_verification = ["Open the PNG and check the image matches the prompt"]

    def get_status(self) -> ToolStatus:
        if shutil.which("z-ai"):
            return ToolStatus.AVAILABLE
        return ToolStatus.UNAVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        # z-ai is free in this environment; the cost_tracker logs 0.0
        return 0.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        # Validate required inputs BEFORE checking availability, so callers get
        # a deterministic error message regardless of whether z-ai is installed.
        prompt = inputs.get("prompt", "")
        if not prompt:
            return ToolResult(success=False, error="Missing required input: prompt")
        output_path_str = inputs.get("output_path")
        if not output_path_str:
            return ToolResult(success=False, error="Missing required input: output_path")
        if self.get_status() != ToolStatus.AVAILABLE:
            return ToolResult(success=False, error="z-ai CLI not available. " + self.install_instructions)

        output_path = Path(output_path_str)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Compose size
        if inputs.get("size"):
            size = inputs["size"]
        else:
            aspect = inputs.get("aspect_ratio", "16:9")
            size = ASPECT_TO_SIZE.get(aspect, "1344x768")

        # z-ai doesn't support negative prompts natively — append as a clause
        full_prompt = prompt
        if inputs.get("negative_prompt"):
            full_prompt = f"{prompt}\n\nAvoid: {inputs['negative_prompt']}"

        cmd = [
            "z-ai", "image",
            "--prompt", full_prompt,
            "--output", str(output_path),
            "--size", size,
        ]

        start = time.time()
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        except subprocess.TimeoutExpired:
            # Kill the z-ai process tree to prevent zombies
            try:
                import signal
                import os
                # Send SIGKILL to the process group
                os.killpg(os.getpgid(proc.pid if hasattr(proc, 'pid') else 0), signal.SIGKILL)
            except Exception:
                pass
            return ToolResult(success=False, error="z-ai image timed out after 90s")

        if proc.returncode != 0:
            # Check if the file was still created despite the error
            if output_path.exists() and output_path.stat().st_size > 0:
                pass  # File exists, treat as success
            else:
                return ToolResult(
                    success=False,
                    error=f"z-ai image failed (exit {proc.returncode}): {proc.stderr[:500]}"
                )
        if not output_path.exists() or output_path.stat().st_size == 0:
            return ToolResult(success=False, error=f"Output PNG missing or empty: {output_path}")

        return ToolResult(
            success=True,
            data={
                "provider": self.provider,
                "prompt": prompt,
                "size": size,
                "output": str(output_path),
                "format": "png",
            },
            artifacts=[str(output_path)],
            duration_seconds=round(time.time() - start, 2),
        )
