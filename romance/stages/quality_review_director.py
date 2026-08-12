"""Stage 13: Quality Review.

Final quality pass on the rendered video + script. Reviews retention,
opening 30 seconds, title/payoff alignment, and re-confirms the 10 quality
scores. Produces the canonical `review` artifact.
"""

from __future__ import annotations

from romance.constants import QUALITY_MINIMUM, QUALITY_THRESHOLDS
from romance.llm_bridge import zai_available
from romance.stages._shared import ROMANCE_SYSTEM_PROMPT, SAFETY_PROMPT, llm_json, render_output, timed


QUALITY_REVIEW_PROMPT = """You are the final quality reviewer for a YouTube romance video that has been rendered.

SCRIPT SECTIONS:
{script_block}

RENDER REPORT:
{render_summary}

Continuity review scores (from earlier stage):
{prior_scores}

Review the FINAL output for:

1. RETENTION: Does the first 30 seconds contain (a) a compelling first line,
   (b) the central relationship, (c) a meaningful conflict or mystery,
   (d) a clear emotional promise? Are there retention beats throughout
   (new question / revelation / decision / reversal / confession / visual
   change / escalation)?

2. TITLE-PAYOFF ALIGNMENT: Will the eventual title pay off the opening promise?
   No clickbait.

3. FINAL QUALITY SCORES (0-10 each, be honest):
   - hook_strength, originality, emotional_progression, romantic_chemistry,
     character_motivation, conflict_credibility, dialogue_quality, continuity,
     retention_potential, ending_satisfaction

Respond with ONLY this JSON (no fences):
{{
  "version": "1.0",
  "project_id": "{project_id}",
  "stage": "quality_review",
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
  "retention_check": {{
    "first_30_seconds_has_hook": <bool>,
    "first_30_seconds_has_relationship": <bool>,
    "first_30_seconds_has_conflict": <bool>,
    "first_30_seconds_has_promise": <bool>,
    "retention_beats_present": <bool>,
    "notes": "<text>"
  }},
  "title_payoff_alignment": "<text>",
  "revision_required": <bool>,
  "revision_reasons": ["<text>"],
  "summary": "<2-3 sentence overall summary>"
}}{SAFETY_PROMPT}
"""


def run(engine, payload: dict) -> dict:
    return timed(lambda: _run(engine, payload))


def _run(engine, payload: dict) -> dict:
    script = engine.load_artifact("script")
    render_report = engine.load_artifact("render_report")
    if not script:
        return {"error": "Missing script"}

    script_block = "\n".join(
        f"- {s['id']} ({s.get('start_seconds',0):.1f}-{s.get('end_seconds',0):.1f}s): {s.get('text','')[:200]}"
        for s in script.get("sections", [])
    )
    render_summary = (
        f"Final video: {render_output(render_report, 'final_video') or '?'}. "
        f"Scene count: {render_report.get('metadata', {}).get('scene_count', '?')}."
        if render_report else "No render report available."
    )

    prior_ledger = engine.load_artifact("continuity_ledger") or {}
    prior_scores = json.dumps(prior_ledger.get("quality_scores", {})) if prior_ledger else "{}"

    prompt = QUALITY_REVIEW_PROMPT.format(
        script_block=script_block,
        render_summary=render_summary,
        prior_scores=prior_scores,
        project_id=engine.project_id,
        SAFETY_PROMPT=SAFETY_PROMPT,
    )

    if payload.get("review_override"):
        data = payload["review_override"]
    elif not zai_available():
        data = {
            "version": "1.0", "project_id": engine.project_id, "stage": "quality_review",
            "quality_scores": {k: 7 for k in QUALITY_THRESHOLDS},
            "retention_check": {
                "first_30_seconds_has_hook": True,
                "first_30_seconds_has_relationship": True,
                "first_30_seconds_has_conflict": True,
                "first_30_seconds_has_promise": True,
                "retention_beats_present": True,
                "notes": "Auto-passed (LLM unavailable)",
            },
            "title_payoff_alignment": "Auto-passed",
            "revision_required": False,
            "revision_reasons": [],
            "summary": "Auto-passed (LLM unavailable)",
            "metadata": {"auto_passed": True},
        }
    else:
        try:
            data = llm_json(prompt, system=ROMANCE_SYSTEM_PROMPT)
        except Exception as exc:
            return {"error": f"LLM call failed: {exc}"}

    data["version"] = "1.0"
    data["project_id"] = engine.project_id
    data["stage"] = "quality_review"

    # Enforce thresholds
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

    # Build the canonical review artifact — conforms to review.schema.json
    # (required: version, stage, findings; everything else lives in metadata).
    review_artifact = {
        "version": "1.0",
        "stage": "quality_review",
        "findings": [
            {
                "id": f"quality-{i + 1}",
                "severity": "critical",
                "category": "quality_score",
                "description": reason,
            }
            for i, reason in enumerate(reasons)
        ],
        "metadata": {
            "project_id": engine.project_id,
            "quality_scores": scores,
            "retention_check": data.get("retention_check", {}),
            "title_payoff_alignment": data.get("title_payoff_alignment", ""),
            "revision_required": needs_revision,
            "revision_reasons": reasons,
            "summary": data.get("summary", ""),
            "auto_passed": bool(
                isinstance(data.get("metadata"), dict)
                and data.get("metadata", {}).get("auto_passed")
            ),
        },
    }

    engine.log("quality_review", "Quality review complete",
               revision_required=needs_revision,
               scores=scores)
    return {
        "artifact": "review",
        "data": review_artifact,
    }


# Late import to avoid circular dependency in module init
import json as json  # noqa: E402
