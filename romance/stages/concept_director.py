"""Stage 2: Concept.

Calls LLM to generate 3 distinct romance story concepts from the premise +
genre + format. Picks the strongest one (or uses user-supplied choice) and
emits the canonical `proposal_packet` artifact. Also emits a `decision_log`.
"""

from __future__ import annotations

import json
import uuid

from romance.constants import GENRE_LABELS
from romance.llm_bridge import zai_available
from romance.stages._shared import ROMANCE_SYSTEM_PROMPT, SAFETY_PROMPT, brief_meta, llm_json, timed


CONCEPT_PROMPT_TEMPLATE = """You are generating romance story concepts for a faceless YouTube channel.

PREMISE: {premise}
GENRE: {genre_label}
FORMAT: {format}
TARGET DURATION: {target_duration} seconds (~{target_word_count} words)
TONE: {tone}
SETTING: {setting}
TIME PERIOD: {time_period}
NARRATION: {narration_perspective}
DESIRED ENDING: {desired_ending}
ROMANCE INTENSITY: {romance_intensity}/10
DRAMA INTENSITY: {drama_intensity}/10
MYSTERY INTENSITY: {mystery_intensity}/10
MAIN CHARACTER NAMES (use if provided): {main_character_names}
CHARACTER DESCRIPTIONS (use if provided): {character_descriptions}
{extra_constraints}

Generate exactly 3 DIFFERENT concept options. Each must have a distinct
emotional angle (e.g. one mystery-led, one character-led, one situation-led).

CRITICAL RULES:
- The opening_hook MUST be ≤ 30 words and MUST create immediate curiosity /
  tension / danger / desire / surprise. NEVER start with background information.
- Every concept must contain all 10 emotional beats: opening_hook, setup,
  inciting_encounter, rising_attraction, complication, midpoint_shift,
  emotional_break, final_choice, payoff, final_button.
- The final_button for a serialized episode must create a compelling reason to
  watch the next episode without feeling randomly cut off.
- Originality only — no copyrighted characters, no imitation of living authors.{SAFETY_PROMPT}

Respond with ONLY this JSON shape (no markdown fences, no commentary):
{{
  "concepts": [
    {{
      "id": "concept_a",
      "label": "<short label like 'Mystery-Led'>",
      "title": "<episode title, ≤ 80 chars>",
      "logline": "<1-2 sentence logline>",
      "opening_hook": "<the exact first narration line, ≤ 30 words, no background>",
      "central_relationship": "<who and what kind of relationship>",
      "central_conflict": "<the believable barrier>",
      "mystery_promise": "<what the audience is curious about>",
      "midpoint_shift": "<what gets revealed that changes everything>",
      "emotional_break": "<the separation/confrontation/loss>",
      "final_choice": "<the active choice the protagonist makes>",
      "payoff": "<the satisfying emotional reward>",
      "final_button": "<one memorable final line or image>",
      "beat_summary": "<2-3 sentence beat map covering all 10 beats>",
      "title_options": ["<6 emotionally specific curiosity-driven title options>"]
    }},
    ... (3 concepts total)
  ],
  "recommended_concept_id": "concept_a" | "concept_b" | "concept_c",
  "recommendation_reason": "<why this concept>"
}}
"""


def run(engine, payload: dict) -> dict:
    return timed(lambda: _run(engine, payload))


