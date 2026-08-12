"""Stage 15: Thumbnail Generation.

Generates 3 distinct thumbnail concepts per episode. Each concept has:
- Main character expression
- Background, lighting, color contrast, composition
- 2-5 word overlay text
- Image-generation prompt (using story_bible character descriptions)
- Negative prompt

Then generates each thumbnail image and adds the overlay text on top using
PIL (so the text is sharp and accurate — not baked into the AI image).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from romance.llm_bridge import zai_available
from romance.stages._shared import ROMANCE_SYSTEM_PROMPT, SAFETY_PROMPT, get_best_image_tool, llm_json, timed


THUMBNAIL_PROMPT = """You are designing 3 distinct YouTube thumbnail concepts for a romance video.

EPISODE TITLE: {title}
LOGLINE: {logline}
CENTRAL CONFLICT: {central_conflict}
MYSTERY PROMISE: {mystery_promise}

MAIN CHARACTERS:
{characters_block}

For each concept:
- main_character_expression: a specific facial expression
- secondary_element: a secondary character or important object
- background: simple, high-contrast
- lighting: dramatic, eye-catching
- color_contrast: what colors make this pop
- composition: how elements are arranged (rule of thirds, etc.)
- overlay_text: 2-5 words that create curiosity — NOT the title
- image_prompt: full image-gen prompt using the character's visual_reference_prompt
  + this concept's specific expression + background + lighting. The image
  should leave negative space for the overlay text.
- negative_prompt: what to avoid

The thumbnail must be UNDERSTANDABLE ON A PHONE. Big expressions, simple
composition, high contrast.

Respond with ONLY this JSON (no fences):
{{
  "version": "1.0",
  "project_id": "{project_id}",
  "concepts": [
    {{
      "id": "thumb_a",
      "main_character_expression": "<text>",
      "secondary_element": "<text>",
      "background": "<text>",
      "lighting": "<text>",
      "color_contrast": "<text>",
      "composition": "<text>",
      "overlay_text": "<2-5 words>",
      "image_prompt": "<full prompt>",
      "negative_prompt": "<text>"
    }},
    ... (3 concepts total)
  ]
}}{SAFETY_PROMPT}
"""


def run(engine, payload: dict) -> dict:
    return timed(lambda: _run(engine, payload))


def _run(engine, payload: dict) -> dict:
    proposal = engine.load_artifact("proposal_packet")
    bible = engine.load_artifact("story_bible")
    if not proposal or not bible:
        return {"error": "Missing proposal_packet or story_bible"}

    concept = proposal.get("metadata", {}).get("selected_concept", proposal.get("selected_concept", {}))
    chars_block = "\n".join(
        f"- {c['character_id']} ({c.get('full_name','')}): "
        f"visual_reference_prompt = \"{c.get('visual_reference_prompt','')}\""
        for c in bible.get("characters", [])
    )

    if payload.get("thumbnail_override"):
        data = payload["thumbnail_override"]
    elif not zai_available():
        return {"error": "z-ai CLI not available — cannot generate thumbnail concepts."}
    else:
        try:
            data = llm_json(
                THUMBNAIL_PROMPT.format(
                    title=concept.get("title", ""),
                    logline=concept.get("logline", ""),
                    central_conflict=concept.get("central_conflict", ""),
                    mystery_promise=concept.get("mystery_promise", ""),
                    characters_block=chars_block,
                    project_id=engine.project_id,
                    SAFETY_PROMPT=SAFETY_PROMPT,
                ),
                system=ROMANCE_SYSTEM_PROMPT,
            )
        except Exception as exc:
            return {"error": f"LLM call failed: {exc}"}

    data["version"] = "1.0"
    data["project_id"] = engine.project_id
    concepts = data.get("concepts", [])
    if len(concepts) < 3:
        return {"error": f"Expected 3 thumbnail concepts, got {len(concepts)}"}

    # Generate each thumbnail image and add overlay text
    image_tool, _ = get_best_image_tool()
    if image_tool is None:
        return {"error": "No image generation tool available. Install ComfyUI (local) or z-ai CLI."}

    for c in concepts:
        out_path = engine.asset_path("thumbnails", f"{c['id']}.png")
        if not (out_path.exists() and out_path.stat().st_size > 0):
            result = image_tool.execute({
                "prompt": c["image_prompt"],
                "negative_prompt": c["negative_prompt"],
                "output_path": str(out_path),
                "aspect_ratio": "16:9",
                "size": "1344x768",
            })
            if not result.success:
                engine.log("thumbnail_generation", f"Image gen failed for {c['id']}: {result.error}")
                continue
        c["rendered_image_path"] = str(out_path)
        # Add overlay text using PIL
        _add_overlay_text(out_path, c.get("overlay_text", ""))

    engine.log("thumbnail_generation",
               "Thumbnail concepts generated",
               count=len(concepts))
    return {
        "artifact": "thumbnail_concept",
        "data": data,
    }


def _add_overlay_text(image_path: Path, text: str) -> None:
    """Add large overlay text to a thumbnail image using PIL."""
    if not text:
        return
    try:
        from PIL import Image, ImageDraw, ImageFont
        img = Image.open(image_path).convert("RGB")
        draw = ImageDraw.Draw(img)
        # Use a heavy font if available
        font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        try:
            font = ImageFont.truetype(font_path, 80)
        except Exception:
            font = ImageFont.load_default()
        # Position: lower-third, left-aligned
        x = 60
        y = img.height - 200
        # Draw text with thick black outline + white fill
        for dx, dy in [(-3,0),(3,0),(0,-3),(0,3),(-3,-3),(3,3),(-3,3),(3,-3)]:
            draw.text((x+dx, y+dy), text, fill="black", font=font)
        draw.text((x, y), text, fill="white", font=font)
        img.save(image_path)
    except Exception as exc:
        # Non-fatal — the image is still there without overlay
        pass
