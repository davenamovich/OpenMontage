"""Stage 8: Character Assets.

Generates one canonical reference image per character. Uses ComfyUI (local
Stable Diffusion) when available, falling back to z-ai image. These reference
images are reused in every scene that features the character (visual_assets
stage references the character's reference image in its prompts to enforce
consistency).
"""

from __future__ import annotations

import json
from pathlib import Path

from romance.llm_bridge import zai_available
from romance.stages._shared import get_best_image_tool, timed


def run(engine, payload: dict) -> dict:
    return timed(lambda: _run(engine, payload))


def _run(engine, payload: dict) -> dict:
    bible = engine.load_artifact("story_bible")
    scene_plan = engine.load_artifact("scene_plan")
    if not bible:
        return {"error": "Missing story_bible"}

    image_tool, provider_name = get_best_image_tool()
    if image_tool is None:
        return {"error": "No image generation tool available. Install ComfyUI (local) or z-ai CLI."}

    # Load existing asset_manifest if present (so we extend rather than replace)
    existing_manifest = engine.load_artifact("asset_manifest") or {
        "version": "1.0",
        "project_id": engine.project_id,
        "assets": [],
    }
    assets = existing_manifest.get("assets", [])
    # Index by (type, character_id) so we can update existing entries
    by_key = {(a.get("type"), a.get("character_id")): a for a in assets if a.get("character_id")}

    aspect = "1:1"  # character reference images are square
    results_log = []

    for char in bible.get("characters", []):
        cid = char["character_id"]
        prompt = char.get("visual_reference_prompt", "")
        if not prompt:
            continue
        negative = char.get("negative_prompt", "")
        out_path = engine.asset_path("characters", f"{cid}.png")

        # Skip if already generated (resume support)
        if out_path.exists() and out_path.stat().st_size > 0:
            engine.log("character_assets", f"Skipping {cid} (already exists)")
            entry = by_key.get(("character_reference", cid))
            if not entry:
                entry = {
                    "type": "character_reference",
                    "character_id": cid,
                    "path": str(out_path),
                    "provider": provider_name,
                    "prompt": prompt,
                    "negative_prompt": negative,
                }
                assets.append(entry)
                by_key[("character_reference", cid)] = entry
            results_log.append({"character_id": cid, "path": str(out_path), "skipped": True})
            continue

        result = image_tool.execute({
            "prompt": prompt,
            "negative_prompt": negative,
            "output_path": str(out_path),
            "aspect_ratio": aspect,
            "size": "1024x1024",
        })
        if not result.success:
            engine.log("character_assets",
                       f"Image gen failed for {cid}: {result.error}")
            results_log.append({"character_id": cid, "error": result.error})
            continue
        entry = by_key.get(("character_reference", cid))
        if entry:
            entry["path"] = str(out_path)
            entry["prompt"] = prompt
        else:
            entry = {
                "type": "character_reference",
                "character_id": cid,
                "path": str(out_path),
                "provider": provider_name,
                "prompt": prompt,
                "negative_prompt": negative,
            }
            assets.append(entry)
            by_key[("character_reference", cid)] = entry
        results_log.append({"character_id": cid, "path": str(out_path)})

    manifest = {
        "version": "1.0",
        "project_id": engine.project_id,
        "assets": assets,
        "metadata": {
            "stage": "character_assets",
            "characters_processed": len(results_log),
            "results": results_log,
        },
    }
    engine.log("character_assets",
               "Character reference images generated",
               count=len(results_log))
    return {
        "artifact": "asset_manifest",
        "data": manifest,
    }
