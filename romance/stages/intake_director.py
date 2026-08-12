"""Stage 1: Intake.

Validates user input, fills defaults, runs a content-safety check, and writes
the canonical `brief` artifact (conforming to the existing OpenMontage brief
schema). Romance-specific fields go under metadata.
"""

from __future__ import annotations

import json

from romance.constants import (
    GENRE_LABELS, FORMAT_LABELS, VISUAL_MODE_LABELS,
    ERA_LABELS, ERA_VISUAL_CUES, VISUAL_STYLE_LABELS,
    VISUAL_STYLE_MODIFIERS, VISUAL_STYLE_NEGATIVES,
)
from romance.engine import load_intake_defaults
from romance.stages._shared import timed


SAFETY_BLOCKLIST = [
    "minor", "underage", "child", "kid", "13 year", "14 year", "15 year",
    "16 year", "17 year",
]


def _safety_check(intake: dict) -> list[str]:
    """Return a list of safety warnings. Empty list = OK."""
    warnings: list[str] = []
    text = " ".join(str(v) for v in intake.values()).lower()
    for term in SAFETY_BLOCKLIST:
        if term in text:
            if term in ("child", "kid"):
                if any(w in text for w in ["marry", "kiss", "date", "love interest", "romance with"]):
                    warnings.append(
                        f"Possible minor reference in romantic context: '{term}'. "
                        "All romantic characters must be adults (18+)."
                    )
            else:
                warnings.append(f"Possible underage reference: '{term}'")
    return warnings


def run(engine, payload: dict) -> dict:
    """Run the intake stage. payload may contain intake fields to override."""
    return timed(lambda: _run(engine, payload))


def _run(engine, payload: dict) -> dict:
    existing = engine.load_intake()
    merged = {**existing, **payload}
    intake = load_intake_defaults(merged)

    warnings = _safety_check(intake)

    # Build brief artifact conforming to the existing OpenMontage brief schema
    # (additionalProperties: false). Romance-specific fields go under metadata.
    brief = {
        "version": "1.0",
        "title": intake.get("title") or intake["premise"][:80],
        "hook": intake["premise"],  # The premise IS the hook for the intake stage
        "key_points": [
            f"Genre: {GENRE_LABELS.get(intake['genre'], intake['genre'])}",
            f"Format: {FORMAT_LABELS.get(intake['format'], intake['format'])}",
            f"Setting: {intake['setting']}",
            f"Tone: {intake['emotional_tone']}",
            f"Desired ending: {intake['desired_ending']}",
        ],
        "core_message": intake["premise"],
        "cta": intake["call_to_action"],
        "tone": intake["emotional_tone"],
        "style": intake.get("visual_style", "cinematic-realism"),
        "target_audience": intake["target_audience"],
        "target_platform": "youtube",
        "target_duration_seconds": intake["target_duration"],
        "metadata": {
            # Romance-specific fields
            "premise": intake["premise"],
            "format": intake["format"],
            "genre": intake["genre"],
            "genre_label": GENRE_LABELS.get(intake["genre"], intake["genre"]),
            "format_label": FORMAT_LABELS.get(intake["format"], intake["format"]),
            "visual_mode": intake["visual_mode"],
            "visual_mode_label": VISUAL_MODE_LABELS.get(intake["visual_mode"], intake["visual_mode"]),
            "era": intake.get("era", "modern"),
            "era_label": ERA_LABELS.get(intake.get("era", "modern"), "Modern"),
            "era_visual_cues": ERA_VISUAL_CUES.get(intake.get("era", "modern"), ""),
            "visual_style": intake.get("visual_style", "cinematic_realism"),
            "visual_style_label": VISUAL_STYLE_LABELS.get(intake.get("visual_style", "cinematic_realism"), "Cinematic Realism"),
            "visual_style_modifier": VISUAL_STYLE_MODIFIERS.get(intake.get("visual_style", "cinematic_realism"), ""),
            "visual_style_negative": VISUAL_STYLE_NEGATIVES.get(intake.get("visual_style", "cinematic_realism"), ""),
            "target_word_count": intake["target_word_count"],
            "setting": intake["setting"],
            "time_period": intake["time_period"],
            "narration_perspective": intake["narration_perspective"],
            "language": intake["language"],
            "output_aspect_ratio": intake["output_aspect_ratio"],
            "romance_intensity": intake["romance_intensity"],
            "drama_intensity": intake["drama_intensity"],
            "mystery_intensity": intake["mystery_intensity"],
            "desired_ending": intake["desired_ending"],
            "number_of_episodes": intake["number_of_episodes"],
            "channel_name": intake["channel_name"],
            "max_budget_usd": intake["max_budget_usd"],
            "narrator_voice": intake["narrator_voice"],
            "character_voices": intake["character_voices"],
            "music_style": intake["music_style"],
            "main_character_names": intake.get("main_character_names") or [],
            "character_ages": intake.get("character_ages") or [],
            "character_descriptions": intake.get("character_descriptions") or [],
            "safety_warnings": warnings,
            "source_text": intake.get("source_text", ""),
            "reference_images": intake.get("reference_images", []),
        },
    }
    # Persist intake.json so other stages and the UI can read it
    (engine.project_dir / "intake.json").write_text(
        json.dumps(intake, indent=2, ensure_ascii=False)
    )
    engine.project["intake"] = intake
    engine._save_project()
    engine.log("intake", "Intake completed", warnings=warnings)
    return {
        "artifact": "brief",
        "data": brief,
        "warnings": warnings,
    }
