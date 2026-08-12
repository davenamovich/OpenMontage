"""Stage 7: Scene Plan.

Breaks the approved script into visual scenes. Each scene has shot type,
camera movement, composition, lighting, character actions, image prompt,
negative prompt, music cue, sound effects, transition, and continuity refs.

The output conforms to the existing OpenMontage scene_plan schema (extended
with our romance-specific fields under metadata).

Strategy: For MVP reliability, scenes are generated deterministically from
the script sections + story_bible. Each script section gets 3-6 scenes with
varied shot types and camera movements. The image_prompt is built from the
character's visual_reference_prompt + a snippet of the section text + the
shot's lighting/composition. This avoids LLM timeout issues and produces
consistent, schema-valid output.
"""

from __future__ import annotations

import re

from romance.stages._shared import brief_meta, timed


# Allowed enum values from scene_plan.schema.json
ALLOWED_SHOT_SIZES = ["establishing", "wide", "medium_wide", "medium", "medium_close", "close_up", "extreme_close_up", "over_shoulder", "insert"]
ALLOWED_CAMERA_MOVEMENTS = ["static", "pan_left", "pan_right", "tilt_up", "tilt_down", "dolly_in", "dolly_out", "tracking_left", "tracking_right", "handheld", "steadicam", "zoom_in", "zoom_out", "rack_focus"]
ALLOWED_LENS_MM = [24, 35, 50, 85, 135]
ALLOWED_LIGHTING_KEYS = ["natural", "golden_hour", "blue_hour", "tungsten_warm", "silhouette", "rim_lit", "volumetric", "overcast_soft"]
ALLOWED_DOF = ["shallow", "medium", "deep"]
ALLOWED_COLOR_TEMP = ["cool", "neutral", "warm", "mixed"]
ALLOWED_NARRATIVE_ROLES = ["establish_context", "introduce_subject", "build_tension", "deliver_payload", "transition", "emotional_beat", "resolution"]
ALLOWED_SCENE_TYPES = ["generated", "character_scene", "text_card", "transition"]

# Shot patterns for variety — cycle through these per scene index
SHOT_PATTERNS = [
    {"shot_size": "establishing", "camera_movement": "static", "lens_mm": 24, "lighting_key": "natural", "depth_of_field": "deep", "color_temperature": "neutral"},
    {"shot_size": "medium_wide", "camera_movement": "dolly_in", "lens_mm": 35, "lighting_key": "tungsten_warm", "depth_of_field": "medium", "color_temperature": "warm"},
    {"shot_size": "medium_close", "camera_movement": "static", "lens_mm": 50, "lighting_key": "natural", "depth_of_field": "medium", "color_temperature": "warm"},
    {"shot_size": "close_up", "camera_movement": "zoom_in", "lens_mm": 85, "lighting_key": "rim_lit", "depth_of_field": "shallow", "color_temperature": "warm"},
    {"shot_size": "over_shoulder", "camera_movement": "static", "lens_mm": 50, "lighting_key": "tungsten_warm", "depth_of_field": "shallow", "color_temperature": "warm"},
    {"shot_size": "medium", "camera_movement": "pan_right", "lens_mm": 35, "lighting_key": "natural", "depth_of_field": "medium", "color_temperature": "neutral"},
    {"shot_size": "insert", "camera_movement": "static", "lens_mm": 85, "lighting_key": "natural", "depth_of_field": "shallow", "color_temperature": "warm"},
    {"shot_size": "extreme_close_up", "camera_movement": "rack_focus", "lens_mm": 135, "lighting_key": "rim_lit", "depth_of_field": "shallow", "color_temperature": "warm"},
    {"shot_size": "wide", "camera_movement": "tilt_up", "lens_mm": 24, "lighting_key": "golden_hour", "depth_of_field": "deep", "color_temperature": "warm"},
    {"shot_size": "medium_close", "camera_movement": "tracking_right", "lens_mm": 50, "lighting_key": "volumetric", "depth_of_field": "medium", "color_temperature": "mixed"},
]

