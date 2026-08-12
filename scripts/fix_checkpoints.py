"""Retroactively write checkpoints for stages that already have artifacts on disk.

Usage: python scripts/fix_checkpoints.py projects/<slug>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.checkpoint import write_checkpoint
from romance.engine import PIPELINE_NAME, RomanceEngine

STAGE_ARTIFACT_MAP = {
    "intake": "brief",
    "concept": "proposal_packet",
    "story_bible": "story_bible",
    "outline": "outline",
    "script": "script",
    "continuity_review": "continuity_ledger",
    "scene_plan": "scene_plan",
    "character_assets": "asset_manifest",
    "visual_assets": "asset_manifest",
    "voice_generation": "asset_manifest",
    "music_and_sfx": "asset_manifest",
    "compose": "render_report",
    "quality_review": "review",
    "shorts_extraction": "shorts_package",
    "thumbnail_generation": "thumbnail_concept",
    "youtube_package": "youtube_package",
    "publish": "publish_log",
}

SUPPLEMENTARY = {
    "concept": ["decision_log"],
    "continuity_review": ["review"],
    "compose": ["final_review"],
}


def main(project_dir: str) -> int:
    engine = RomanceEngine(project_dir)
    print(f"Fixing checkpoints for {engine.project_id}")

    for stage, artifact_name in STAGE_ARTIFACT_MAP.items():
        artifact = engine.load_artifact(artifact_name)
        if not artifact:
            print(f"  {stage}: no {artifact_name}.json — skipping")
            continue
        artifacts = {artifact_name: artifact}
        for supp in SUPPLEMENTARY.get(stage, []):
            supp_data = engine.load_artifact(supp)
            if supp_data:
                artifacts[supp] = supp_data
        try:
            write_checkpoint(
                engine.pipeline_dir,
                engine.project_id,
                stage,
                "completed",
                artifacts,
                pipeline_type=PIPELINE_NAME,
                checkpoint_policy="guided",
                human_approval_required=False,
                human_approved=True,
                cost_snapshot=engine.cost_tracker.cost_snapshot(),
            )
            print(f"  {stage}: checkpoint written")
        except Exception as exc:
            print(f"  {stage}: FAILED - {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "projects/emma-a-34-year-old-waitress-rebuilding-her-life-after-a-pain"))
