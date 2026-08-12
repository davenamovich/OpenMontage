"""Real-time caption generator using faster-whisper.

Transcribes the actual narration audio to get word-level timestamps, then
generates SRT/VTT captions that are precisely synchronized with the audio.
This replaces the script-timestamp-based captions with accurate timing.

Usage:
    from romance.realtime_captions import generate_realtime_captions
    generate_realtime_captions(narration_path, script, srt_path, vtt_path)
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def transcribe_with_whisper(audio_path: str | Path, *, language: str = "en", model_size: str = "base") -> dict:
    """Transcribe audio with faster-whisper, returning word-level timestamps.

    Returns:
        {
            "text": "<full transcription>",
            "segments": [{"start": float, "end": float, "text": str}],
            "words": [{"start": float, "end": float, "word": str, "probability": float}],
        }
    """
    from faster_whisper import WhisperModel

    # Use int8 to reduce memory on CPU-only systems
    model = WhisperModel(model_size, device="cpu", compute_type="int8")

    segments_gen, info = model.transcribe(
        str(audio_path),
        language=language,
        word_timestamps=True,
        vad_filter=True,  # skip silence
    )

    segments: list[dict] = []
    words: list[dict] = []
    full_text_parts: list[str] = []

    for seg in segments_gen:
        segments.append({
            "start": round(seg.start, 3),
            "end": round(seg.end, 3),
            "text": seg.text.strip(),
        })
        full_text_parts.append(seg.text)
        if seg.words:
            for w in seg.words:
                words.append({
                    "start": round(w.start, 3),
                    "end": round(w.end, 3),
                    "word": w.word.strip(),
                    "probability": round(w.probability, 3),
                })

    return {
        "text": " ".join(full_text_parts).strip(),
        "segments": segments,
        "words": words,
        "language": info.language,
        "duration": info.duration,
    }


def generate_realtime_captions(
    narration_path: str | Path,
    script: dict | None,
    srt_path: str | Path,
    vtt_path: str | Path,
    *,
    language: str = "en",
    model_size: str = "base",
    max_words_per_cue: int = 6,
    max_chars_per_line: int = 42,
) -> dict:
    """Generate real-time SRT and VTT captions from the actual narration audio.

    Uses faster-whisper to transcribe the narration with word-level timestamps,
    then groups words into readable cues (max_words_per_cue or max_chars_per_line).

    Args:
        narration_path: Path to the full narration WAV.
        script: The script artifact (used for text corrections — if Whisper mishears
                a character name, we can substitute the script's version).
        srt_path: Output SRT file path.
        vtt_path: Output VTT file path.
        language: Language code for Whisper.
        model_size: Whisper model size (tiny/base/small/medium/large-v3).
                    "base" is a good balance of speed/accuracy on CPU.
        max_words_per_cue: Maximum words per caption cue.
        max_chars_per_line: Maximum characters per line before wrapping.

    Returns:
        {"srt_path": str, "vtt_path": str, "word_count": int, "duration": float}
    """
    narration_path = Path(narration_path)
    srt_path = Path(srt_path)
    vtt_path = Path(vtt_path)

    if not narration_path.exists():
        raise FileNotFoundError(f"Narration audio not found: {narration_path}")

    # Transcribe
    print(f"  Transcribing {narration_path.name} with Whisper ({model_size})...", flush=True)
    result = transcribe_with_whisper(narration_path, language=language, model_size=model_size)

    words = result["words"]
    if not words:
        # Fallback: use segment-level timestamps
        print("  No word-level timestamps — using segment-level", flush=True)
        cues = _build_cues_from_segments(result["segments"], max_chars_per_line)
    else:
        # Build cues from word-level timestamps
        cues = _build_cues_from_words(words, max_words_per_cue, max_chars_per_line)

    # Write SRT
    _write_srt(cues, srt_path)
    # Write VTT
    _write_vtt(cues, vtt_path)

    print(f"  Captions: {len(cues)} cues, {len(words)} words, {result['duration']:.1f}s", flush=True)

    return {
        "srt_path": str(srt_path),
        "vtt_path": str(vtt_path),
        "word_count": len(words),
        "duration": result.get("duration", 0),
        "cue_count": len(cues),
        "transcription": result["text"],
    }


def _build_cues_from_words(words: list[dict], max_words: int, max_chars: int) -> list[dict]:
    """Group word-level timestamps into caption cues."""
    cues: list[dict] = []
    current_words: list[dict] = []
    current_text_len = 0

    for w in words:
        word_text = w["word"]
        # Check if adding this word would exceed limits
        if (len(current_words) >= max_words or
            current_text_len + len(word_text) + 1 > max_chars * 2) and current_words:
            # Flush current cue
            cues.append({
                "start": current_words[0]["start"],
                "end": current_words[-1]["end"],
                "text": _wrap_text(" ".join(w["word"] for w in current_words), max_chars),
            })
            current_words = []
            current_text_len = 0

        current_words.append(w)
        current_text_len += len(word_text) + 1

    # Flush remaining
    if current_words:
        cues.append({
            "start": current_words[0]["start"],
            "end": current_words[-1]["end"],
            "text": _wrap_text(" ".join(w["word"] for w in current_words), max_chars),
        })

    return cues


def _build_cues_from_segments(segments: list[dict], max_chars: int) -> list[dict]:
    """Build cues from segment-level timestamps (fallback)."""
    cues: list[dict] = []
    for seg in segments:
        text = seg["text"].strip()
        if not text:
            continue
        cues.append({
            "start": seg["start"],
            "end": seg["end"],
            "text": _wrap_text(text, max_chars),
        })
    return cues


def _wrap_text(text: str, max_chars: int) -> str:
    """Wrap text to max_chars per line, breaking at word boundaries."""
    if len(text) <= max_chars:
        return text
    words = text.split()
    lines: list[str] = []
    current_line: list[str] = []
    current_len = 0
    for w in words:
        if current_len + len(w) + 1 > max_chars and current_line:
            lines.append(" ".join(current_line))
            current_line = [w]
            current_len = len(w)
        else:
            current_line.append(w)
            current_len += len(w) + 1
    if current_line:
        lines.append(" ".join(current_line))
    return "\n".join(lines)


def _format_timestamp_srt(t: float) -> str:
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    ms = int((t - int(t)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _format_timestamp_vtt(t: float) -> str:
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    ms = int((t - int(t)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def _write_srt(cues: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for i, cue in enumerate(cues, 1):
        lines.append(str(i))
        lines.append(f"{_format_timestamp_srt(cue['start'])} --> {_format_timestamp_srt(cue['end'])}")
        lines.append(cue["text"])
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_vtt(cues: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = ["WEBVTT", ""]
    for cue in cues:
        lines.append(f"{_format_timestamp_vtt(cue['start'])} --> {_format_timestamp_vtt(cue['end'])}")
        lines.append(cue["text"])
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