# Music cue mapping by beat type
MUSIC_CUE_MAP = {
    "opening_hook": "mystery_opening",
    "setup": "warm_first_meeting",
    "inciting_encounter": "warm_first_meeting",
    "rising_attraction": "growing_attraction",
    "complication": "emotional_uncertainty",
    "midpoint_shift": "emotional_uncertainty",
    "emotional_break": "betrayal_or_loss",
    "final_choice": "final_decision",
    "payoff": "romantic_payoff",
    "final_button": "romantic_payoff",
}


def run(engine, payload: dict) -> dict:
    return timed(lambda: _run(engine, payload))


def _run(engine, payload: dict) -> dict:
    script = engine.load_artifact("script")
    bible = engine.load_artifact("story_bible")
    outline = engine.load_artifact("outline")
    if not script or not bible:
        return {"error": "Missing script or story_bible"}

    # Index characters and locations
    chars_by_id = {c["character_id"]: c for c in bible.get("characters", [])}
    locs_by_id = {loc["id"]: loc for loc in bible.get("world", {}).get("locations", [])}

    # Map outline beats to script sections by index
    beats = outline.get("beats", []) if outline else []
    sections = script.get("sections", [])

    all_scenes: list[dict] = []
    cursor = 0.0
    scene_idx = 0

    for sec_idx, section in enumerate(sections):
        beat = beats[sec_idx] if sec_idx < len(beats) else {}
        beat_type = beat.get("beat_type", "emotional_beat")
        section_id = section.get("id", f"s{sec_idx+1}")
        text = section.get("text", "")
        section_start = section.get("start_seconds", cursor)
        section_end = section.get("end_seconds", cursor + 30)
        section_duration = max(3.0, section_end - section_start)

        # Determine number of scenes: 1 scene per 5-7 seconds, min 2, max 3
        # (Capped at 3 for MVP to keep image generation time reasonable)
        n_scenes = max(2, min(3, round(section_duration / 8)))

        # Get characters present in this beat
        chars_present = beat.get("characters_present", [])
        if not chars_present:
            # Default to first 2 characters
            chars_present = list(chars_by_id.keys())[:2]

        # Get location
        loc_id = beat.get("location_id", "")
        loc = locs_by_id.get(loc_id, {})

        # Music cue
        music_cue = MUSIC_CUE_MAP.get(beat_type, "warm_first_meeting")

        # SFX based on location
        sfx = _pick_sfx(loc_id, text)

        # Split text into chunks for image prompts (one per scene)
        text_chunks = _split_text(text, n_scenes)

        for i in range(n_scenes):
            shot = SHOT_PATTERNS[scene_idx % len(SHOT_PATTERNS)]
            scene_dur = section_duration / n_scenes
            scene_start = round(cursor, 2)
            scene_end = round(cursor + scene_dur, 2)

            # Build image prompt: primary character's visual_reference_prompt +
            # location visual_prompt + scene action + lighting
            primary_char = chars_by_id.get(chars_present[0], {}) if chars_present else {}
            char_visual = primary_char.get("visual_reference_prompt", "a person")
            char_negative = primary_char.get("negative_prompt", "")
            loc_visual = loc.get("visual_prompt", "")

            text_chunk = text_chunks[i] if i < len(text_chunks) else text[:200]

            # Get era cues + style modifier from brief metadata
            brief_meta_data = brief_meta(engine.load_artifact("brief"))
            era_cues = brief_meta_data.get("era_visual_cues", "")
            style_mod = brief_meta_data.get("visual_style_modifier", "")
            style_neg = brief_meta_data.get("visual_style_negative", "")

            image_prompt = _build_image_prompt(
                char_visual, loc_visual, text_chunk, shot, beat_type, chars_present, chars_by_id,
                era_cues=era_cues, style_modifier=style_mod
            )

            sc = {
                "id": f"sc{scene_idx+1}",
                "type": "generated",
                "description": text_chunk[:200] if text_chunk else f"{beat_type} scene",
                "start_seconds": scene_start,
                "end_seconds": scene_end,
                "script_section_id": section_id,
                "shot_language": dict(shot),
                "shot_intent": _shot_intent(beat_type, shot["shot_size"]),
                "narrative_role": _narrative_role(beat_type),
                "texture_keywords": _texture_keywords(shot),
                "character_actions": _build_character_actions(chars_present, chars_by_id, beat_type, text_chunk),
                "required_assets": [
                    {"type": "image", "description": f"Scene {scene_idx+1}: {beat_type}", "source": "generate"},
                ],
                "metadata": {
                    "image_prompt": image_prompt,
                    "negative_prompt": (char_negative + ", " + style_neg).strip(", ") if style_neg else char_negative,
                    "music_cue": music_cue,
                    "sfx": sfx,
                    "transition_in": "crossfade" if scene_idx > 0 else "cut",
                    "transition_out": "crossfade",
                    "continuity_refs": chars_present + ([loc_id] if loc_id else []),
                    "estimated_cost_usd": 0.02,
                    "selected_provider": "zai_image",
                    "era": brief_meta_data.get("era", "modern"),
                    "visual_style": brief_meta_data.get("visual_style", "cinematic_realism"),
                },
            }
            all_scenes.append(sc)
            cursor = scene_end
            scene_idx += 1

    shot_sizes = {sc.get("shot_language", {}).get("shot_size") for sc in all_scenes}
    data = {
        "version": "1.0",
        "style_playbook": "cinematic-realism",
        "scenes": all_scenes,
        "metadata": {
            "visual_mode": brief_meta(engine.load_artifact("brief")).get("visual_mode", "economical"),
            "aspect_ratio": brief_meta(engine.load_artifact("brief")).get("output_aspect_ratio", "16:9"),
            "shot_variety_count": len(shot_sizes),
            "beat_errors": [],
            "total_duration": cursor,
            "generation_method": "deterministic",
        },
    }
    engine.log("scene_plan",
               "Scene plan generated (deterministic)",
               scenes=len(all_scenes),
               shot_variety=len(shot_sizes))
    return {
        "artifact": "scene_plan",
        "data": data,
    }


