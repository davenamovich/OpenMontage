"""OmniVoice TTS provider tool.

Calls the OmniVoice API for text-to-speech with multi-voice support.
Requires an OMNIVOICE_API_KEY environment variable.

OmniVoice supports:
- Multiple languages
- Multiple voice profiles per language
- SSML input for fine-grained control
- Emotion/style control

Auth: Set OMNIVOICE_API_KEY in your environment or .env file.
Endpoint: Configurable via OMNIVOICE_API_URL (default: https://api.omnivoice.ai/v1)

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


OMNIVOICE_API_URL = os.environ.get("OMNIVOICE_API_URL", "https://api.omnivoice.ai/v1/tts")


class OmniVoiceTTS(BaseTool):
    name = "omnivoice_tts"
    version = "0.1.0"
    tier = ToolTier.VOICE
    capability = "tts"
    provider = "omnivoice"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.API

    dependencies = ["env:OMNIVOICE_API_KEY"]
    install_instructions = (
        "OmniVoice TTS requires an API key.\n"
        "1. Sign up at https://omnivoice.ai\n"
        "2. Get your API key from the dashboard\n"
        "3. Set environment variable:\n"
        "   export OMNIVOICE_API_KEY=your_key_here\n"
        "4. (Optional) Set OMNIVOICE_DEFAULT_VOICE to your preferred voice\n"
        "5. (Optional) Set OMNIVOICE_API_URL if using a custom endpoint"
    )
    agent_skills = ["text-to-speech", "multi-voice"]

    capabilities = ["text_to_speech", "multilingual", "ssml", "emotion_control"]
    supports = {
        "voice_cloning": False,
        "multilingual": True,
        "offline": False,
        "voice_ids": True,
        "speed_control": True,
        "pitch_control": True,
        "ssml": True,
        "emotions": True,
    }
    best_for = [
        "multi-language narration with consistent quality",
        "emotion-controlled TTS (happy, sad, neutral, etc.)",
        "SSML-supported fine-grained speech control",
        "batch voice generation across many characters",
    ]
    not_good_for = [
        "use without an API key",
        "offline generation",
        "voice cloning (use fish_audio_tts instead)",
    ]
    fallback_tools = ["zai_tts", "piper_tts", "fish_audio_tts"]

    input_schema = {
        "type": "object",
        "required": ["text", "output_path"],
        "properties": {
            "text": {"type": "string", "description": "Text to convert to speech"},
            "output_path": {"type": "string", "description": "Output audio file path"},
            "voice_id": {
                "type": "string",
                "description": "OmniVoice voice ID. Falls back to OMNIVOICE_DEFAULT_VOICE env var.",
            },
            "speed": {
                "type": "number",
                "minimum": 0.5,
                "maximum": 2.0,
                "default": 1.0,
            },
            "pitch": {
                "type": "number",
                "minimum": -12,
                "maximum": 12,
                "default": 0,
                "description": "Pitch adjustment in semitones",
            },
            "emotion": {
                "type": "string",
                "enum": ["neutral", "happy", "sad", "angry", "surprised", "calm", "fearful"],
                "default": "neutral",
            },
            "format": {
                "type": "string",
                "enum": ["mp3", "wav", "ogg"],
                "default": "mp3",
            },
            "language": {
                "type": "string",
                "description": "Language code (e.g. 'en-US', 'zh-CN'). Auto-detected if omitted.",
            },
            "ssml": {
                "type": "boolean",
                "default": False,
                "description": "If true, text is treated as SSML.",
            },
        },
    }

    resource_profile = ResourceProfile(cpu_cores=1, ram_mb=128, vram_mb=0, disk_mb=10, network_required=True)
    retry_policy = RetryPolicy(max_retries=2, retryable_errors=["timeout", "rate_limit", "5xx"])
    idempotency_key_fields = ["text", "voice_id", "speed", "emotion"]
    side_effects = ["writes audio file to output_path"]
    user_visible_verification = ["Listen to generated audio"]

    def get_status(self) -> ToolStatus:
        if os.environ.get("OMNIVOICE_API_KEY"):
            return ToolStatus.AVAILABLE
        return ToolStatus.UNAVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        # OmniVoice pricing: roughly $0.008 per 1000 characters
        text = inputs.get("text", "")
        return round(len(text) / 1000 * 0.008, 4)

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        api_key = os.environ.get("OMNIVOICE_API_KEY")
        if not api_key:
            return ToolResult(success=False, error="OMNIVOICE_API_KEY not set. " + self.install_instructions)

        text = inputs.get("text", "")
        if not text:
            return ToolResult(success=False, error="Missing required input: text")
        output_path_str = inputs.get("output_path")
        if not output_path_str:
            return ToolResult(success=False, error="Missing required input: output_path")
        output_path = Path(output_path_str)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        voice_id = inputs.get("voice_id") or os.environ.get("OMNIVOICE_DEFAULT_VOICE", "")
        if not voice_id:
            return ToolResult(success=False, error="No voice_id provided. Set OMNIVOICE_DEFAULT_VOICE or pass voice_id in inputs.")

        speed = inputs.get("speed", 1.0)
        pitch = inputs.get("pitch", 0)
        emotion = inputs.get("emotion", "neutral")
        fmt = inputs.get("format", "mp3")
        language = inputs.get("language", "")
        is_ssml = inputs.get("ssml", False)

        # Build request body
        body_dict = {
            "text": text,
            "voice": voice_id,
            "format": fmt,
            "speed": speed,
            "pitch": pitch,
            "emotion": emotion,
            "ssml": is_ssml,
        }
        if language:
            body_dict["language"] = language

        body = json.dumps(body_dict).encode("utf-8")

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        start = time.time()
        try:
            req = urllib.request.Request(OMNIVOICE_API_URL, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=120) as resp:
                audio_data = resp.read()
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")[:500]
            return ToolResult(success=False, error=f"OmniVoice API error {exc.code}: {error_body}")
        except Exception as exc:
            return ToolResult(success=False, error=f"OmniVoice request failed: {exc}")

        if not audio_data:
            return ToolResult(success=False, error="OmniVoice returned empty response")

        output_path.write_bytes(audio_data)
        if not output_path.exists() or output_path.stat().st_size == 0:
            return ToolResult(success=False, error=f"Failed to write audio to {output_path}")

        return ToolResult(
            success=True,
            data={
                "provider": self.provider,
                "voice_id": voice_id,
                "speed": speed,
                "pitch": pitch,
                "emotion": emotion,
                "format": fmt,
                "output": str(output_path),
                "text_length": len(text),
            },
            artifacts=[str(output_path)],
            duration_seconds=round(time.time() - start, 2),
        )
