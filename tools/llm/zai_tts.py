"""Z-AI TTS tool — wraps `z-ai tts` CLI.

Generates speech from text. Output formats: wav, mp3, pcm.
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


# Voice catalog (extend as more voices are added to z-ai)
KNOWN_VOICES = {
    "tongtong": "warm female voice (default)",
    # Future: more voices as z-ai adds them
}


class ZaiTTS(BaseTool):
    name = "zai_tts"
    version = "0.1.0"
    tier = ToolTier.VOICE
    capability = "tts"
    provider = "zai"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.API

    dependencies = ["cmd:z-ai"]
    install_instructions = "z-ai CLI must be on PATH."
    agent_skills = ["text-to-speech", "TTS"]

    capabilities = ["text_to_speech"]
    supports = {
        "voice_ids": list(KNOWN_VOICES.keys()),
        "speed_control": True,
        "multilingual": True,
        "offline": False,
    }
    best_for = [
        "narration for YouTube romance videos",
        "character dialogue",
        "free TTS with no API key",
    ]
    not_good_for = ["offline use", "voice cloning"]
    fallback_tools = ["piper_tts", "elevenlabs_tts", "openai_tts", "google_tts"]

    input_schema = {
        "type": "object",
        "required": ["text", "output_path"],
        "properties": {
            "text": {"type": "string"},
            "output_path": {"type": "string"},
            "voice": {
                "type": "string",
                "default": "tongtong",
                "description": f"Voice ID. Known: {list(KNOWN_VOICES.keys())}",
            },
            "speed": {
                "type": "number",
                "minimum": 0.5,
                "maximum": 2.0,
                "default": 1.0,
            },
            "format": {
                "type": "string",
                "enum": ["wav", "mp3", "pcm"],
                "default": "wav",
            },
        },
    }

    resource_profile = ResourceProfile(cpu_cores=1, ram_mb=128, vram_mb=0, disk_mb=10, network_required=True)
    retry_policy = RetryPolicy(max_retries=2, retryable_errors=["timeout", "rate_limit"])
    idempotency_key_fields = ["text", "voice", "speed"]
    side_effects = ["writes audio file to output_path"]
    user_visible_verification = ["Listen to generated audio"]

    def get_status(self) -> ToolStatus:
        if shutil.which("z-ai"):
            return ToolStatus.AVAILABLE
        return ToolStatus.UNAVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.0  # free in this environment

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        if self.get_status() != ToolStatus.AVAILABLE:
            return ToolResult(success=False, error="z-ai CLI not available. " + self.install_instructions)

        text = inputs["text"]
        output_path = Path(inputs["output_path"])
        output_path.parent.mkdir(parents=True, exist_ok=True)

        voice = inputs.get("voice", "tongtong")
        speed = inputs.get("speed", 1.0)
        fmt = inputs.get("format", "wav")

        cmd = [
            "z-ai", "tts",
            "--input", text,
            "--output", str(output_path),
            "--voice", voice,
            "--speed", str(speed),
            "--format", fmt,
        ]

        start = time.time()
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, error="z-ai tts timed out after 120s")

        if proc.returncode != 0:
            return ToolResult(
                success=False,
                error=f"z-ai tts failed (exit {proc.returncode}): {proc.stderr[:500]}"
            )
        if not output_path.exists():
            return ToolResult(success=False, error=f"Output audio missing: {output_path}")

        return ToolResult(
            success=True,
            data={
                "provider": self.provider,
                "voice": voice,
                "speed": speed,
                "format": fmt,
                "output": str(output_path),
                "text_length": len(text),
            },
            artifacts=[str(output_path)],
            duration_seconds=round(time.time() - start, 2),
        )