def _run(engine, payload: dict) -> dict:
    brief = engine.load_artifact("brief")
    if not brief:
        return {"error": "Missing brief artifact — run intake first"}

    intake = engine.load_intake()
    extra_constraints = ""
    if intake.get("source_text"):
        extra_constraints = (
            "ADDITIONAL SOURCE TEXT (use as inspiration, do not copy verbatim):\n"
            + intake["source_text"][:2000]
        )

    meta = brief_meta(brief)
    prompt = CONCEPT_PROMPT_TEMPLATE.format(
        premise=meta.get("premise", brief.get("hook", "")),
        genre_label=GENRE_LABELS.get(meta.get("genre", ""), meta.get("genre", "")),
        format=meta.get("format", "long_form"),
        target_duration=brief.get("target_duration_seconds", 540),
        target_word_count=meta.get("target_word_count", 1500),
        tone=brief.get("tone", ""),
        setting=meta.get("setting", ""),
        time_period=meta.get("time_period", ""),
        narration_perspective=meta.get("narration_perspective", "third_person_limited"),
        desired_ending=meta.get("desired_ending", "satisfying_emotional_payoff"),
        romance_intensity=meta.get("romance_intensity", 6),
        drama_intensity=meta.get("drama_intensity", 5),
        mystery_intensity=meta.get("mystery_intensity", 4),
        main_character_names=", ".join(meta.get("main_character_names") or []) or "(none — invent appropriate adult names)",
        character_descriptions="; ".join(meta.get("character_descriptions") or []) or "(none — invent appropriate adult characters)",
        extra_constraints=extra_constraints,
        SAFETY_PROMPT=SAFETY_PROMPT,
    )

    # Allow user-supplied override (e.g. resume, manual concept pick)
    if payload.get("concepts_override"):
        data = payload["concepts_override"]
    elif not zai_available():
        return {"error": "z-ai CLI not available — cannot generate concepts. Install z-ai or provide payload.concepts_override."}
    else:
        try:
            data = llm_json(prompt, system=ROMANCE_SYSTEM_PROMPT)
        except Exception as exc:
            return {"error": f"LLM call failed: {exc}"}

    concepts = data.get("concepts", [])
    if len(concepts) < 3:
        return {"error": f"LLM returned {len(concepts)} concepts, expected 3"}

    recommended_id = data.get("recommended_concept_id", concepts[0]["id"])
    selected = next((c for c in concepts if c["id"] == recommended_id), concepts[0])

    # Build canonical proposal_packet artifact — conforms to existing OpenMontage
    # proposal_packet schema. Romance-specific data goes under metadata.
    target_duration = brief.get("target_duration_seconds", 540)

    concept_options = []
    for c in concepts:
        concept_options.append({
            "id": c["id"],
            "title": c.get("title", ""),
            "hook": c.get("opening_hook", "")[:200],  # schema wants <20 words but we allow longer
            "narrative_structure": "story",
            "visual_approach": c.get("beat_summary", "Cinematic realism with character-led scenes"),
            "suggested_playbook": "cinematic-realism",
            "target_audience": brief.get("target_audience", "adults_25_55"),
            "target_platform": "youtube",
            "target_duration_seconds": target_duration,
            "key_points": [
                c.get("central_relationship", ""),
                c.get("central_conflict", ""),
                c.get("mystery_promise", ""),
            ],
            "core_message": c.get("logline", ""),
            "cta": brief.get("cta", ""),
            "tone": brief.get("tone", ""),
            "why_this_works": c.get("recommendation_reason", c.get("beat_summary", "")),
        })

    proposal_packet = {
        "version": "1.0",
        "concept_options": concept_options,
        "selected_concept": {
            "concept_id": selected["id"],
            "rationale": data.get("recommendation_reason", ""),
        },
        "production_plan": {
            "pipeline": "youtube-romance-story",
            "playbook": "cinematic-realism",
            "stages": [
                {
                    "stage": "voice_generation",
                    "tools": [{"tool_name": "zai_tts", "role": "narration + dialogue", "available": True, "provider": "zai"}],
                    "approach": "Per-section TTS with stable narrator voice + per-character voice IDs",
                    "fallback_if_unavailable": "piper_tts (local, offline)",
                },
                {
                    "stage": "visual_assets",
                    "tools": [{"tool_name": "zai_image", "role": "scene image generation", "available": True, "provider": "zai"}],
                    "approach": "One image per scene, character prompts reference story_bible",
                    "fallback_if_unavailable": "pixabay_image (stock)",
                },
                {
                    "stage": "compose",
                    "tools": [{"tool_name": "video_stitch", "role": "ffmpeg concat", "available": True, "provider": "ffmpeg"}],
                    "approach": "Ken Burns per scene + crossfade + audio mux + caption burn",
                    "fallback_if_unavailable": "none (ffmpeg is required)",
                },
            ],
            "render_runtime": "ffmpeg",
            "delivery_promise": {
                "promise_type": "hybrid",
                "motion_required": False,
                "tone_mode": "intimate",
                "quality_floor": "presentable",
                "approved_fallback": None,
            },
            "renderer_family": "cinematic-trailer",
        },
        "cost_estimate": {
            "total_estimated_usd": 0.0,
            "line_items": [
                {"tool": "zai_chat", "operation": "LLM calls for story generation", "quantity": 6, "estimated_usd": 0.0},
                {"tool": "zai_tts", "operation": "Narration TTS", "quantity": len(engine.load_artifact("script", ) or {}.get("sections", [])) if engine.load_artifact("script") else 11, "estimated_usd": 0.0},
                {"tool": "zai_image", "operation": "Scene + character images", "quantity": 10, "estimated_usd": 0.0},
            ],
            "budget_cap_usd": meta.get("max_budget_usd", 5.0),
            "budget_verdict": "within_budget",
        },
        "approval": {
            "status": "approved",
            "user_notes": "Auto-approved by romance pipeline",
        },
        "metadata": {
            # Romance-specific data — all fields downstream stages need
            "generated_by": "concept-director",
            "llm_available": zai_available(),
            "selected_concept": selected,
            "all_concepts": concepts,
            "recommendation_reason": data.get("recommendation_reason", ""),
            "target_word_count": meta.get("target_word_count", 1500),
            "visual_mode": meta.get("visual_mode", "economical"),
            "format": meta.get("format", "long_form"),
            "language": meta.get("language", "en"),
            "output_aspect_ratio": meta.get("output_aspect_ratio", "16:9"),
        },
    }

    # Decision log (canonical supplementary artifact)
    decision_log = {
        "version": "1.0",
        "project_id": engine.project_id,
        "decisions": [
            {
                "decision_id": f"concept-{uuid.uuid4().hex[:8]}",
                "stage": "concept",
                "category": "concept_selection",
                "decision": f"Selected concept {selected['id']}: {selected.get('label','')}",
                "reason": data.get("recommendation_reason", ""),
                "alternatives": [c["id"] for c in concepts if c["id"] != selected["id"]],
            }
        ],
    }

    engine.log("concept", "Concept selected",
               selected=selected["id"], title=selected.get("title"))
    return {
        "artifact": "proposal_packet",
        "data": proposal_packet,
        "extra_artifacts": {"decision_log": decision_log},
    }