def _split_text(text: str, n: int) -> list[str]:
    """Split text into n roughly equal chunks at sentence boundaries."""
    if not text:
        return [""] * n
    sentences = re.split(r'(?<=[.!?])\s+', text)
    if len(sentences) <= n:
        # Pad with empty strings
        return sentences + [""] * (n - len(sentences))
    chunks = []
    per_chunk = len(sentences) // n
    for i in range(n):
        start = i * per_chunk
        end = (i + 1) * per_chunk if i < n - 1 else len(sentences)
        chunks.append(" ".join(sentences[start:end]))
    return chunks


def _build_image_prompt(char_visual: str, loc_visual: str, text_chunk: str, shot: dict, beat_type: str, chars_present: list, chars_by_id: dict, era_cues: str = "", style_modifier: str = "") -> str:
    """Build a complete image prompt for a scene.

    Includes era visual cues (clothing/architecture/props) and the visual
    style modifier (e.g. 'anime', 'oil_painting', 'caricature') so every
    image matches the selected era and artistic look.
    """
    parts = []
    if loc_visual:
        parts.append(loc_visual)
    parts.append(char_visual)
    # Add secondary character if present
    if len(chars_present) > 1:
        sec_char = chars_by_id.get(chars_present[1], {})
        sec_visual = sec_char.get("visual_reference_prompt", "")
        if sec_visual:
            parts.append(f"with {sec_visual}")
    # Add era visual cues (clothing, architecture, props of the era)
    if era_cues:
        parts.append(f"Era details: {era_cues}")
    if text_chunk:
        # Use a short snippet of the narration as the scene action
        snippet = text_chunk[:150].replace('"', "'")
        parts.append(f"Scene: {snippet}")
    parts.append(f"Shot: {shot['shot_size']}, {shot['camera_movement']}, {shot['lighting_key']} lighting, {shot['depth_of_field']} depth of field, {shot['color_temperature']} color temperature")
    # Add the visual style modifier (e.g. anime, oil_painting, caricature)
    if style_modifier:
        parts.append(style_modifier)
    else:
        parts.append("cinematic realism, warm tones, film grain, anamorphic, high quality")
    return ". ".join(parts)


