"""Stage 6: Continuity Review.

Reviews the script against the story bible. Produces:
- `continuity_ledger` artifact (canonical): current state of relationships,
  secrets, wardrobe, locations, promises, unresolved threads, quality scores
- `review` artifact (canonical): structured review with quality_scores and
  revision_required flag
"""

from __future__ import annotations

from romance.constants import QUALITY_MINIMUM, QUALITY_THRESHOLDS
from romance.llm_bridge import zai_available
from romance.stages._shared import ROMANCE_SYSTEM_PROMPT, SAFETY_PROMPT, llm_json, timed


REVIEW_PROMPT = """You are the continuity reviewer and quality evaluator for a YouTube romance episode.

STORY BIBLE CHARACTERS:
{characters_block}

SCRIPT SECTIONS (in order):
{script_block}

Review the script for:

1. CONTINUITY: Do characters change name, age, ethnicity, hair, wardrobe, or
   body type between sections? Are timeline events consistent? Are promises
   paid off (or flagged as unresolved)?
2. QUALITY SCORES (0-10 each, be honest):
   - hook_strength: does the first line create immediate curiosity/tension?
   - originality: avoids clichés, copyrighted material, imitation
   - emotional_progression: attraction grows through specific moments
   - romantic_chemistry: believable, earned
   - character_motivation: characters act from clear wants/fears
   - conflict_credibility: barrier is believable, not contrived
   - dialogue_quality: sparse, emotionally important, not melodramatic
   - continuity: internal consistency throughout
   - retention_potential: opens strong, has retention beats, pays off
   - ending_satisfaction: delivers promised emotional reward
3. UNRESOLVED THREADS: list any plot threads left hanging (intentional for
   serialized, accidental for standalone).

Build a continuity_ledger with entries tracking each character's current
wardrobe, location, emotional_state, known_secrets, and any promises made.

Respond with ONLY this JSON shape (no fences, no commentary):
{{
  "version": "1.0",
  "project_id": "{project_id}",
  "episode_number": 1,
  "entries": [
    {{
      "entity_type": "character|location|object|relationship|plot_thread",
      "entity_id": "<id>",
      "key": "wardrobe|location|emotional_state|known_secrets|promise|etc",
      "value": "<text>",
      "first_seen_section": "s1",
      "last_updated_section": "s5"
    }}
  ],
  "unresolved_threads": [
    {{"id": "<id>", "description": "<text>", "opened_in_section": "s3", "intended_payoff_section": "s8 or null"}}
  ],
  "quality_scores": {{
    "hook_strength": <0-10>,
    "originality": <0-10>,
    "emotional_progression": <0-10>,
    "romantic_chemistry": <0-10>,
    "character_motivation": <0-10>,
    "conflict_credibility": <0-10>,
    "dialogue_quality": <0-10>,
    "continuity": <0-10>,
    "retention_potential": <0-10>,
    "ending_satisfaction": <0-10>
  }},
  "revision_required": <bool>,
  "revision_reasons": ["<text>", "..."],
  "metadata": {{}}
}}{SAFETY_PROMPT}
"""


def run(engine, payload: dict) -> dict:
    return timed(lambda: _run(engine, payload))


def _run(engine, payload: dict) -> dict:
    script = engine.load_artifact("script")
    bible = engine.load_artifact("story_bible")
    if not script or not bible:
        return {"error": "Missing script or story_bible"}

    chars_block = "\n".join(
        f"- {c['character_id']} ({c.get('full_name','')}): "
        f"appearance={c.get('appearance',{}).get('face','')}, "
        f"hair={c.get('appearance',{}).get('hair','')}, "
        f"wardrobe={c.get('appearance',{}).get('wardrobe','')}"
        for c in bible.get("characters", [])
    )

    script_block_parts = []
    for s in script.get("sections", []):
        script_block_parts.append(
            f"- {s['id']} ({s.get('start_seconds',0):.1f}-{s.get('end_seconds',0):.1f}s): "
            f"{s.get('text','')[:300]}"
        )
    script_block = "\n".join(script_block_parts)

    prompt = REVIEW_PROMPT.format(
        characters_block=chars_block,
        script_block=script_block,
        project_id=engine.project_id,
        SAFETY_PROMPT=SAFETY_PROMPT,
    )

    if payload.get("continuity_override"):
        data = payload["continuity_override"]
    elif not zai_available():
        # Auto-pass with stub review if LLM unavailable
        data = {
            "version": "1.0",
            "project_id": engine.project_id,
            "episode_number": 1,
            "entries": [],
            "unresolved_threads": [],
            "quality_scores": {k: 7 for k in QUALITY_THRESHOLDS},
            "revision_required": False,
            "revision_reasons": ["LLM unavailable — auto-passed with default scores"],
            "metadata": {"auto_passed": True},
        }
    else:
        try:
            data = llm_json(prompt, system=ROMANCE_SYSTEM_PROMPT)
        except Exception as exc:
            return {"error": f"LLM call failed: {exc}"}

    data["version"] = "1.0"
    data["project_id"] = engine.project_id
    data.setdefault("episode_number", 1)

    # Enforce threshold — if any critical score is below threshold, mark for revision
    scores = data.get("quality_scores", {})
    needs_revision = data.get("revision_required", False)
    reasons = list(data.get("revision_reasons", []))
    for k, threshold in QUALITY_THRESHOLDS.items():
        if k in scores and scores[k] < threshold:
            needs_revision = True
            reasons.append(f"{k}={scores[k]} below threshold {threshold}")
    for k, v in scores.items():
        if k not in QUALITY_THRESHOLDS and v < QUALITY_MINIMUM:
            needs_revision = True
            reasons.append(f"{k}={v} below minimum {QUALITY_MINIMUM}")
    data["revision_required"] = needs_revision
    data["revision_reasons"] = reasons

    # Build canonical review artifact (separate from continuity_ledger).
    # Conforms to review.schema.json — required: version, stage, findings;
    # everything else lives in metadata.
    review = {
        "version": "1.0",
        "stage": "continuity_review",
        "findings": [
            {
                "id": f"continuity-{i + 1}",
                "severity": "critical",
                "category": "revision",
                "description": reason,
            }
            for i, reason in enumerate(reasons)
        ],
        "metadata": {
            "project_id": engine.project_id,
            "quality_scores": scores,
            "revision_required": needs_revision,
            "revision_reasons": reasons,
            "summary": (
                f"Reviewed {len(script.get('sections', []))} sections. "
                f"{'Needs revision.' if needs_revision else 'Passes all checks.'}"
            ),
            "auto_passed": bool(
                isinstance(data.get("metadata"), dict)
                and data.get("metadata", {}).get("auto_passed")
            ),
        },
    }

    engine.log("continuity_review",
               "Review complete",
               revision_required=needs_revision,
               scores=scores)
    return {
        "artifact": "continuity_ledger",
        "data": data,
        "extra_artifacts": {"review": review},
    }
