"""Stage 3: Story Bible.

Calls LLM to produce the canonical `story_bible` artifact: full character
definitions (face/hair/wardrobe/palette/personality/voice), world, locations,
important objects. Every recurring character gets a stable character_id that
all downstream scene prompts must reference.
"""

from __future__ import annotations

from romance.constants import GENRE_LABELS
from romance.llm_bridge import zai_available
from romance.stages._shared import ROMANCE_SYSTEM_PROMPT, SAFETY_PROMPT, brief_meta, llm_json, timed


STORY_BIBLE_PROMPT = """You are building the canonical Story Bible for a YouTube romance episode.

SELECTED CONCEPT:
- Title: {title}
- Logline: {logline}
- Central relationship: {central_relationship}
- Central conflict: {central_conflict}
- Midpoint shift: {midpoint_shift}
- Final choice: {final_choice}
- Final button: {final_button}

GENRE: {genre_label}
SETTING: {setting}
TIME PERIOD: {time_period}
ERA: {era_label}
ERA VISUAL CUES (clothing, architecture, props of the era): {era_cues}
VISUAL STYLE: {style_label}
STYLE MODIFIER (append to every image prompt): {style_modifier}
NARRATION: {narration_perspective}
MAIN CHARACTER NAMES (use if provided, otherwise invent appropriate adult names): {main_character_names}
CHARACTER DESCRIPTIONS (use if provided): {character_descriptions}
NARRATOR VOICE PREFERENCE: {narrator_voice}
LANGUAGE: {language}

Define EVERY recurring character with stable details. Every character must be
an adult (18+). For each character provide:
- A stable character_id (lowercase snake_case, e.g. "emma_main", "daniel_li")
- Full name, age, role, full appearance (face/hair/build/wardrobe/palette)
- Personality: summary, emotional_wound, desire, fear, contradiction, speech_style
- Relationships to other characters
- visual_reference_prompt: a STABLE prompt used for every image of this character.
  Must include face shape, hair color & style, eye color, skin tone, build,
  typical wardrobe appropriate for the ERA, age, and palette colors.
  MUST END WITH the style modifier: "{style_modifier}"
  Should be reusable across scenes.
- negative_prompt: what to AVOID in image gen (prevents feature drift).
- voice: TTS provider + voice_id. Use "zai_tts" as provider. Voice IDs for
  z-ai are: tongtong (warm female), etc. Pick a distinct voice per character.
  Narrator should be a calm, expressive voice.

Also define the WORLD: setting, time_period, locations (with their own
visual_prompt + negative_prompt), and important_objects.

Respond with ONLY this JSON shape (no fences, no commentary):
{{
  "version": "1.0",
  "project_id": "{project_id}",
  "format": "{format}",
  "genre": "{genre}",
  "tone": "{tone}",
  "characters": [
    {{
      "character_id": "<id>",
      "full_name": "<name>",
      "role": "protagonist | love_interest | supporting | antagonist",
      "age": <int 18+>,
      "appearance": {{
        "face": "<specific>",
        "hair": "<color, length, style>",
        "build": "<body type>",
        "wardrobe": "<typical outfit>",
        "palette": ["#hex", "#hex", "#hex"]
      }},
      "personality": {{
        "summary": "<2-3 sentences>",
        "emotional_wound": "<the past hurt>",
        "desire": "<what they want>",
        "fear": "<what they fear>",
        "contradiction": "<what makes them interesting>",
        "speech_style": "<how they talk>"
      }},
      "relationships": [{{"to_character_id": "<id>", "relation": "<text>"}}],
      "visual_reference_prompt": "<stable image prompt>",
      "negative_prompt": "<what to avoid>",
      "voice": {{
        "provider": "zai_tts",
        "voice_id": "tongtong",
        "speed": 1.0
      }},
      "continuity_notes": "<any notes>"
    }}
  ],
  "world": {{
    "setting": "<text>",
    "time_period": "<text>",
    "locations": [
      {{
        "id": "<id>",
        "name": "<name>",
        "description": "<text>",
        "visual_prompt": "<stable image prompt>",
        "negative_prompt": "<what to avoid>"
      }}
    ],
    "important_objects": [
      {{"id": "<id>", "name": "<name>", "description": "<text>"}}
    ]
  }},
  "metadata": {{}}
}}{SAFETY_PROMPT}
"""


def run(engine, payload: dict) -> dict:
    return timed(lambda: _run(engine, payload))


def _run(engine, payload: dict) -> dict:
    proposal = engine.load_artifact("proposal_packet")
    if not proposal:
        return {"error": "Missing proposal_packet — run concept first"}
    brief = engine.load_artifact("brief") or {}
    intake = engine.load_intake()

    concept = proposal.get("metadata", {}).get("selected_concept", proposal.get("selected_concept", {}))

    meta = brief_meta(brief)
    # Build era + style context for the prompt
    era = meta.get("era", "modern")
    era_label = meta.get("era_label", "Modern")
    era_cues = meta.get("era_visual_cues", "")
    style = meta.get("visual_style", "cinematic_realism")
    style_label = meta.get("visual_style_label", "Cinematic Realism")
    style_mod = meta.get("visual_style_modifier", "")

    prompt = STORY_BIBLE_PROMPT.format(
        title=concept.get("title", ""),
        logline=concept.get("logline", ""),
        central_relationship=concept.get("central_relationship", ""),
        central_conflict=concept.get("central_conflict", ""),
        midpoint_shift=concept.get("midpoint_shift", ""),
        final_choice=concept.get("final_choice", ""),
        final_button=concept.get("final_button", ""),
        genre_label=GENRE_LABELS.get(meta.get("genre", ""), meta.get("genre", "")),
        setting=meta.get("setting", ""),
        time_period=meta.get("time_period", ""),
        era_label=era_label,
        era_cues=era_cues,
        style_label=style_label,
        style_modifier=style_mod,
        narration_perspective=meta.get("narration_perspective", ""),
        main_character_names=", ".join(meta.get("main_character_names") or []) or "(invent appropriate adult names)",
        character_descriptions="; ".join(meta.get("character_descriptions") or []) or "(invent appropriate adult characters)",
        narrator_voice=meta.get("narrator_voice", "warm_female"),
        language=meta.get("language", "en"),
        project_id=engine.project_id,
        format=meta.get("format", "long_form"),
        genre=meta.get("genre", ""),
        tone=brief.get("tone", ""),
        SAFETY_PROMPT=SAFETY_PROMPT,
    )

    if payload.get("story_bible_override"):
        data = payload["story_bible_override"]
    elif not zai_available():
        return {"error": "z-ai CLI not available — cannot generate story bible."}
    else:
        try:
            data = llm_json(prompt, system=ROMANCE_SYSTEM_PROMPT)
        except Exception as exc:
            return {"error": f"LLM call failed: {exc}"}

    # Force-correct project_id and version
    data["project_id"] = engine.project_id
    data["version"] = "1.0"

    # Validate narrator exists
    has_narrator = any(c.get("role") == "protagonist" or "narrator" in c.get("character_id", "").lower()
                       for c in data.get("characters", []))
    if not has_narrator and data.get("characters"):
        # Mark the first character as the narrator viewpoint
        data["characters"][0]["role"] = data["characters"][0].get("role", "protagonist")

    engine.log("story_bible", "Story bible generated",
               characters=len(data.get("characters", [])),
               locations=len(data.get("world", {}).get("locations", [])))
    return {
        "artifact": "story_bible",
        "data": data,
    }
