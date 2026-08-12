"""Generate missing scene images one at a time with rate-limit-aware delays.

Usage: python scripts/gen_missing_images.py projects/<slug>
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from romance.engine import RomanceEngine
from tools.llm.zai_image import ZaiImage


def main(project_dir: str) -> int:
    engine = RomanceEngine(project_dir)
    sp = engine.load_artifact("scene_plan")
    if not sp:
        print("No scene_plan found")
        return 1

    bible = engine.load_artifact("story_bible")
    chars_by_id = {c["character_id"]: c for c in bible.get("characters", [])}
    locs_by_id = {loc["id"]: loc for loc in bible.get("world", {}).get("locations", [])}

    img_dir = engine.project_dir / "assets" / "images"
    existing = {f.stem.replace("scene-", "") for f in img_dir.glob("*.png")}

    missing_scenes = [sc for sc in sp["scenes"] if sc["id"] not in existing]
    print(f"Found {len(missing_scenes)} missing scene images")

    image_tool = ZaiImage()
    if image_tool.get_status().value != "available":
        print("z-ai image not available")
        return 1

    for i, sc in enumerate(missing_scenes):
        sid = sc["id"]
        meta = sc.get("metadata", {})
        prompt = meta.get("image_prompt", "")
        if not prompt:
            print(f"  {sid}: no image_prompt — skipping")
            continue

        out_path = engine.asset_path("images", f"scene-{sid}.png")
        print(f"  [{i+1}/{len(missing_scenes)}] {sid}: generating...", flush=True)

        # Retry with backoff
        success = False
        for attempt in range(4):
            result = image_tool.execute({
                "prompt": prompt,
                "negative_prompt": meta.get("negative_prompt", ""),
                "output_path": str(out_path),
                "aspect_ratio": "16:9",
            })
            if result.success:
                print(f"    OK ({result.duration_seconds:.1f}s)", flush=True)
                success = True
                break
            err = str(result.error or "")
            if "429" in err or "Too many requests" in err:
                wait = 20 * (attempt + 1)
                print(f"    Rate limited, waiting {wait}s...", flush=True)
                time.sleep(wait)
            elif "deadline" in err.lower():
                wait = 15 * (attempt + 1)
                print(f"    Deadline exceeded, waiting {wait}s...", flush=True)
                time.sleep(wait)
            else:
                print(f"    Error: {err[:200]}", flush=True)
                time.sleep(5)

        if not success:
            print(f"    FAILED after 4 attempts", flush=True)

        # Always wait between scenes to avoid rate limiting
        time.sleep(5)

    # Final count
    final = len(list(img_dir.glob("*.png")))
    print(f"\nDone. Total scene images: {final}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "projects/emma-a-34-year-old-waitress-rebuilding-her-life-after-a-pain"))
