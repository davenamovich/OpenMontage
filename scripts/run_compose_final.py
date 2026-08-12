#!/usr/bin/env python3
"""Run the final compose steps: mix audio, mux, captions, burn.

Assumes clean-video.mp4 and full-narration.wav already exist.
"""

from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from romance.engine import RomanceEngine
from romance.stages.compose_director import (
    _mix_audio, _mux_av, _write_captions, _burn_captions, _ffprobe,
)


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main(project_dir: str) -> int:
    engine = RomanceEngine(project_dir)
    manifest = engine.load_artifact("asset_manifest")
    sp = engine.load_artifact("scene_plan")
    script = engine.load_artifact("script")

    # Paths
    clean_video = engine.project_dir / "renders" / "clean-video.mp4"
    narration_path = engine.asset_path("voice", "full-narration.wav")
    final_audio = engine.asset_path("voice", "final-mix.wav")
    final_video = engine.project_dir / "renders" / "youtube-16x9.mp4"
    srt_path = engine.project_dir / "assets" / "captions" / "captions.srt"
    vtt_path = engine.project_dir / "assets" / "captions" / "captions.vtt"

    log(f"clean_video exists: {clean_video.exists()}")
    log(f"narration exists: {narration_path.exists()}")

    # Step 4: mix narration + music
    music_paths = {a["cue"]: a["path"] for a in manifest.get("assets", []) if a.get("type") == "music_track"}
    music_path = None
    for cue in ["warm_first_meeting", "growing_attraction", "romantic_payoff", "mystery_opening"]:
        if cue in music_paths:
            music_path = music_paths[cue]
            break
    if not music_path and music_paths:
        music_path = next(iter(music_paths.values()))

    total_dur = sp["scenes"][-1].get("end_seconds", 60)
    log(f"Step 4: mixing audio (total_dur={total_dur})...")
    ok = _mix_audio(narration_path, music_path, final_audio, total_dur)
    if not ok:
        shutil.copy(narration_path, final_audio)
    log(f"  final mix: {final_audio.exists()}, size={final_audio.stat().st_size if final_audio.exists() else 0}")

    # Step 5: mux
    log("Step 5: muxing video + audio...")
    ok = _mux_av(clean_video, final_audio, final_video)
    log(f"  mux: {ok}, size={final_video.stat().st_size if final_video.exists() else 0}")

    # Step 6: captions
    log("Step 6: generating captions...")
    _write_captions(script, srt_path, "srt")
    _write_captions(script, vtt_path, "vtt")
    log(f"  srt: {srt_path.exists()}, vtt: {vtt_path.exists()}")

    # Step 7: burn captions
    log("Step 7: burning captions...")
    captioned = final_video.with_suffix(".captioned.mp4")
    ok = _burn_captions(final_video, srt_path, captioned)
    if ok:
        shutil.move(str(captioned), str(final_video))
        log(f"  captions burned, size={final_video.stat().st_size}")
    else:
        log("  caption burn failed — keeping non-captioned version")

    # ffprobe
    info = _ffprobe(final_video)
    if info:
        log(f"Final video duration: {info.get('format',{}).get('duration','?')}s")

    # Save render_report + final_review artifacts
    scene_clips = []
    for a in manifest.get("assets", []):
        if a.get("type") == "scene_image":
            scene_clips.append({"scene_id": a["scene_id"], "path": a.get("path", "")})

    render_report = {
        "version": "1.0",
        "project_id": engine.project_id,
        "outputs": {
            "final_video": str(final_video),
            "clean_video": str(clean_video),
            "srt": str(srt_path),
            "vtt": str(vtt_path),
        },
        "video_info": info,
        "scene_clips": scene_clips,
        "narration_path": str(narration_path),
        "music_path": music_path,
        "metadata": {
            "stage": "compose",
            "width": 1280,
            "height": 720,
            "aspect_ratio": "16:9",
            "scene_count": len(scene_clips),
        },
    }
    final_review = {
        "version": "1.0",
        "project_id": engine.project_id,
        "stage": "compose",
        "summary": f"Composed {len(scene_clips)} scenes into youtube-16x9.mp4.",
        "checks": {
            "video_plays": info is not None,
            "narration_present": narration_path.exists(),
            "music_present": music_path is not None,
            "captions_present": srt_path.exists(),
        },
    }
    engine.save_artifact("render_report", render_report)
    engine.save_artifact("final_review", final_review)
    engine.log("compose", "Compose complete", video=str(final_video), scenes=len(scene_clips))
    log(f"\nCompose complete! Final video: {final_video}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "projects/emma-a-34-year-old-waitress-rebuilding-her-life-after-a-pain"))
