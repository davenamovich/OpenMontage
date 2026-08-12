"""Stage 10: Voice Generation.

Generates one audio file per script section using the best available TTS
provider. Provider priority: fish_audio_tts → omnivoice_tts → zai_tts →
piper_tts. The narrator voice comes from the story_bible (the protagonist
or a designated narrator character). Each speaking character with dialogue
gets their own voice_id.

Supports per-character voice provider selection — if the story_bible
specifies a different provider for a character (e.g. fish_audio for the
narrator, zai_tts for a minor character), the stage honors that.
"""

from __future__ import annotations

import re
from pathlib import Path

from romance.stages._shared import get_best_tts_tool, timed


def run(engine, payload: dict) -> dict:
    return timed(lambda: _run(engine, payload))


def _split_dialogue(text: str) -> list[dict]:
    """Split a script section text into narrator/dialogue segments.

    Looks for patterns like 'DANIEL (quietly): "text"' or 'DANIEL: text'.
    Returns a list of {speaker: 'narrator'|'character_id', text: ...}.
    """
    pattern = re.compile(
        r'([A-Z_][A-Z_ ]{1,40}?)\s*(?:\([^)]+\))?\s*:\s*(?:"([^"]+)"|([^.\n]+?))(?=[\n.]|[A-Z_][A-Z_ ]{1,40}?\s*(?:\(|:)|$)',
        re.MULTILINE,
    )
    segments: list[dict] = []
    last_end = 0
    for m in pattern.finditer(text):
        if m.start() > last_end:
            narrator_text = text[last_end:m.start()].strip()
            if narrator_text:
                segments.append({"speaker": "narrator", "text": narrator_text})
        speaker = m.group(1).strip().lower().replace(" ", "_")
        dialogue = (m.group(2) or m.group(3) or "").strip()
        if dialogue:
            segments.append({"speaker": speaker, "text": dialogue})
        last_end = m.end()
    if last_end < len(text):
        narrator_text = text[last_end:].strip()
        if narrator_text:
            segments.append({"speaker": "narrator", "text": narrator_text})
    if not segments:
        segments = [{"speaker": "narrator", "text": text}]
    return segments


def _get_tts_tool_for_provider(provider_name: str):
    """Get a specific TTS tool instance by provider name."""
    from tools.base_tool import ToolStatus

    if provider_name == "fish_audio_tts":
        from tools.llm.fish_audio_tts import FishAudioTTS
        tool = FishAudioTTS()
        return tool if tool.get_status() == ToolStatus.AVAILABLE else None
    elif provider_name == "omnivoice_tts":
        from tools.llm.omnivoice_tts import OmniVoiceTTS
        tool = OmniVoiceTTS()
        return tool if tool.get_status() == ToolStatus.AVAILABLE else None
    elif provider_name == "zai_tts":
        from tools.llm.zai_tts import ZaiTTS
        tool = ZaiTTS()
        return tool if tool.get_status() == ToolStatus.AVAILABLE else None
    elif provider_name == "piper_tts":
        from tools.audio.piper_tts import PiperTTS
        tool = PiperTTS()
        return tool if tool.get_status() == ToolStatus.AVAILABLE else None
    return None


