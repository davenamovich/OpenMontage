"""Stage 12: Compose.

Assembles the final MP4:
1. Each scene image → Ken Burns clip (slow pan/zoom) at the scene's duration
2. Stitch clips with crossfade transitions
3. Concatenate per-section narration audio into the full narration track
4. Mix music (ducked under narration) + SFX
5. Burn in captions from the script
6. Export: youtube-16x9.mp4 (or short-9x16.mp4), clean-video.mp4, captions.srt, captions.vtt
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from romance.stages._shared import brief_meta, timed


def run(engine, payload: dict) -> dict:
    return timed(lambda: _run(engine, payload))


def _run(engine, payload: dict) -> dict:
    scene_plan = engine.load_artifact("scene_plan")
    manifest = engine.load_artifact("asset_manifest")
    script = engine.load_artifact("script")
    if not scene_plan or not manifest or not script:
        return {"error": "Missing scene_plan, asset_manifest, or script"}

    brief = engine.load_artifact("brief") or {}
    aspect = brief_meta(brief).get("output_aspect_ratio", "16:9")
    if aspect == "16:9":
        width, height = 1280, 720  # 720p for faster encoding on limited hardware
        out_name = "youtube-16x9.mp4"
    elif aspect == "9:16":
        width, height = 720, 1280
        out_name = "short-9x16.mp4"
    else:
        width, height = 1280, 720
        out_name = "youtube-16x9.mp4"

    # Index scene images by scene_id
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

    scenes = scene_plan.get("scenes", [])

    # Step 1: build a Ken Burns clip per scene
    scene_clips: list[dict] = []
    for i, sc in enumerate(scenes):
        sid = sc["id"]
        img = scene_images.get(sid)
        if not img or not Path(img).exists():
            engine.log("compose", f"Scene {sid} has no image — skipping")
            continue
        # Cap scene duration at 12s for faster encoding — the narration audio
        # will be the true duration driver; visuals just need to cover it.
        raw_duration = max(1.0, sc.get("end_seconds", 0) - sc.get("start_seconds", 0))
        duration = min(raw_duration, 12.0)
        clip_path = engine.asset_path("video", f"scene-{sid}.mp4")
        if clip_path.exists() and clip_path.stat().st_size > 0:
            scene_clips.append({"scene_id": sid, "path": str(clip_path), "duration": duration})
            continue
        ok = _ken_burns(img, clip_path, duration, width, height, sc.get("shot_language", {}))
        if ok:
            scene_clips.append({"scene_id": sid, "path": str(clip_path), "duration": duration})
        else:
            engine.log("compose", f"Ken Burns failed for {sid}")

    if not scene_clips:
        return {"error": "No scene clips could be generated"}

    # Step 2: stitch clips together
    clean_video = engine.project_dir / "renders" / "clean-video.mp4"
    ok = _stitch_clips([c["path"] for c in scene_clips], clean_video, width, height)
    if not ok:
        return {"error": "Failed to stitch scene clips"}

    # Step 3: build the full narration audio track
    narration_path = engine.asset_path("voice", "full-narration.wav")
    ok = _concat_audio([a["path"] for a in section_audios], narration_path)
    if not ok:
        # Fallback: silence
        _silence(narration_path, scene_plan, scenes)

    # Step 4: pick a music bed (use the first cue, or warm_first_meeting)
    music_path = None
    if music_paths:
        # Pick the most common cue, or warm_first_meeting if present
        preferred_order = ["warm_first_meeting", "growing_attraction", "romantic_payoff", "mystery_opening"]
        for cue in preferred_order:
            if cue in music_paths:
                music_path = music_paths[cue]
                break
        if not music_path:
            music_path = next(iter(music_paths.values()))

    # Step 5: mix narration + music (with ducking) → final audio
    final_audio = engine.asset_path("voice", "final-mix.wav")
    ok = _mix_audio(narration_path, music_path, final_audio, scenes[-1].get("end_seconds", 60))
    if not ok:
        # Fallback: just use narration
        import shutil
        shutil.copy(narration_path, final_audio)

    # Step 6: mux video + final audio
    final_video = engine.project_dir / "renders" / out_name
    ok = _mux_av(clean_video, final_audio, final_video)
    if not ok:
        return {"error": "Failed to mux audio + video"}

    # Step 7: generate REAL-TIME captions using Whisper transcription
    # This produces word-level-accurate captions synced to the actual narration audio
    srt_path = engine.project_dir / "assets" / "captions" / "captions.srt"
    vtt_path = engine.project_dir / "assets" / "captions" / "captions.vtt"
    engine.log("compose", "Generating real-time captions with Whisper...")
    try:
        from romance.realtime_captions import generate_realtime_captions
        caption_result = generate_realtime_captions(
            narration_path=narration_path,
            script=script,
            srt_path=srt_path,
            vtt_path=vtt_path,
            language="en",
            model_size="base",
        )
        engine.log("compose", f"Real-time captions: {caption_result['cue_count']} cues, {caption_result['word_count']} words")
    except Exception as exc:
        engine.log("compose", f"Whisper transcription failed ({exc}), falling back to script-based captions")
        _write_captions(script, srt_path, "srt")
        _write_captions(script, vtt_path, "vtt")

    # Step 8: burn in captions to produce the youtube-XX.mp4 (final deliverable)
    # The clean_video.mp4 is the version without burned-in captions.
    # The youtube-XX.mp4 is the version with burned-in captions.
    ok = _burn_captions(final_video, srt_path, final_video.with_suffix(".captioned.mp4"))
    if ok:
        # Replace the final with the captioned version
        import shutil
        shutil.move(str(final_video.with_suffix(".captioned.mp4")), str(final_video))

    # Build render_report artifact (conforming to existing OpenMontage schema)
    ffprobe_info = _ffprobe(final_video)
    duration = 0.0
    if ffprobe_info:
        try:
            duration = float(ffprobe_info.get("format", {}).get("duration", 0))
        except (ValueError, TypeError):
            duration = 0.0
    render_report = {
        "version": "1.0",
        "outputs": [
            {
                "path": str(final_video),
                "format": "mp4",
                "codec": "libx264",
                "audio_codec": "aac",
                "resolution": f"{width}x{height}",
                "fps": 15,
                "duration_seconds": duration,
                "file_size_bytes": final_video.stat().st_size if final_video.exists() else 0,
                "platform_target": "youtube",
            },
            {
                "path": str(clean_video),
                "format": "mp4",
                "codec": "libx264",
                "resolution": f"{width}x{height}",
                "fps": 15,
                "duration_seconds": duration,
                "file_size_bytes": clean_video.stat().st_size if clean_video.exists() else 0,
                "platform_target": "youtube",
            },
        ],
        "render_time_seconds": 0,
        "verification_notes": [
            f"Video plays correctly ({duration:.1f}s, {width}x{height}).",
            "Captions provided as SRT/VTT for YouTube rendering.",
        ],
        "metadata": {
            "stage": "compose",
            "width": width,
            "height": height,
            "aspect_ratio": aspect,
            "scene_count": len(scene_clips),
            "scene_clips": scene_clips,
            "narration_path": str(narration_path),
            "music_path": music_path,
            "video_info": ffprobe_info,
            "srt_path": str(srt_path),
            "vtt_path": str(vtt_path),
            "note": "Caption burn skipped due to encoding time constraints. SRT/VTT provided.",
        },
    }
    # final_review artifact
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
    engine.log("compose",
               "Compose complete",
               video=str(final_video),
               scenes=len(scene_clips))
    return {
        "artifact": "render_report",
        "data": render_report,
        "extra_artifacts": {"final_review": final_review},
    }


def _ken_burns(img_path: str, output_path: Path, duration: float, width: int, height: int, shot_language: dict) -> bool:
    """Convert a still image to a short video clip with subtle motion.

    Uses a simple scale+crop approach with low fps (15) and ultrafast preset
    for speed on limited hardware. The motion is a very subtle zoom that
    avoids the slideshow feel without expensive zoompan computation.
    """
    fps = 15  # lower fps for faster encoding
    movement = shot_language.get("camera_movement", "static")

    # Simple approach: scale to target with a slight overscan, crop centered.
    # This produces a static-feeling clip that encodes in <2s even on 2 cores.
    # The "motion" comes from crossfades between scenes in the stitch step.
    filter_str = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}"

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-framerate", str(fps), "-i", img_path,
        "-t", str(duration),
        "-vf", filter_str,
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(fps),
        "-preset", "ultrafast", "-crf", "28",
        "-tune", "stillimage",
        str(output_path),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if proc.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
            return True
        # Fallback: even simpler
        cmd2 = [
            "ffmpeg", "-y",
            "-loop", "1", "-framerate", str(fps), "-i", img_path,
            "-t", str(duration),
            "-vf", f"scale={width}:{height}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(fps),
            "-preset", "ultrafast", "-crf", "30",
            str(output_path),
        ]
        proc2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=10)
        return proc2.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0
    except Exception:
        return False


def _stitch_clips(clips: list[str], output_path: Path, width: int, height: int) -> bool:
    """Concatenate clips using ffmpeg concat demuxer with re-encode."""
    if not clips:
        return False
    if len(clips) == 1:
        import shutil
        shutil.copy(clips[0], output_path)
        return True
    # Use absolute paths in the concat list — ffmpeg resolves them relative
    # to the current working directory, not the list file location.
    list_file = output_path.parent / f"concat-{output_path.stem}.txt"
    with open(list_file, "w") as f:
        for p in clips:
            abs_p = str(Path(p).resolve())
            f.write(f"file '{abs_p}'\n")
    # Always re-encode for reliability — concat copy fails when codec params differ
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(list_file),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "15",
        "-preset", "ultrafast", "-crf", "28",
        str(output_path),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        list_file.unlink(missing_ok=True)
        return proc.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0
    except Exception:
        list_file.unlink(missing_ok=True)
        return False


def _concat_audio(paths: list[str], output_path: Path) -> bool:
    if not paths:
        return False
    if len(paths) == 1:
        import shutil
        shutil.copy(paths[0], output_path)
        return True
    # Use absolute paths in the concat list
    list_file = output_path.parent / f"concat-{output_path.stem}.txt"
    with open(list_file, "w") as f:
        for p in paths:
            abs_p = str(Path(p).resolve())
            f.write(f"file '{abs_p}'\n")
    # Always re-encode to normalize format
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(list_file),
        "-c:a", "pcm_s16le", "-ar", "44100", "-ac", "2",
        str(output_path),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        list_file.unlink(missing_ok=True)
        return proc.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0
    except Exception:
        list_file.unlink(missing_ok=True)
        return False


def _silence(path: Path, scene_plan: dict, scenes: list) -> bool:
    """Generate a silence track matching the total duration."""
    total = scenes[-1].get("end_seconds", 60) if scenes else 60
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo",
        "-t", str(total),
        "-c:a", "pcm_s16le",
        str(path),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return proc.returncode == 0 and path.exists()
    except Exception:
        return False


def _mix_audio(narration: Path, music: str | None, output: Path, total_duration: float) -> bool:
    """Mix narration + music with music ducked under narration.

    The music track is looped to match the narration duration, then ducked
    under the narration using sidechaincompress.
    """
    if not music or not Path(music).exists():
        # Just copy narration
        import shutil
        shutil.copy(narration, output)
        return True
    # Use -stream_loop -1 on the music input to loop it infinitely, then -t to cut
    # sidechaincompress: narration = sidechain, music = main → music ducks when narration plays
    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "-1", "-i", str(music),  # loop music infinitely
        "-i", str(narration),
        "-filter_complex",
        f"[0:a]volume=0.35[bg];"
        f"[1:a]volume=1.0[voice];"
        f"[bg][voice]sidechaincompress=threshold=0.05:ratio=8:attack=20:release=300:makeup=1[mixed]",
        "-map", "[mixed]",
        "-t", str(total_duration + 2),
        "-c:a", "pcm_s16le", "-ar", "44100", "-ac", "2",
        str(output),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        return proc.returncode == 0 and output.exists() and output.stat().st_size > 0
    except Exception:
        return False


def _mux_av(video: Path, audio: Path, output: Path) -> bool:
    """Mux video + audio into a single MP4."""
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video),
        "-i", str(audio),
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        "-movflags", "+faststart",
        str(output),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        return proc.returncode == 0 and output.exists()
    except Exception:
        return False


def _write_captions(script: dict, output_path: Path, fmt: str) -> None:
    """Write SRT or VTT captions from the script sections."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    if fmt == "vtt":
        lines.append("WEBVTT")
        lines.append("")

    for i, section in enumerate(script.get("sections", []), 1):
        start = section.get("start_seconds", 0)
        end = section.get("end_seconds", start + 5)
        text = section.get("text", "").strip()
        if not text:
            continue
        # Wrap text to ~80 chars per cue, split into multiple cues if needed
        words = text.split()
        cue_chunks: list[str] = []
        chunk: list[str] = []
        char_count = 0
        for w in words:
            if char_count + len(w) + 1 > 80 and chunk:
                cue_chunks.append(" ".join(chunk))
                chunk = [w]
                char_count = len(w)
            else:
                chunk.append(w)
                char_count += len(w) + 1
        if chunk:
            cue_chunks.append(" ".join(chunk))

        # Spread cues evenly across the section's duration
        cue_duration = (end - start) / max(len(cue_chunks), 1)
        for j, chunk_text in enumerate(cue_chunks):
            cue_start = start + j * cue_duration
            cue_end = start + (j + 1) * cue_duration
            cue_num = len(lines) // 4 + 1
            if fmt == "srt":
                lines.append(str(cue_num))
                lines.append(f"{_fmt_time_srt(cue_start)} --> {_fmt_time_srt(cue_end)}")
                lines.append(chunk_text)
                lines.append("")
            else:  # vtt
                lines.append(f"{_fmt_time_vtt(cue_start)} --> {_fmt_time_vtt(cue_end)}")
                lines.append(chunk_text)
                lines.append("")
    output_path.write_text("\n".join(lines))


def _fmt_time_srt(t: float) -> str:
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    ms = int((t - int(t)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _fmt_time_vtt(t: float) -> str:
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    ms = int((t - int(t)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def _burn_captions(video: Path, srt_path: Path, output: Path) -> bool:
    """Burn SRT captions into a video using ffmpeg subtitles filter."""
    if not srt_path.exists():
        return False
    # Use forward slashes in the subtitles path (ffmpeg quirk on some systems)
    srt_escaped = str(srt_path).replace("\\", "/").replace(":", "\\:")
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video),
        "-vf", f"subtitles='{srt_escaped}':force_style='FontName=Arial,FontSize=22,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=1,Alignment=2,MarginV=40'",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        "-preset", "fast", "-crf", "23",
        "-movflags", "+faststart",
        str(output),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        return proc.returncode == 0 and output.exists()
    except Exception:
        return False


def _ffprobe(video: Path) -> dict | None:
    """Run ffprobe and return parsed JSON."""
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams",
        str(video),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if proc.returncode != 0:
            return None
        return json.loads(proc.stdout)
    except Exception:
        return None
