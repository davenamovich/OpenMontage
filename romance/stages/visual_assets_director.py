"""Stage 9: Visual Assets.

Generates one image per scene using z-ai image. Each scene's image_prompt
references the character's stable visual_reference_prompt (so characters stay
visually consistent) plus the scene's specific action, lighting, composition.

Rate limiting: adds a 3-second delay between image generation calls to avoid
HTTP 429 from the z-ai API. On 429, retries with exponential backoff.
"""

from __future__ import annotations

import time
from pathlib import Path

from romance.stages._shared import brief_meta, get_best_image_tool, timed


def run(engine, payload: dict) -> dict:
    return timed(lambda: _run(engine, payload))


def _run(engine, payload: dict) -> dict:
    scene_plan = engine.load_artifact("scene_plan")
    bible = engine.load_artifact("story_bible")
    if not scene_plan or not bible:
        return {"error": "Missing scene_plan or story_bible"}

    image_tool, provider_name = get_best_image_tool()
    if image_tool is None:
        return {"error": "No image generation tool available. Install ComfyUI (local) or z-ai CLI."}

    # Index characters by id for quick prompt lookup
    chars_by_id = {c["character_id"]: c for c in bible.get("characters", [])}
    # Index locations
    locs_by_id = {loc["id"]: loc for loc in bible.get("world", {}).get("locations", [])}

    # Load existing manifest (so we extend character_assets entries)
    manifest = engine.load_artifact("asset_manifest") or {
        "version": "1.0", "project_id": engine.project_id, "assets": [],
    }
    assets = manifest.get("assets", [])
    # Remove existing scene_image entries — we regenerate them
    assets = [a for a in assets if a.get("type") != "scene_image"]
    # Index by scene_id for resume support
    generated_by_scene: dict[str, dict] = {}

    brief = engine.load_artifact("brief") or {}
    aspect = brief_meta(brief).get("output_aspect_ratio", "16:9")

    scenes = scene_plan.get("scenes", [])
    results_log = []
    for sc in scenes:
        sid = sc["id"]
        meta = sc.get("metadata", {})
        prompt = meta.get("image_prompt", "")
        if not prompt:
            # Fallback: build a prompt from description + character visual refs
            desc = sc.get("description", "")
            chars_present = []
            for action in sc.get("character_actions", []):
                cid = action.get("character_id")
                if cid and cid in chars_by_id:
                    chars_present.append(chars_by_id[cid].get("visual_reference_prompt", ""))
            loc_id = sc.get("location_id") or sc.get("script_section_id")
            loc_prompt = locs_by_id.get(loc_id, {}).get("visual_prompt", "")
            shot = sc.get("shot_language", {})
            prompt = (
                f"{loc_prompt}. {desc}. " +
                " ".join(chars_present) +
                f" Shot: {shot.get('shot_size','medium')}, "
                f"lighting: {shot.get('lighting_key','natural')}, "
                f"movement: {shot.get('camera_movement','static')}."
            )

        out_path = engine.asset_path("images", f"scene-{sid}.png")

        if out_path.exists() and out_path.stat().st_size > 0:
            entry = {
                "type": "scene_image",
                "scene_id": sid,
                "path": str(out_path),
                "provider": provider_name,
                "prompt": prompt,
                "negative_prompt": meta.get("negative_prompt", ""),
                "start_seconds": sc.get("start_seconds", 0),
                "end_seconds": sc.get("end_seconds", 0),
            }
            assets.append(entry)
            generated_by_scene[sid] = entry
            results_log.append({"scene_id": sid, "path": str(out_path), "skipped": True})
            continue

        try:
            # Retry with exponential backoff on rate limit (429)
            max_retries = 3
            result = None
            for attempt in range(max_retries):
                result = image_tool.execute({
                    "prompt": prompt,
                    "negative_prompt": meta.get("negative_prompt", ""),
                    "output_path": str(out_path),
                    "aspect_ratio": aspect,
                })
                if result.success:
                    break
                # Check if it's a rate limit error
                err_str = str(result.error or "")
                if "429" in err_str or "Too many requests" in err_str:
                    wait_time = 10 * (attempt + 1)  # 10s, 20s, 30s
                    engine.log("visual_assets",
                               f"Rate limited on scene {sid}, waiting {wait_time}s (attempt {attempt+1}/{max_retries})")
                    time.sleep(wait_time)
                    continue
                else:
                    break  # Non-rate-limit error, don't retry
            if not result or not result.success:
                engine.log("visual_assets",
                           f"Image gen failed for scene {sid}: {result.error if result else 'no result'}")
                results_log.append({"scene_id": sid, "error": result.error if result else "no result"})
                continue
        except Exception as exc:
            engine.log("visual_assets",
                       f"Exception for scene {sid}: {exc}")
            results_log.append({"scene_id": sid, "error": str(exc)})
            continue
        # Rate limit: wait between successful generations (only for cloud providers)
        if provider_name != "comfy_image":
            time.sleep(3)
        entry = {
            "type": "scene_image",
            "scene_id": sid,
            "path": str(out_path),
            "provider": provider_name,
            "prompt": prompt,
            "negative_prompt": meta.get("negative_prompt", ""),
            "start_seconds": sc.get("start_seconds", 0),
            "end_seconds": sc.get("end_seconds", 0),
        }
        assets.append(entry)
        generated_by_scene[sid] = entry
        results_log.append({"scene_id": sid, "path": str(out_path)})

    manifest = {
        "version": "1.0",
        "project_id": engine.project_id,
        "assets": assets,
        "metadata": {
            "stage": "visual_assets",
            "scenes_processed": len(results_log),
            "results": results_log,
            "generated_by_scene": generated_by_scene,
        },
    }
    engine.log("visual_assets",
               "Scene images generated",
               count=len(results_log))
    return {
        "artifact": "asset_manifest",
        "data": manifest,
    }
