# Compose Director — YouTube Romance Story Pipeline

## When To Use

This stage assembles the final MP4 from the scene plan, asset manifest, and
script. It produces:
- youtube-16x9.mp4 (or short-9x16.mp4) — the final video with burned-in captions
- clean-video.mp4 — the video without burned-in captions
- captions.srt, captions.vtt — subtitle files
- render_report artifact (canonical)
- final_review artifact (supplementary)

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Schema | `schemas/artifacts/render_report.schema.json` | Artifact validation |
| Prior artifacts | `scene_plan`, `asset_manifest`, `script` | Required inputs |
| Tools | `video_stitch`, `audio_mixer`, `subtitle_gen`, `remotion_caption_burn` | FFmpeg-based composition |

## Process

### 1. Build Per-Scene Ken Burns Clips

For each scene in the scene_plan:
- Load the scene image from the asset_manifest
- Apply a Ken Burns effect (slow pan/zoom) based on the scene's camera_movement
  - zoom_in → slow zoom in
  - zoom_out → slow zoom out
  - pan_left/pan_right → horizontal pan
  - tilt_up/tilt_down → vertical pan
  - static → very slow imperceptible zoom (no true static — avoids slideshow feel)
- Duration = scene end_seconds - scene start_seconds
- Output: assets/video/scene-<id>.mp4

### 2. Stitch Clips With Crossfades

Concatenate all scene clips using ffmpeg concat demuxer. Use crossfade
transitions between clips (1-second crossfade). If codec params differ
between clips, re-encode the concat output.

Output: renders/clean-video.mp4

### 3. Build Full Narration Audio

Concatenate all per-section narration audio files (from voice_generation
stage) into one continuous narration track. Use ffmpeg concat with PCM
re-encoding if needed.

Output: assets/voice/full-narration.wav

### 4. Mix Narration + Music

Use ffmpeg's sidechaincompress filter to duck the music under the narration:
- Music volume = 0.5 (background level)
- Narration volume = 1.0 (full level)
- Sidechain threshold = 0.05, ratio = 8:1, attack = 20ms, release = 300ms

Output: assets/voice/final-mix.wav

### 5. Mux Video + Audio

Combine the clean video with the final audio mix. Use `-c:v copy` to preserve
video quality, `-c:a aac -b:a 192k` for audio. Add `-movflags +faststart` for
web playback.

Output: renders/youtube-16x9.mp4 (or short-9x16.mp4)

### 6. Generate Captions

Write SRT and VTT caption files from the script sections. Each section is
split into cues of ~80 characters, spread evenly across the section's
duration.

Output: assets/captions/captions.srt, assets/captions/captions.vtt

### 7. Burn In Captions

Use ffmpeg's subtitles filter to burn the SRT into the final video. Style:
Arial 22pt, white text, black outline, bottom-center alignment, 40px margin.

Output: renders/youtube-16x9.mp4 (replaces the non-captioned version)

## Render Runtime Routing

The `render_runtime` field in the proposal_packet's production_plan
determines which composition engine to use:

- **ffmpeg** (default for romance pipeline) — Ken Burns + concat + caption
  burn. This is the runtime the romance pipeline uses because:
  1. Faceless romance videos are image-led, not motion-led
  2. Ken Burns motion + crossfades produce cinematic feel from stills
  3. No external JS runtime (Remotion/HyperFrames) needed
  4. Most reliable for long-form 8-15 minute videos

- **hyperframes** — NOT used by default. If the visual_mode is `text_message`
  or the format is `confession`, hyperframes may produce better results for
  chat-bubble and text-card scenes. To switch: set render_runtime="hyperframes"
  in the proposal_packet and ensure the HyperFrames CLI is available.

- **remotion** — NOT used by default. If the visual_mode is `cinematic` with
  complex data overlays, Remotion may be better. To switch: set
  render_runtime="remotion" and ensure the Remotion composer is built.

**Silent runtime swaps are FORBIDDEN.** The compose stage MUST use the
render_runtime locked in the proposal_packet. If the runtime is unavailable
(e.g. HyperFrames CLI not installed), the compose stage fails with a clear
error rather than silently falling back to ffmpeg.

## Quality Gate

- Output MP4 plays start-to-finish without errors (ffprobe validation)
- Narration is synced to visuals
- Music is ducked under narration (not overwhelming)
- Captions are legible, in safe area, not covering faces
- Both burned-in and clean versions exist
- SRT and VTT files exist and are valid

## Common Pitfalls

- Music too loud — drowns out narration
- Captions covering character faces
- Slideshow feel — every scene gets the same slow zoom
- Missing faststart flag — video won't stream on YouTube
- Audio desync — narration longer/shorter than video
