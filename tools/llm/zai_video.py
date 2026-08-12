"""Z-AI Video generation tool — wraps `z-ai video` CLI.

Generates short video clips from text prompts or first/last-frame images.
Default 5-second clips, 30 fps. Polling is automatic with --poll.
"""

from __future__ import annotations

import json
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


class ZaiVideo(BaseTool):
    name = "zai_video"
    version = "0.1.0"
    tier = ToolTier.GENERATE
    capability = "video_generation"
    provider = "zai"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.API

    dependencies = ["cmd:z-ai"]
    install_instructions = "z-ai CLI must be on PATH."
    agent_skills = ["video-generation"]

    capabilities = ["generate_video", "text_to_video", "image_to_video"]
    supports = {
        "durations": [5, 10],
        "fps": [30, 60],
        "quality_modes": ["speed", "quality"],
        "first_last_frame": False,
        "offline": False,
    }
    best_for = [
        "short hero moments in hybrid mode",
        "cinematic AI video clips",
    ]
    not_good_for = ["long-form continuous video", "offline generation"]
    fallback_tools = ["pexels_video", "pixabay_video"]

    input_schema = {
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "Video description"},
            "image_url": {"type": "string", "description": "Optional first-frame image URL"},
            "image_path": {"type": "string", "description": "Optional first-frame local image path (converted to URL by caller)"},
            "output_path": {"type": "string", "description": "Where to save the result JSON (will contain video URL)"},
            "video_output_path": {"type": "string", "description": "Where to save the downloaded MP4"},
            "quality": {"type": "string", "enum": ["speed", "quality"], "default": "speed"},
            "size": {"type": "string", "default": "1920x1080"},
            "fps": {"type": "integer", "enum": [30, 60], "default": 30},
            "duration": {"type": "integer", "enum": [5, 10], "default": 5},
            "with_audio": {"type": "boolean", "default": False},
            "poll": {"type": "boolean", "default": True},
            "poll_interval": {"type": "integer", "default": 5},
            "max_polls": {"type": "integer", "default": 60},
        },
    }

    resource_profile = ResourceProfile(cpu_cores=1, ram_mb=256, vram_mb=0, disk_mb=50, network_required=True)
    retry_policy = RetryPolicy(max_retries=1, retryable_errors=["timeout"])
    idempotency_key_fields = ["prompt", "size", "duration"]
    side_effects = ["writes JSON result + downloaded MP4"]
    user_visible_verification = ["Play the MP4"]

    def get_status(self) -> ToolStatus:
        if shutil.which("z-ai"):
            return ToolStatus.AVAILABLE
        return ToolStatus.UNAVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        # z-ai video is metered but for now treat as free in this env
        return 0.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        if self.get_status() != ToolStatus.AVAILABLE:
            return ToolResult(success=False, error="z-ai CLI not available. " + self.install_instructions)

        output_path = Path(inputs.get("output_path", "video_result.json"))
        output_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            "z-ai", "video",
            "--prompt", inputs.get("prompt", ""),
            "--quality", inputs.get("quality", "speed"),
            "--size", inputs.get("size", "1920x1080"),
            "--fps", str(inputs.get("fps", 30)),
            "--duration", str(inputs.get("duration", 5)),
        ]
        if inputs.get("image_url"):
            cmd += ["--image-url", inputs["image_url"]]
        if inputs.get("with_audio"):
            cmd.append("--with-audio")
        if inputs.get("poll", True):
            cmd.append("--poll")
            cmd += ["--poll-interval", str(inputs.get("poll_interval", 5))]
            cmd += ["--max-polls", str(inputs.get("max_polls", 60))]
        cmd += ["--output", str(output_path)]

        start = time.time()
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, error="z-ai video timed out after 600s")

        if proc.returncode != 0:
            return ToolResult(
                success=False,
                error=f"z-ai video failed (exit {proc.returncode}): {proc.stderr[:500]}"
            )
        if not output_path.exists():
            return ToolResult(success=False, error=f"Output JSON missing: {output_path}")

        # Parse result JSON — find the JSON in stdout
        result_data: dict[str, Any] = {}
        try:
            result_data = json.loads(output_path.read_text())
        except Exception:
            stdout = proc.stdout
            json_start = stdout.find("{")
            if json_start >= 0:
                try:
                    result_data = json.loads(stdout[json_start:])
                except Exception:
                    pass

        video_url = result_data.get("video_url") or result_data.get("url")
        video_output = inputs.get("video_output_path")
        downloaded: str | None = None
        if video_url and video_output:
            downloaded = _download(video_url, video_output)

        return ToolResult(
            success=True,
            data={
                "provider": self.provider,
                "prompt": inputs.get("prompt", ""),
                "video_url": video_url,
                "downloaded_to": downloaded,
                "result_json": str(output_path),
            },
            artifacts=[s for s in [str(output_path), downloaded] if s],
            duration_seconds=round(time.time() - start, 2),
        )


def _download(url: str, dest: str) -> str | None:
    """Download a URL to a local path. Returns the dest path or None on failure."""
    import urllib.request
    try:
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(url, dest)
        return dest
    except Exception:
        return None
