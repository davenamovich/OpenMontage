"""Stage 4: Outline.

Calls LLM to break the selected concept into a beat-by-beat outline covering
all 10 required emotional beats, with concrete scene descriptions and word
budgets that sum to the target duration.
"""

from __future__ import annotations

from romance.constants import EMOTIONAL_BEATS
from romance.llm_bridge import zai_available
from romance.stages._shared import ROMANCE_SYSTEM_PROMPT, SAFETY_PROMPT, brief_meta, llm_json, timed


OUTLINE_PROMPT = """You are outlining a YouTube romance episode.

SELECTED CONCEPT:
- Title: {title}
- Logline: {logline}
- Central relationship: {central_relationship}
- Central conflict: {central_conflict}
- Mystery promise: {mystery_promise}
- Midpoint shift: {midpoint_shift}
- Emotional break: {emotional_break}
- Final choice: {final_choice}
- Payoff: {payoff}
- Final button: {final_button}

STORY BIBLE CHARACTERS:
{characters_summary}

TARGET WORD COUNT: {target_word_count} (about {target_duration} seconds at {wpm} WPM)
FORMAT: {format}
SERIALIZED: {serialized}

Create a beat-by-beat outline. Every required beat MUST appear, in order:
- opening_hook (the first spoken line — curiosity/tension/danger/desire/surprise)
- setup (protagonist's wound, want, obstacle; introduce love interest & world)
- inciting_encounter (the meeting/reunion/disruption that starts the story)
- rising_attraction (specific small moments: care, vulnerability, jokes, protection,
  meaningful objects, unspoken attraction — NOT declarations of love)
- complication (a believable barrier: secret/betrayal/family/distance/etc.)
- midpoint_shift (reveal that changes how the relationship is understood)
- emotional_break (separation/confrontation/discovery/sacrifice/apparent loss)
- final_choice (the protagonist's active choice demonstrating emotional change)
- payoff (satisfying emotional reward / reconciliation / bittersweet / twist / cliffhanger)
- final_button (one memorable final line or image)

Each beat must be CONCRETE — describe a specific scene with specific actions
and sensory details, not an abstract summary.

Sprinkle 3-5 retention_beats throughout (NOT in opening_hook or final_button):
new_question, revelation, decision, reversal, emotional_confession, visual_change,
escalation.

Distribute approx_words so they sum to ~{target_word_count}. The opening_hook
should be 30-60 words. The final_button should be 15-40 words.

{serialized_instruction}

Respond with ONLY this JSON shape (no fences, no commentary):
{{
  "version": "1.0",
  "project_id": "{project_id}",
  "title": "{title}",
  "logline": "<1-2 sentence logline>",
  "target_word_count": {target_word_count},
  "target_duration_seconds": {target_duration},
  "beats": [
    {{
      "id": "b1",
      "beat_type": "opening_hook",
      "summary": "<concrete scene description, 2-4 sentences>",
      "characters_present": ["<character_id>", "..."],
      "location_id": "<id from story_bible or new>",
      "emotional_purpose": "<why this beat exists>",
      "approx_words": <int>,
      "retention_beat": "<null or one of new_question|revelation|decision|reversal|emotional_confession|visual_change|escalation>"
    }},
    ... (10 beats total)
  ],
  "metadata": {{}}
}}{SAFETY_PROMPT}
"""


def run(engine, payload: dict) -> dict:
    return timed(lambda: _run(engine, payload))


def _run(engine, payload: dict) -> dict:
    proposal = engine.load_artifact("proposal_packet")
    bible = engine.load_artifact("story_bible")
    if not proposal or not bible:
        return {"error": "Missing proposal_packet or story_bible"}

    brief = engine.load_artifact("brief") or {}
    concept = proposal.get("metadata", {}).get("selected_concept", proposal.get("selected_concept", {}))

    # Build a compact character summary for the prompt
    chars_summary_parts = []
    for c in bible.get("characters", []):
        chars_summary_parts.append(
            f"- {c['character_id']} ({c.get('full_name','')}, {c.get('age','?')}, "
            f"{c.get('role','')}): {c.get('personality',{}).get('summary','')}"
        )
    chars_summary = "\n".join(chars_summary_parts) or "(no characters defined)"

    meta = brief_meta(brief)
    serialized = meta.get("format") == "serialized" or meta.get("number_of_episodes", 1) > 1
    serialized_instruction = (
        "Because this is a SERIALIZED episode, the final_button MUST end on an "
        "unresolved emotional question that creates a compelling reason to watch "
        "the next episode — without feeling randomly cut off."
        if serialized else
        "This is a standalone episode — the final_button should provide emotional closure."
    )

    prompt = OUTLINE_PROMPT.format(
        title=concept.get("title", ""),
        logline=concept.get("logline", ""),
        central_relationship=concept.get("central_relationship", ""),
        central_conflict=concept.get("central_conflict", ""),
        mystery_promise=concept.get("mystery_promise", ""),
        midpoint_shift=concept.get("midpoint_shift", ""),
        emotional_break=concept.get("emotional_break", ""),
        final_choice=concept.get("final_choice", ""),
        payoff=concept.get("payoff", ""),
        final_button=concept.get("final_button", ""),
        characters_summary=chars_summary,
        target_word_count=meta.get("target_word_count", 1500),
        target_duration=brief.get("target_duration_seconds", 540),
        wpm=150,
        format=meta.get("format", "long_form"),
        serialized=serialized,
        serialized_instruction=serialized_instruction,
        project_id=engine.project_id,
        SAFETY_PROMPT=SAFETY_PROMPT,
    )

    if payload.get("outline_override"):
        data = payload["outline_override"]
    elif not zai_available():
        return {"error": "z-ai CLI not available — cannot generate outline."}
    else:
        try:
            data = llm_json(prompt, system=ROMANCE_SYSTEM_PROMPT)
        except Exception as exc:
            return {"error": f"LLM call failed: {exc}"}

    # Validate beat coverage
    present_beats = {b["beat_type"] for b in data.get("beats", [])}
    missing = set(EMOTIONAL_BEATS) - present_beats
    if missing:
        return {"error": f"Outline missing required beats: {sorted(missing)}"}

    # Ensure version + project_id
    data["version"] = "1.0"
    data["project_id"] = engine.project_id
    data["target_word_count"] = meta.get("target_word_count", sum(b.get("approx_words", 0) for b in data["beats"]))
    data["target_duration_seconds"] = brief.get("target_duration_seconds", 540)

    engine.log("outline", "Outline generated",
               beats=len(data["beats"]),
               total_words=sum(b.get("approx_words", 0) for b in data["beats"]))
    return {
        "artifact": "outline",
        "data": data,
    }
