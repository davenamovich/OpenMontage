"""Shared helpers for stage directors."""

from __future__ import annotations

import time
from typing import Any, Callable

from romance.llm_bridge import chat_json


def timed(fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """Wrap a stage function to record duration_seconds."""
    start = time.time()
    result = fn()
    result["duration_seconds"] = round(time.time() - start, 2)
    return result


def llm_json(prompt: str, system: str | None = None, *, thinking: bool = False, timeout: int = 300, retries: int = 2) -> Any:
    """Convenience wrapper around chat_json for stage directors."""
    return chat_json(prompt, system=system, thinking=thinking, timeout=timeout, retries=retries)


def brief_meta(brief: dict | None) -> dict:
    """Extract romance-specific metadata from a brief artifact.

    The brief conforms to the existing OpenMontage brief schema, so all
    romance-specific fields live under brief['metadata'].
    """
    if not brief:
        return {}
    return brief.get("metadata", {}) or {}


def render_output(render_report: dict | None, name: str) -> str | None:
    """Extract an output path from a render_report.

    Handles both the old dict format (outputs.final_video) and the schema-
    compliant array format (outputs[].path where platform_target matches).
    Also falls back to metadata fields.
    """
    if not render_report:
        return None
    outputs = render_report.get("outputs", {})
    if isinstance(outputs, dict):
        return outputs.get(name)
    if isinstance(outputs, list):
        # Search by metadata key or platform_target
        for o in outputs:
            path = o.get("path", "")
            if name == "final_video" and ("youtube" in path or "short" in path) and "clean" not in path:
                return path
            if name == "clean_video" and "clean" in path:
                return path
            if name == "srt" and path.endswith(".srt"):
                return path
            if name == "vtt" and path.endswith(".vtt"):
                return path
    # Fallback to metadata
    metadata = render_report.get("metadata", {})
    return metadata.get(name) or metadata.get(f"{name}_path")


def get_best_image_tool():
    """Return the best available image generation tool.

    Preference order:
    1. comfy_image — if ComfyUI is running locally (free, full control, negative prompts)
    2. zai_image — if z-ai CLI is available (free, no setup)
    3. None — caller must handle
    """
    from tools.base_tool import ToolStatus

    # Try ComfyUI first
    try:
        from tools.llm.comfy_image import ComfyImage
        tool = ComfyImage()
        if tool.get_status() == ToolStatus.AVAILABLE:
            return tool, "comfy_image"
    except Exception:
        pass

    # Fall back to z-ai image
    try:
        from tools.llm.zai_image import ZaiImage
        tool = ZaiImage()
        if tool.get_status() == ToolStatus.AVAILABLE:
            return tool, "zai_image"
    except Exception:
        pass

    return None, None


def get_best_tts_tool():
    """Return the best available TTS tool.

    Preference order:
    1. fish_audio_tts — if FISH_AUDIO_API_KEY is set (premium, voice cloning)
    2. omnivoice_tts — if OMNIVOICE_API_KEY is set (multi-voice, emotion control)
    3. zai_tts — if z-ai CLI is available (free, no setup)
    4. piper_tts — if Piper is installed (offline, local)
    5. None — caller must handle
    """
    from tools.base_tool import ToolStatus

    # Try Fish.Audio first
    try:
        from tools.llm.fish_audio_tts import FishAudioTTS
        tool = FishAudioTTS()
        if tool.get_status() == ToolStatus.AVAILABLE:
            return tool, "fish_audio_tts"
    except Exception:
        pass

    # Try OmniVoice
    try:
        from tools.llm.omnivoice_tts import OmniVoiceTTS
        tool = OmniVoiceTTS()
        if tool.get_status() == ToolStatus.AVAILABLE:
            return tool, "omnivoice_tts"
    except Exception:
        pass

    # Fall back to z-ai TTS
    try:
        from tools.llm.zai_tts import ZaiTTS
        tool = ZaiTTS()
        if tool.get_status() == ToolStatus.AVAILABLE:
            return tool, "zai_tts"
    except Exception:
        pass

    # Last resort: Piper (offline)
    try:
        from tools.audio.piper_tts import PiperTTS
        tool = PiperTTS()
        if tool.get_status() == ToolStatus.AVAILABLE:
            return tool, "piper_tts"
    except Exception:
        pass

    return None, None


def list_tts_providers() -> list[dict]:
    """Return all TTS providers and their availability status."""
    from tools.base_tool import ToolStatus

    providers = []
    tool_specs = [
        ("fish_audio_tts", "tools.llm.fish_audio_tts", "FishAudioTTS"),
        ("omnivoice_tts", "tools.llm.omnivoice_tts", "OmniVoiceTTS"),
        ("zai_tts", "tools.llm.zai_tts", "ZaiTTS"),
        ("piper_tts", "tools.audio.piper_tts", "PiperTTS"),
    ]
    for name, module_path, class_name in tool_specs:
        try:
            import importlib
            mod = importlib.import_module(module_path)
            cls = getattr(mod, class_name)
            tool = cls()
            providers.append({
                "name": name,
                "available": tool.get_status() == ToolStatus.AVAILABLE,
                "provider": tool.provider,
                "supports": tool.supports,
                "best_for": tool.best_for,
                "install_instructions": tool.install_instructions,
            })
        except Exception as exc:
            providers.append({
                "name": name,
                "available": False,
                "error": str(exc),
            })
    return providers


def get_publish_tool():
    """Return the UploadPost tool if available, else None."""
    from tools.base_tool import ToolStatus
    try:
        from tools.llm.uploadpost import UploadPostTool
        tool = UploadPostTool()
        if tool.get_status() == ToolStatus.AVAILABLE:
            return tool, "uploadpost"
    except Exception:
        pass
    return None, None


# Shared system prompt — keeps voice/style consistent across stages
ROMANCE_SYSTEM_PROMPT = """You are a senior YouTube romance-story writer and producer.

Your job is to produce original, emotionally believable, performance-ready romance
content for a faceless YouTube channel. You write for spoken narration, not silent
reading. Your work must be:

- Original. Never imitate living authors or use copyrighted characters.
- Emotionally believable. Attraction grows through specific moments, not declarations.
- Concrete. Sensory details, real objects, specific actions — not generic AI prose.
- Retention-aware. Hooks, questions, revelations, and visual changes throughout.
- Internally consistent. Characters do not change names, age, hair, wardrobe, or
  ethnicity between scenes.

You always respond with strictly valid JSON matching the requested schema — no
markdown, no commentary, no preamble. If a field is unknown, use an empty string
or empty array rather than omitting it."""

SAFETY_PROMPT = """

Content safety rules (non-negotiable):
- All romantic characters are adults (18+).
- No sexual content involving minors.
- No non-consensual sexual content, incest, or glorified abuse.
- If manipulation, stalking, coercion, or violence appears, do NOT frame it as
  romantic — frame it as the problem the protagonist must deal with.
- No real private people's faces or voices without permission.
- No copyrighted characters or direct imitation of living authors.
- If a story is presented as a confession, it must be labeled fictional unless
  the user has explicitly marked source material as verified and owned."""