def _run(engine, payload: dict) -> dict:
    script = engine.load_artifact("script")
    bible = engine.load_artifact("story_bible")
    if not script or not bible:
        return {"error": "Missing script or story_bible"}

    # Pick the best available TTS tool
    default_tts, default_provider = get_best_tts_tool()
    if default_tts is None:
        return {"error": "No TTS tool available. Install fish.audio, omnivoice, z-ai, or piper."}

    engine.log("voice_generation", f"Using TTS provider: {default_provider}")

    # Determine narrator voice config
    narrator_char = next(
        (c for c in bible.get("characters", [])
         if c.get("role") == "protagonist" or "narrator" in c.get("character_id", "").lower()),
        bible.get("characters", [{}])[0] if bible.get("characters") else {},
    )
    narrator_voice = narrator_char.get("voice", {}).get("voice_id", "tongtong")
    narrator_speed = narrator_char.get("voice", {}).get("speed", 1.0)
    narrator_provider = narrator_char.get("voice", {}).get("provider", default_provider)

    # Map character_id → voice config
    voice_by_char = {
        c["character_id"]: c.get("voice", {})
        for c in bible.get("characters", [])
    }

    # Load existing manifest
    manifest = engine.load_artifact("asset_manifest") or {
        "version": "1.0", "project_id": engine.project_id, "assets": [],
    }
    assets = manifest.get("assets", [])
    assets = [a for a in assets if a.get("type") != "narration_audio"]
    assets = [a for a in assets if a.get("type") != "dialogue_audio"]
    assets = [a for a in assets if a.get("type") != "section_audio"]

    results_log = []
    section_audios: list[dict] = []

    for section in script.get("sections", []):
        sid = section["id"]
        text = section.get("text", "")
        if not text.strip():
            continue

        segments = _split_dialogue(text)
        segment_paths: list[str] = []

        for i, seg in enumerate(segments):
            speaker = seg["speaker"]
            seg_text = seg["text"]
            if not seg_text.strip():
                continue

            if speaker == "narrator":
                voice = narrator_voice
                speed = narrator_speed
                provider_name = narrator_provider
                filename = f"narr-{sid}-{i:02d}.wav"
            else:
                vcfg = voice_by_char.get(speaker, {})
                voice = vcfg.get("voice_id", narrator_voice)
                speed = vcfg.get("speed", 1.0)
                provider_name = vcfg.get("provider", default_provider)
                filename = f"dlg-{sid}-{speaker}-{i:02d}.wav"

            out_path = engine.asset_path("voice", filename)

            # Skip if already generated (resume support)
            if out_path.exists() and out_path.stat().st_size > 0:
                segment_paths.append(str(out_path))
                results_log.append({"section": sid, "segment": i, "speaker": speaker, "path": str(out_path), "provider": provider_name, "skipped": True})
                continue

            # Get the right TTS tool for this provider
            if provider_name == default_provider:
                tts = default_tts
            else:
                tts = _get_tts_tool_for_provider(provider_name)
                if tts is None:
                    # Fall back to default provider
                    tts = default_tts
                    provider_name = default_provider

            # Build inputs based on provider capabilities
            tts_inputs = {
                "text": seg_text,
                "output_path": str(out_path),
                "voice": voice,
                "speed": speed,
                "format": "wav",
            }

            # Add emotion for OmniVoice if supported
            if provider_name == "omnivoice_tts":
                # Map beat type to emotion (simplified)
                section_idx = int(sid.lstrip("s")) if sid.startswith("s") and sid[1:].isdigit() else 1
                emotions = ["neutral", "curious", "neutral", "happy", "conflicted", "shocked", "sad", "determined", "happy", "neutral"]
                tts_inputs["emotion"] = emotions[min(section_idx - 1, len(emotions) - 1)] if section_idx <= len(emotions) else "neutral"

            result = tts.execute(tts_inputs)
            if not result.success:
                engine.log("voice_generation",
                           f"TTS failed for {sid}/{i} ({speaker}, {provider_name}): {result.error}")
                # Try fallback to default provider
                if provider_name != default_provider:
                    engine.log("voice_generation", f"Falling back to {default_provider}")
                    result = default_tts.execute(tts_inputs)
                    if result.success:
                        provider_name = default_provider
                if not result.success:
                    results_log.append({"section": sid, "segment": i, "speaker": speaker, "error": result.error})
                    continue

            segment_paths.append(str(out_path))
            assets.append({
                "type": "narration_audio" if speaker == "narrator" else "dialogue_audio",
                "section_id": sid,
                "segment_index": i,
                "speaker": speaker,
                "voice_id": voice,
                "provider": provider_name,
                "path": str(out_path),
                "text": seg_text,
            })
            results_log.append({"section": sid, "segment": i, "speaker": speaker, "path": str(out_path), "provider": provider_name})

        # Concatenate this section's audio segments into one file
        if segment_paths:
            section_path = engine.asset_path("voice", f"section-{sid}.wav")
            _concat_audio(segment_paths, section_path)
            section_audios.append({
                "section_id": sid,
                "path": str(section_path),
                "start_seconds": section.get("start_seconds", 0),
                "end_seconds": section.get("end_seconds", 0),
                "text": text,
            })
            assets.append({
                "type": "section_audio",
                "section_id": sid,
                "path": str(section_path),
                "start_seconds": section.get("start_seconds", 0),
                "end_seconds": section.get("end_seconds", 0),
            })

    manifest = {
        "version": "1.0",
        "project_id": engine.project_id,
        "assets": assets,
        "metadata": {
            **manifest.get("metadata", {}),
            "stage": "voice_generation",
            "narrator_voice": narrator_voice,
            "narrator_provider": narrator_provider,
            "default_tts_provider": default_provider,
            "sections_processed": len(section_audios),
            "section_audios": section_audios,
            "results": results_log,
        },
    }
    engine.log("voice_generation",
               "Voice generation complete",
               sections=len(section_audios),
               provider=default_provider)
    return {
        "artifact": "asset_manifest",
        "data": manifest,
    }


def _concat_audio(segment_paths: list[str], output_path: Path) -> bool:
    """Concatenate WAV files using ffmpeg. Returns True on success."""
    import subprocess
    if not segment_paths:
        return False
    if len(segment_paths) == 1:
        import shutil
        shutil.copy(segment_paths[0], output_path)
        return True
    list_file = output_path.parent / f"concat-{output_path.stem}.txt"
    with open(list_file, "w") as f:
        for p in segment_paths:
            f.write(f"file '{p}'\n")
    try:
        proc = subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
             "-c", "copy", str(output_path)],
            capture_output=True, text=True, timeout=60,
        )
        list_file.unlink(missing_ok=True)
        return proc.returncode == 0 and output_path.exists()
    except Exception:
        list_file.unlink(missing_ok=True)
        return False
