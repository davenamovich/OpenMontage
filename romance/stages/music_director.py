"""Stage 11: Music and SFX.

Generates a royalty-free ambient music bed using ffmpeg's built-in synthesizers
(sine wave + filters). This keeps the MVP fully self-contained — no external
music scraping that could break.

The music plan maps to emotional beats from the scene plan: mystery opening,
warm first meeting, growing attraction, emotional uncertainty, betrayal/loss,
final decision, romantic payoff, cliffhanger. Each gets a different synth
patch (frequency, filter, modulation).

For SFX, we use ffmpeg's anoisesrc filter to generate ambience (white/pink
noise shaped into restaurant murmur, rain, etc.).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from romance.stages._shared import timed


# Music "patches" — each defines an ffmpeg filter graph that synthesizes an
# ambient bed matching the emotional beat.
MUSIC_PATCHES = {
    "mystery_opening": {
        "freq": 110.0,    # low A
        "filter": "lowpass=f=600, tremolo=f=0.3:d=0.4",
        "duration": 30,
        "volume": 0.18,
    },
    "warm_first_meeting": {
        "freq": 220.0,    # A3
        "filter": "lowpass=f=1200, tremolo=f=0.4:d=0.3",
        "duration": 30,
        "volume": 0.20,
    },
    "growing_attraction": {
        "freq": 261.63,   # C4
        "filter": "lowpass=f=1500, tremolo=f=0.5:d=0.3",
        "duration": 30,
        "volume": 0.22,
    },
    "emotional_uncertainty": {
        "freq": 196.0,    # G3
        "filter": "lowpass=f=900, tremolo=f=0.6:d=0.4",
        "duration": 30,
        "volume": 0.18,
    },
    "betrayal_or_loss": {
        "freq": 146.83,   # D3
        "filter": "lowpass=f=500, tremolo=f=0.2:d=0.5",
        "duration": 30,
        "volume": 0.16,
    },
    "final_decision": {
        "freq": 174.61,   # F3
        "filter": "lowpass=f=800, tremolo=f=0.4:d=0.35",
        "duration": 30,
        "volume": 0.20,
    },
    "romantic_payoff": {
        "freq": 329.63,   # E4
        "filter": "lowpass=f=2000, tremolo=f=0.5:d=0.25",
        "duration": 30,
        "volume": 0.24,
    },
    "cliffhanger": {
        "freq": 130.81,   # C3
        "filter": "lowpass=f=600, tremolo=f=0.3:d=0.5",
        "duration": 15,
        "volume": 0.18,
    },
}

# SFX patches
SFX_PATCHES = {
    "restaurant_ambience": "anoisesrc=color=pink:a=0.06, lowpass=f=800",
    "rain": "anoisesrc=color=white:a=0.04, lowpass=f=4000, highpass=f=200",
    "door": "sine=frequency=120:duration=0.5, afade=t=out:st=0.3:d=0.2",
    "phone_vibration": "sine=frequency=145:duration=0.3, tremolo=f=20:d=1.0",
    "footsteps": "anoisesrc=color=brown:a=0.05, tremolo=f=2:d=0.6",
    "traffic": "anoisesrc=color=pink:a=0.04, lowpass=f=500",
    "crowd_murmur": "anoisesrc=color=pink:a=0.05, lowpass=f=1000, tremolo=f=3:d=0.4",
    "clock_tick": "sine=frequency=1000:duration=0.05, afade=t=out:st=0.04:d=0.01",
    "ocean": "anoisesrc=color=pink:a=0.06, lowpass=f=600, tremolo=f=0.5:d=0.4",
    "fireplace": "anoisesrc=color=brown:a=0.05, lowpass=f=400, tremolo=f=2:d=0.5",
}


def run(engine, payload: dict) -> dict:
    return timed(lambda: _run(engine, payload))


def _run(engine, payload: dict) -> dict:
    scene_plan = engine.load_artifact("scene_plan")
    if not scene_plan:
        return {"error": "Missing scene_plan"}

    # Load existing manifest
    manifest = engine.load_artifact("asset_manifest") or {
        "version": "1.0", "project_id": engine.project_id, "assets": [],
    }
    assets = manifest.get("assets", [])
    assets = [a for a in assets if a.get("type") != "music_track"]
    assets = [a for a in assets if a.get("type") != "sfx_track"]

    # Generate one music track per distinct music_cue
    cues_used = set()
    for sc in scene_plan.get("scenes", []):
        cue = sc.get("metadata", {}).get("music_cue")
        if cue and cue in MUSIC_PATCHES:
            cues_used.add(cue)

    music_paths: dict[str, str] = {}
    for cue in sorted(cues_used):
        patch = MUSIC_PATCHES[cue]
        out_path = engine.asset_path("music", f"{cue}.wav")
        if out_path.exists() and out_path.stat().st_size > 0:
            music_paths[cue] = str(out_path)
            continue
        ok = _synth_music(patch, out_path)
        if ok:
            music_paths[cue] = str(out_path)
            assets.append({
                "type": "music_track",
                "cue": cue,
                "path": str(out_path),
                "provider": "ffmpeg_synth",
                "duration_seconds": patch["duration"],
            })

    # Generate SFX for cues mentioned in scenes
    sfx_used = set()
    for sc in scene_plan.get("scenes", []):
        for effect in sc.get("metadata", {}).get("sfx", []):
            key = effect.lower().replace(" ", "_")
            if key in SFX_PATCHES:
                sfx_used.add(key)

    sfx_paths: dict[str, str] = {}
    for sfx in sorted(sfx_used):
        out_path = engine.asset_path("sfx", f"{sfx}.wav")
        if out_path.exists() and out_path.stat().st_size > 0:
            sfx_paths[sfx] = str(out_path)
            continue
        ok = _synth_sfx(SFX_PATCHES[sfx], out_path, duration=2.0)
        if ok:
            sfx_paths[sfx] = str(out_path)
            assets.append({
                "type": "sfx_track",
                "effect": sfx,
                "path": str(out_path),
                "provider": "ffmpeg_synth",
            })

    manifest = {
        "version": "1.0",
        "project_id": engine.project_id,
        "assets": assets,
        "metadata": {
            **manifest.get("metadata", {}),
            "stage": "music_and_sfx",
            "music_paths": music_paths,
            "sfx_paths": sfx_paths,
            "cues_used": sorted(cues_used),
            "sfx_used": sorted(sfx_used),
        },
    }
    engine.log("music_and_sfx",
               "Music + SFX generated",
               tracks=len(music_paths), sfx=len(sfx_paths))
    return {
        "artifact": "asset_manifest",
        "data": manifest,
    }


def _synth_music(patch: dict, output_path: Path) -> bool:
    """Synthesize an ambient music bed with ffmpeg."""
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"sine=frequency={patch['freq']}:duration={patch['duration']}",
        "-af", f"{patch['filter']}, volume={patch['volume']}, afade=t=in:st=0:d=2, afade=t=out:st={patch['duration']-3}:d=3",
        "-ar", "44100", "-ac", "2",
        str(output_path),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return proc.returncode == 0 and output_path.exists()
    except Exception:
        return False


def _synth_sfx(filter_str: str, output_path: Path, duration: float = 2.0) -> bool:
    """Synthesize an SFX with ffmpeg lavfi."""
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", filter_str.replace("a=0.06", f"a=0.06:duration={duration}").replace("a=0.04", f"a=0.04:duration={duration}").replace("a=0.05", f"a=0.05:duration={duration}"),
        "-ar", "44100", "-ac", "2",
        str(output_path),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return proc.returncode == 0 and output_path.exists()
    except Exception:
        return False
