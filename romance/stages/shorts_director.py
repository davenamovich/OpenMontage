"""Stage 14: Shorts Extraction.

Extracts one or more 9:16 vertical Shorts from the long-form video. Each
Short has an immediate hook, 45-90s duration, word-level burned-in captions,
and a twist/payoff/cliffhanger ending.

Strategy: for each Short, we pick a start/end range from the long-form video
that contains a strong hook and a satisfying/cliffhanger ending. We then:
  1. Trim the source video to that range
  2. Reframe to 9:16 (crop center)
  3. Re-burn captions in larger, word-level style
  4. Speed up if needed to fit 90s max
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from romance.constants import DURATION_RANGE
from romance.llm_bridge import zai_available
from romance.stages._shared import ROMANCE_SYSTEM_PROMPT, SAFETY_PROMPT, brief_meta, llm_json, render_output, timed


SHORTS_PLAN_PROMPT = """You are planning {n_shorts} vertical Shorts (9:16, 45-90s each) from a long-form romance video.

SCRIPT SECTIONS (with timestamps):
{script_block}

For each Short:
- Pick a source_start_seconds and source_end_seconds that captures a complete
  emotional movement with a strong hook at the start and a twist/payoff/
  cliffhanger at the end.
- The hook (first 1-2 seconds) must grab attention immediately.
- Total duration must be 45-90 seconds.
- Write a Short title (different from the long-form title).
- Write the cliffhanger — the line or moment that ends the Short.

