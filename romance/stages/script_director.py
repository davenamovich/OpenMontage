"""Stage 5: Script.

Calls LLM to produce the canonical `script` artifact (OpenMontage schema):
timestamped sections with text, speaker directions, and pronunciation guides.
This is the spoken narration — written for performance, not silent reading.
"""

from __future__ import annotations

from romance.llm_bridge import zai_available
from romance.stages._shared import ROMANCE_SYSTEM_PROMPT, SAFETY_PROMPT, brief_meta, llm_json, timed


SCRIPT_PROMPT = """You are writing the spoken narration script for a YouTube romance episode.

OUTLINE BEATS (in order):
{beats_block}

STORY BIBLE CHARACTERS (use their defined speech_style for any dialogue):
{characters_block}

TARGET DURATION: {target_duration} seconds (~{target_word_count} words)
NARRATION PERSPECTIVE: {narration_perspective}
TONE: {tone}
LANGUAGE: {language}

Write the FULL spoken script. Each section maps to one outline beat. Each
section's text is the actual spoken narration (NOT a description). Rules:

- The opening_hook section's text MUST be the first thing the audience hears.
  It must create immediate curiosity / tension / desire / surprise.
  NO background exposition first.
- Write for PERFORMANCE, not silent reading. Use natural rhythm, varied sentence
  length, concrete sensory details, specific actions and objects.
- Dialogue (when used) must be sparse and emotionally important. Mark it clearly
  with speaker_directions like "DANIEL (quietly):" — but keep the narrator's
  voice as the spine.
- Tense and viewpoint MUST stay consistent throughout.
- NO generic AI prose, NO constant rhetorical questions, NO repeating the same
  emotional point, NO instant love without development, NO unearned forgiveness,
  NO sudden plot twists without setup.
- Original only — no copyrighted characters, no imitation of living authors.
- Each section's start_seconds and end_seconds must be plausible given
  approx_words / WPM (150 WPM = 2.5 words/sec). The first section starts at 0.
  Sections are contiguous (end_seconds of one = start_seconds of next).
- Total duration should land near {target_duration} seconds.

For each section, you MAY add:
- speaker_directions: brief stage direction for TTS emphasis/pause
- pronunciation_guides: list of {{"word", "phonetic"}} for unusual proper nouns

Respond with ONLY this JSON shape (no fences, no commentary):
{{
  "version": "1.0",
  "title": "<episode title>",
  "total_duration_seconds": <number, near {target_duration}>,
  "sections": [
    {{
      "id": "s1",
      "label": "Opening Hook",
      "text": "<the actual spoken narration for this section>",
      "start_seconds": 0,
      "end_seconds": <number>,
      "speaker_directions": "<optional stage direction>",
      "pronunciation_guides": [{{"word": "<word>", "phonetic": "<phonetic>"}}]
    }},
    ... (one section per outline beat)
  ],
  "metadata": {{
    "narration_perspective": "{narration_perspective}",
    "language": "{language}"
  }}
}}{SAFETY_PROMPT}
"""


def run(engine, payload: dict) -> dict:
    return timed(lambda: _run(engine, payload))


def _run(engine, payload: dict) -> dict:
    outline = engine.load_artifact("outline")
    bible = engine.load_artifact("story_bible")
    if not outline or not bible:
        return {"error": "Missing outline or story_bible"}
    brief = engine.load_artifact("brief") or {}

    # Build the beats block
    beats_block_parts = []
    for b in outline.get("beats", []):
        chars = ", ".join(b.get("characters_present", [])) or "(none)"
        beats_block_parts.append(
            f"- {b['id']} [{b['beat_type']}] ~{b.get('approx_words',0)} words, "
            f"chars: {chars}, location: {b.get('location_id','?')}\n"
            f"  Summary: {b.get('summary','')}\n"
            f"  Emotional purpose: {b.get('emotional_purpose','')}"
        )
    beats_block = "\n".join(beats_block_parts)

    # Build characters block
    chars_block_parts = []
    for c in bible.get("characters", []):
        voice = c.get("personality", {}).get("speech_style", "")
        chars_block_parts.append(
            f"- {c['character_id']} ({c.get('full_name','')}): speech style = {voice}"
        )
    chars_block = "\n".join(chars_block_parts)

    meta = brief_meta(brief)
    prompt = SCRIPT_PROMPT.format(
        beats_block=beats_block,
        characters_block=chars_block,
        target_duration=brief.get("target_duration_seconds", 540),
        target_word_count=meta.get("target_word_count", 1500),
        narration_perspective=meta.get("narration_perspective", "third_person_limited"),
        tone=brief.get("tone", ""),
        language=meta.get("language", "en"),
        SAFETY_PROMPT=SAFETY_PROMPT,
    )

    if payload.get("script_override"):
        data = payload["script_override"]
    elif not zai_available():
        return {"error": "z-ai CLI not available — cannot generate script."}
    else:
        try:
            data = llm_json(prompt, system=ROMANCE_SYSTEM_PROMPT)
        except Exception as exc:
            return {"error": f"LLM call failed: {exc}"}

    # Validate timestamps are contiguous
    sections = data.get("sections", [])
    if not sections:
        return {"error": "Script has no sections"}

    # Normalize: ensure starts at 0, contiguous
    cursor = 0.0
    for i, s in enumerate(sections):
        s["start_seconds"] = round(cursor, 2)
        if "end_seconds" not in s or s["end_seconds"] <= cursor:
            # Estimate from word count
            word_count = len(s.get("text", "").split())
            s["end_seconds"] = round(cursor + word_count / 2.5, 2)
        cursor = s["end_seconds"]
        s.setdefault("id", f"s{i+1}")

    data["total_duration_seconds"] = round(cursor, 2)
    data["version"] = "1.0"
    # OpenMontage script schema requires title
    data.setdefault("title", outline.get("title", engine.project_id))

    engine.log("script", "Script generated",
               sections=len(sections),
               duration=data["total_duration_seconds"],
               words=sum(len(s.get("text","").split()) for s in sections))
    return {
        "artifact": "script",
        "data": data,
    }
