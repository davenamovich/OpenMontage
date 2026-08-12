#!/usr/bin/env python3
"""Run the compose stage in the background, logging progress to a file.

This script survives tool-call timeouts by running detached. The parent
process can poll the log file to check progress.

Usage: nohup python3 scripts/run_compose_bg.py projects/<slug> > /tmp/compose.log 2>&1 &
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from romance.engine import RomanceEngine
from romance.stages.compose_director import (
    _ken_burns, _stitch_clips, _concat_audio, _mix_audio, _mux_av,
    _write_captions, _burn_captions, _ffprobe, _silence,
)


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main(project_dir: str) -> int:
    engine = RomanceEngine(project_dir)
    log(f"Starting compose for {engine.project_id}")

    sp = engine.load_artifact("scene_plan")
    manifest = engine.load_artifact("asset_manifest")
    script = engine.load_artifact("script")
    if not sp or not manifest or not script:
        log("ERROR: Missing scene_plan, asset_manifest, or script")
        return 1

    # Index assets
    scene_images: dict[str, str] = {}
    section_audios: list[dict] = []
    music_paths: dict[str, str] = {}
    for a in manifest.get("assets", []):
        if a.get("type") == "scene_image":
            scene_images[a["scene_id"]] = a["path"]
        elif a.get("type") == "section_audio":
            section_audios.append(a)
        elif a.get("type") == "music_track":
            music_paths[a["cue"]] = a["path"]
    section_audios.sort(key=lambda x: x.get("start_seconds", 0))

    log(f"Found {len(scene_images)} scene images, {len(section_audios)} section audios, {len(music_paths)} music tracks")

    width, height = 1280, 720  # 720p for faster encoding
    out_name = "youtube-16x9.mp4"

    # Step 1: Build Ken Burns clips
    scenes = sp.get("scenes", [])
    scene_clips: list[dict] = []
    for i, sc in enumerate(scenes):
        sid = sc["id"]
        img = scene_images.get(sid)
        if not img or not Path(img).exists():
            log(f"  {sid}: no image — skipping")
            continue
        # Cap scene duration at 12s for faster encoding
        raw_duration = max(1.0, sc.get("end_seconds", 0) - sc.get("start_seconds", 0))
        duration = min(raw_duration, 12.0)
        clip_path = engine.asset_path("video", f"scene-{sid}.mp4")
        if clip_path.exists() and clip_path.stat().st_size > 0:
            log(f"  [{i+1}/{len(scenes)}] {sid}: cached ({duration:.1f}s)")
            scene_clips.append({"scene_id": sid, "path": str(clip_path), "duration": duration})
            continue
        ok = _ken_burns(img, clip_path, duration, width, height, sc.get("shot_language", {}))
        if ok:
            scene_clips.append({"scene_id": sid, "path": str(clip_path), "duration": duration})
            log(f"  [{i+1}/{len(scenes)}] {sid}: Ken Burns OK ({duration:.1f}s)")
        else:
            log(f"  [{i+1}/{len(scenes)}] {sid}: Ken Burns FAILED")

    log(f"Step 1 done: {len(scene_clips)} clips")
    if not scene_clips:
        log("ERROR: No scene clips generated")
        return 1

    # Step 2: Stitch clips
    clean_video = engine.project_dir / "renders" / "clean-video.mp4"
    log("Step 2: stitching clips...")
    ok = _stitch_clips([c["path"] for c in scene_clips], clean_video, width, height)
    if not ok:
        log("ERROR: Failed to stitch clips")
        return 1
    log(f"Step 2 done: {clean_video}")

    # Step 3: Build full narration audio
    narration_path = engine.asset_path("voice", "full-narration.wav")
    log("Step 3: concatenating narration...")
    ok = _concat_audio([a["path"] for a in section_audios], narration_path)
    if not ok:
        log("Step 3: _concat_audio failed, using silence")
        _silence(narration_path, sp, scenes)
    log(f"Step 3 done: {narration_path}")

    # Step 4: Mix narration + music
    music_path = None
    if music_paths:
        preferred_order = ["warm_first_meeting", "growing_attraction", "romantic_payoff", "mystery_opening"]
        for cue in preferred_order:
            if cue in music_paths:
                music_path = music_paths[cue]
                break
        if not music_path:
            music_path = next(iter(music_paths.values()))

    final_audio = engine.asset_path("voice", "final-mix.wav")
    log("Step 4: mixing audio...")
    total_dur = scenes[-1].get("end_seconds", 60)
    ok = _mix_audio(narration_path, music_path, final_audio, total_dur)
    if not ok:
        import shutil
        shutil.copy(narration_path, final_audio)
    log(f"Step 4 done: {final_audio}")

    # Step 5: Mux video + audio
    final_video = engine.project_dir / "renders" / out_name
    log("Step 5: muxing video + audio...")
    ok = _mux_av(clean_video, final_audio, final_video)
    if not ok:
        log("ERROR: Failed to mux audio + video")
        return 1
    log(f"Step 5 done: {final_video}")

    # Step 6: Generate captions
    srt_path = engine.project_dir / "assets" / "captions" / "captions.srt"
    vtt_path = engine.project_dir / "assets" / "captions" / "captions.vtt"
    log("Step 6: generating captions...")
    _write_captions(script, srt_path, "srt")
    _write_captions(script, vtt_path, "vtt")
    log(f"Step 6 done: {srt_path}, {vtt_path}")

    # Step 7: Burn captions
    log("Step 7: burning captions...")
    captioned = final_video.with_suffix(".captioned.mp4")
    ok = _burn_captions(final_video, srt_path, captioned)
    if ok:
        import shutil
        shutil.move(str(captioned), str(final_video))
        log(f"Step 7 done: captions burned into {final_video}")
    else:
        log("Step 7: caption burn failed — keeping non-captioned version")

    # Build render_report artifact
    ffprobe_info = _ffprobe(final_video)
    render_report = {
        "version": "1.0",
        "project_id": engine.project_id,
        "outputs": {
            "final_video": str(final_video),
            "clean_video": str(clean_video),
            "srt": str(srt_path),
            "vtt": str(vtt_path),
        },
        "video_info": ffprobe_info,
        "scene_clips": scene_clips,
        "narration_path": str(narration_path),
        "music_path": music_path,
        "metadata": {
            "stage": "compose",
            "width": width,
            "height": height,
            "aspect_ratio": "16:9",
            "scene_count": len(scene_clips),
        },
    }
    final_review = {
        "version": "1.0",
        "project_id": engine.project_id,
        "stage": "compose",
        "summary": f"Composed {len(scene_clips)} scenes into {out_name}.",
        "checks": {
            "video_plays": ffprobe_info is not None,
            "narration_present": narration_path.exists(),
            "music_present": music_path is not None,
            "captions_present": srt_path.exists(),
        },
    }
    engine.save_artifact("render_report", render_report)
    engine.save_artifact("final_review", final_review)
    engine.log("compose", "Compose complete", video=str(final_video), scenes=len(scene_clips))
    log(f"\nCompose complete! Final video: {final_video}")
    log(f"Duration: {ffprobe_info.get('format',{}).get('duration','?')}s" if ffprobe_info else "")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "projects/emma-a-34-year-old-waitress-rebuilding-her-life-after-a-pain"))