def _shot_intent(beat_type: str, shot_size: str) -> str:
    """Return the shot intent based on beat type and shot size."""
    if shot_size == "establishing":
        return f"Establish the setting for {beat_type}"
    if shot_size == "close_up":
        return f"Show emotional detail in {beat_type}"
    if shot_size == "over_shoulder":
        return f"Create intimacy during {beat_type}"
    if shot_size == "insert":
        return f"Highlight a meaningful object in {beat_type}"
    return f"Show {beat_type}"


def _narrative_role(beat_type: str) -> str:
    """Map beat type to narrative role."""
    role_map = {
        "opening_hook": "establish_context",
        "setup": "introduce_subject",
        "inciting_encounter": "build_tension",
        "rising_attraction": "emotional_beat",
        "complication": "build_tension",
        "midpoint_shift": "deliver_payload",
        "emotional_break": "emotional_beat",
        "final_choice": "transition",
        "payoff": "resolution",
        "final_button": "resolution",
    }
    return role_map.get(beat_type, "emotional_beat")


def _texture_keywords(shot: dict) -> list[str]:
    """Return texture keywords based on shot parameters."""
    kws = ["cinematic", "film_grain"]
    if shot.get("lighting_key") == "golden_hour":
        kws.append("warm_light")
    elif shot.get("lighting_key") == "rim_lit":
        kws.append("rim_light")
    if shot.get("depth_of_field") == "shallow":
        kws.append("bokeh")
    return kws


def _build_character_actions(chars_present: list, chars_by_id: dict, beat_type: str, text_chunk: str) -> list[dict]:
    """Build character_actions for the scene."""
    actions = []
    for cid in chars_present[:2]:  # max 2 characters per scene
        char = chars_by_id.get(cid, {})
        actions.append({
            "character_id": cid,
            "emotion": _emotion_for_beat(beat_type),
            "action_sequence": [_action_for_beat(beat_type, char.get("full_name", cid))],
        })
    return actions


def _emotion_for_beat(beat_type: str) -> str:
    emotion_map = {
        "opening_hook": "curious",
        "setup": "guarded",
        "inciting_encounter": "surprised",
        "rising_attraction": "drawn_in",
        "complication": "conflicted",
        "midpoint_shift": "shocked",
        "emotional_break": "hurt",
        "final_choice": "determined",
        "payoff": "moved",
        "final_button": "at_peace",
    }
    return emotion_map.get(beat_type, "neutral")


def _action_for_beat(beat_type: str, name: str) -> str:
    action_map = {
        "opening_hook": f"enters the scene",
        "setup": "goes about their routine",
        "inciting_encounter": "notices something unexpected",
        "rising_attraction": "shares a quiet moment",
        "complication": "hesitates, unsure",
        "midpoint_shift": "discovers a hidden truth",
        "emotional_break": "confronts the truth",
        "final_choice": "makes a decision",
        "payoff": "opens up emotionally",
        "final_button": "finds peace",
    }
    return action_map.get(beat_type, "acts")


def _pick_sfx(loc_id: str, text: str) -> list[str]:
    """Pick SFX based on location and text content."""
    sfx = []
    text_lower = text.lower()
    if "diner" in loc_id.lower() or "restaurant" in loc_id.lower():
        sfx.append("restaurant_ambience")
    if "rain" in text_lower:
        sfx.append("rain")
    if "door" in text_lower:
        sfx.append("door")
    if "phone" in text_lower or "text" in text_lower:
        sfx.append("phone_vibration")
    if "street" in loc_id.lower() or "road" in loc_id.lower():
        sfx.append("traffic")
    return sfx[:2]  # max 2 SFX per scene
