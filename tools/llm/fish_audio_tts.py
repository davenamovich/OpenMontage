"""Fish.Audio TTS provider tool.

Calls the Fish.Audio API (https://fish.audio) for high-quality text-to-speech
with voice cloning support. Requires a FISH_AUDIO_API_KEY environment variable.

Auth: Set FISH_AUDIO_API_KEY in your environment or .env file.
Voice IDs: Use Fish.Audio's voice library or clone your own.
Endpoint: https://api.fish.audio/v1/tts

If the API key is not set, the tool reports unavailable and the romance
pipeline falls back to zai_tts or piper_tts.
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
import urllib.error
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


FISH_AUDIO_API_URL = "https://api.fish.audio/v1/tts"


class FishAudioTTS(BaseTool):
    name = "fish_audio_tts"
    version = "0.1.0"
    tier = ToolTier.VOICE
    capability = "tts"
    provider = "fish_audio"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.API

    dependencies = ["env:FISH_AUDIO_API_KEY"]
    install_instructions = (
        "Fish.Audio TTS requires an API key.\n"
        "1. Sign up at https://fish.audio\n"
        "2. Get your API key from the dashboard\n"
        "3. Set environment variable:\n"
        "   export FISH_AUDIO_API_KEY=your_key_here\n"
        "4. (Optional) Set FISH_AUDIO_VOICE_ID to your preferred voice\n"
        "   Browse voices at https://fish.audio/zh-CN/voice/"
    )
    agent_skills = ["text-to-speech", "voice-cloning"]

    capabilities = ["text_to_speech", "voice_cloning", "multilingual"]
    supports = {
        "voice_cloning": True,
        "multilingual": True,
        "offline": False,
        "voice_ids": True,
        "speed_control": True,
        "pitch_control": False,
    }
    best_for = [
        "high-quality expressive narration",
        "voice cloning for consistent character voices",
        "multilingual TTS (50+ languages)",
        "premium voice quality when budget allows",
    ]
    not_good_for = [
        "use without an API key",
        "offline generation",
        "free-tier usage (Fish.Audio is a paid service)",
    ]
    fallback_tools = ["zai_tts", "piper_tts", "omnivoice_tts"]

    input_schema = {
        "type": "object",
        "required": ["text", "output_path"],
        "properties": {
            "text": {"type": "string", "description": "Text to convert to speech"},
            "output_path": {"type": "string", "description": "Output audio file path"},
            "voice_id": {
                "type": "string",
                "description": "Fish.Audio voice ID. Falls back to FISH_AUDIO_VOICE_ID env var.",
            },
            "speed": {
                "type": "number",
                "minimum": 0.5,
                "maximum": 2.0,
                "default": 1.0,
                "description": "Speech rate multiplier",
            },
            "format": {
                "type": "string",
                "enum": ["mp3", "wav"],
                "default": "mp3",
            },
            "language": {
                "type": "string",
                "description": "Language code (e.g. 'en', 'zh'). Auto-detected if omitted.",
            },
        },
    }

    resource_profile = ResourceProfile(cpu_cores=1, ram_mb=128, vram_mb=0, disk_mb=10, network_required=True)
    retry_policy = RetryPolicy(max_retries=2, retryable_errors=["timeout", "rate_limit", "5xx"])
    idempotency_key_fields = ["text", "voice_id", "speed"]
    side_effects = ["writes audio file to output_path"]
    user_visible_verification = ["Listen to generated audio"]

    def get_status(self) -> ToolStatus:
        if os.environ.get("FISH_AUDIO_API_KEY"):
            return ToolStatus.AVAILABLE
        return ToolStatus.UNAVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        # Fish.Audio pricing: roughly $0.01 per 1000 characters (varies by plan)
        text = inputs.get("text", "")
        return round(len(text) / 1000 * 0.01, 4)

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        api_key = os.environ.get("FISH_AUDIO_API_KEY")
        if not api_key:
            return ToolResult(success=False, error="FISH_AUDIO_API_KEY not set. " + self.install_instructions)

        text = inputs.get("text", "")
        if not text:
            return ToolResult(success=False, error="Missing required input: text")
        output_path_str = inputs.get("output_path")
        if not output_path_str:
            return ToolResult(success=False, error="Missing required input: output_path")
        output_path = Path(output_path_str)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        voice_id = inputs.get("voice_id") or os.environ.get("FISH_AUDIO_VOICE_ID", "")
        if not voice_id:
            return ToolResult(success=False, error="No voice_id provided. Set FISH_AUDIO_VOICE_ID or pass voice_id in inputs.")

        speed = inputs.get("speed", 1.0)
        fmt = inputs.get("format", "mp3")

        # Build request body (Fish.Audio API format)
        body = json.dumps({
            "text": text,
            "reference_id": voice_id,
            "format": fmt,
            "latency": "normal",  # normal | balanced | fast
            "prosody_speed": speed,
        }).encode("utf-8")

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        start = time.time()
        try:
            req = urllib.request.Request(FISH_AUDIO_API_URL, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=120) as resp:
                audio_data = resp.read()
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")[:500]
            return ToolResult(success=False, error=f"Fish.Audio API error {exc.code}: {error_body}")
        except Exception as exc:
            return ToolResult(success=False, error=f"Fish.Audio request failed: {exc}")

        if not audio_data:
            return ToolResult(success=False, error="Fish.Audio returned empty response")

        # Write audio to file
        output_path.write_bytes(audio_data)
        if not output_path.exists() or output_path.stat().st_size == 0:
            return ToolResult(success=False, error=f"Failed to write audio to {output_path}")

        return ToolResult(
            success=True,
            data={
                "provider": self.provider,
                "voice_id": voice_id,
                "speed": speed,
                "format": fmt,
                "output": str(output_path),
                "text_length": len(text),
            },
            artifacts=[str(output_path)],
            duration_seconds=round(time.time() - start, 2),
        )