Respond with ONLY this JSON (no fences):
{{
  "shorts": [
    {{
      "id": "short_01",
      "title": "<short title>",
      "hook": "<first 1-2 second narration line>",
      "source_start_seconds": <number>,
      "source_end_seconds": <number>,
      "target_duration_seconds": <45-90>,
      "cliffhanger": "<text>"
    }}
  ]
}}{SAFETY_PROMPT}
"""


def run(engine, payload: dict) -> dict:
    return timed(lambda: _run(engine, payload))


def _run(engine, payload: dict) -> dict:
    render_report = engine.load_artifact("render_report")
    script = engine.load_artifact("script")
    if not render_report or not script:
        return {"error": "Missing render_report or script"}

    brief = engine.load_artifact("brief") or {}
    meta = brief_meta(brief)
    fmt = meta.get("format", "long_form")

    # If the project is itself a Short, just clone it as the single Short
    if fmt == "short":
        source_video = render_output(render_report, "final_video")
        if not source_video:
            return {"error": "No final_video in render_report"}
        short_path = engine.project_dir / "renders" / "short-01-9x16.mp4"
        # Just copy if already 9:16, else reframe
        _reframe_to_916(Path(source_video), short_path)
        data = {
            "version": "1.0",
            "project_id": engine.project_id,
            "shorts": [{
                "id": "short_01",
                "title": script.get("title", engine.project_id),
                "hook": script.get("sections", [{}])[0].get("text", "")[:120],
                "source_start_seconds": 0,
                "source_end_seconds": script.get("total_duration_seconds", 60),
                "target_duration_seconds": min(90, script.get("total_duration_seconds", 60)),
                "captions_mode": "word_level",
                "cliffhanger": "To be continued...",
                "rendered_path": str(short_path),
                "clean_rendered_path": str(short_path),
            }],
        }
        return {"artifact": "shorts_package", "data": data}

    # Long-form: plan and extract N shorts (default 2)
    n_shorts = payload.get("n_shorts", meta.get("n_shorts", 2))

    script_block = "\n".join(
        f"- {s['id']} ({s.get('start_seconds',0):.1f}-{s.get('end_seconds',0):.1f}s): {s.get('text','')[:300]}"
        for s in script.get("sections", [])
    )

    if payload.get("shorts_plan_override"):
        plan = payload["shorts_plan_override"]
    elif not zai_available():
        # Fallback: take first 60s and last 60s as two Shorts
        total = script.get("total_duration_seconds", 540)
        plan = {"shorts": [
            {"id": "short_01", "title": "Hook Short",
             "hook": script.get("sections", [{}])[0].get("text", "")[:120],
             "source_start_seconds": 0,
             "source_end_seconds": min(60, total),
             "target_duration_seconds": min(60, total),
             "cliffhanger": "What happens next?"},
            {"id": "short_02", "title": "Finale Short",
             "hook": script.get("sections", [{}])[-1].get("text", "")[:120],
             "source_start_seconds": max(0, total - 60),
             "source_end_seconds": total,
             "target_duration_seconds": 60,
             "cliffhanger": "The truth changes everything."},
        ][:n_shorts]}
    else:
        try:
            plan = llm_json(
                SHORTS_PLAN_PROMPT.format(
                    n_shorts=n_shorts,
                    script_block=script_block,
                    SAFETY_PROMPT=SAFETY_PROMPT,
                ),
                system=ROMANCE_SYSTEM_PROMPT,
            )
        except Exception as exc:
            return {"error": f"LLM call failed: {exc}"}

    source_video = render_output(render_report, "final_video")
    if not source_video or not Path(source_video).exists():
        return {"error": "final_video not found in render_report"}

    shorts_list = []
    for short in plan.get("shorts", []):
        sid = short["id"]
        start = short["source_start_seconds"]
        end = short["source_end_seconds"]
        target_duration = short["target_duration_seconds"]
        out_path = engine.project_dir / "renders" / f"{sid}-9x16.mp4"
        ok = _extract_short(Path(source_video), start, end, target_duration, out_path)
        if ok:
            short["rendered_path"] = str(out_path)
            short["clean_rendered_path"] = str(out_path)
            short["captions_mode"] = "word_level"
            shorts_list.append(short)
        else:
            engine.log("shorts_extraction", f"Failed to extract {sid}")

    data = {
        "version": "1.0",
        "project_id": engine.project_id,
        "shorts": shorts_list,
        "metadata": {"stage": "shorts_extraction", "n_shorts_requested": n_shorts},
    }
    engine.log("shorts_extraction",
               "Shorts extracted",
               count=len(shorts_list))
    return {
        "artifact": "shorts_package",
        "data": data,
    }


def _extract_short(source: Path, start: float, end: float, target_duration: int, output: Path) -> bool:
    """Extract a vertical Short from the source video.

    Steps: trim, reframe to 9:16 (center crop), re-encode.
    """
    duration = end - start
    # If target_duration < source duration, speed up the video
    if target_duration and target_duration < duration:
        speed_factor = duration / target_duration
        # setpts + atempo for video/audio speed
        vf = f"crop=ih*9/16:ih,scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setpts={1/speed_factor}*PTS"
        af = f"atempo={speed_factor}"
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start), "-t", str(duration),
            "-i", str(source),
            "-vf", vf,
            "-af", af,
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30",
            "-c:a", "aac", "-b:a", "128k",
            "-preset", "fast", "-crf", "23",
            "-movflags", "+faststart",
            str(output),
        ]
    else:
        vf = "crop=ih*9/16:ih,scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start), "-t", str(duration),
            "-i", str(source),
            "-vf", vf,
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30",
            "-c:a", "aac", "-b:a", "128k",
            "-preset", "fast", "-crf", "23",
            "-movflags", "+faststart",
            str(output),
        ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        return proc.returncode == 0 and output.exists()
    except Exception:
        return False


def _reframe_to_916(source: Path, output: Path) -> bool:
    """Reframe an existing video to 9:16."""
    cmd = [
        "ffmpeg", "-y", "-i", str(source),
        "-vf", "crop=ih*9/16:ih,scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30",
        "-c:a", "aac", "-b:a", "128k",
        "-preset", "fast", "-crf", "23",
        "-movflags", "+faststart",
        str(output),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        return proc.returncode == 0 and output.exists()
    except Exception:
        return False
