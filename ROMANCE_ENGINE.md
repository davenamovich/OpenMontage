# YouTube Romance Story Engine for OpenMontage

A faceless YouTube romance-story production system built as a modular extension
to [OpenMontage](https://github.com/davenamovich/OpenMontage). Transforms a
one-sentence premise into a complete, original video package: story bible,
structured script, character-consistent visuals, narration, music, captions,
Shorts, thumbnails, and a full YouTube metadata package.

## Quick Start

```bash
cd OpenMontage

# Create a new project from a one-sentence premise
python -m romance.cli create "A struggling waitress falls in love with a wealthy customer, but discovers he has been hiding why he visits the restaurant every Friday."

# Run the full pipeline end-to-end
python -m romance.cli run projects/<slug>

# Or run a single stage
python -m romance.cli run-stage projects/<slug> concept

# Check status
python -m romance.cli status projects/<slug>

# Resume from where you left off
python -m romance.cli resume projects/<slug>

# List all projects
python -m romance.cli list

# Create and run the canonical demo
python -m romance.cli demo
```

## What It Produces

For every project, the engine generates:

1. **Original romance story** — premise, concept, story bible, outline, script
2. **Strong YouTube hook** — first narration line creates immediate curiosity
3. **Structured episode script** — 10 emotional beats (hook → setup → inciting encounter → rising attraction → complication → midpoint shift → emotional break → final choice → payoff → final button)
4. **Narration and character dialogue** — per-section TTS audio files
5. **Scene-by-scene visual plan** — shot types, camera movements, lighting, music cues
6. **Consistent recurring characters** — stable character_id, visual reference prompts, voice assignments
7. **Cinematic images** — one per scene, character prompts reference the story bible
8. **Voice narration** — TTS via z-ai (free) or Piper (offline fallback)
9. **Background music and sound effects** — synthesized ambient beds per emotional beat
10. **Captions** — SRT and VTT files, sentence-level
11. **Finished YouTube video** — MP4 with narration, visuals, music, and captions
12. **YouTube Shorts** — 1-2 vertical 9:16 clips extracted from the long-form
13. **Thumbnail concepts** — 3 concepts with generated images and overlay text
14. **YouTube metadata** — 10 title options, 3 recommended, description, chapters, tags, hashtags, pinned comment, community post, Shorts hooks + scripts
15. **Reusable project** — every artifact saved as JSON, resumable from any stage

## Pipeline Stages (17 total)

| # | Stage | Produces | LLM? |
|---|-------|----------|------|
| 1 | `intake` | `brief` | No |
| 2 | `proposal` | `proposal_packet` + `decision_log` | Yes |
| 3 | `story_bible` | `story_bible` | Yes |
| 4 | `outline` | `outline` | Yes |
| 5 | `script` | `script` | Yes |
| 6 | `continuity_review` | `continuity_ledger` + `review` | Yes |
| 7 | `scene_plan` | `scene_plan` | Deterministic |
| 8 | `character_assets` | `asset_manifest` (character images) | z-ai image |
| 9 | `visual_assets` | `asset_manifest` (scene images) | z-ai image |
| 10 | `voice_generation` | `asset_manifest` (narration audio) | z-ai TTS |
| 11 | `music_and_sfx` | `asset_manifest` (music + SFX) | ffmpeg synth |
| 12 | `compose` | `render_report` + `final_review` | ffmpeg |
| 13 | `quality_review` | `review` | Yes |
| 14 | `shorts_extraction` | `shorts_package` | ffmpeg |
| 15 | `thumbnail_generation` | `thumbnail_concept` | Yes + z-ai image |
| 16 | `youtube_package` | `youtube_package` | Yes |
| 17 | `publish` | `publish_log` | No |

## Supported Formats

- **Long-Form Episode** — 8-15 min, 16:9, 1300-2400 words
- **Romance Short** — 45-90 sec, 9:16, 120-220 words
- **Serialized Romance** — continuing episodes with series bible + continuity ledger
- **Confession Story** — first-person, intimate, diary/voice-note style
- **Text-Message Romance** — chat-style narrated story

## Genres (26 supported)

second_chance, forbidden_love, friends_to_lovers, enemies_to_lovers,
secret_identity, workplace, small_town, billionaire, unexpected_inheritance,
marriage_of_convenience, long_distance, lost_love, love_after_divorce, mature,
holiday, romantic_mystery, romantic_suspense, betrayal_redemption,
family_disapproval, class_difference, accidental_meeting, fake_relationship,
single_parent, military_reunion, historical, supernatural

## Visual Modes

- **Economical** — still images + motion, lowest cost (default)
- **Hybrid** — character stills + stock env + AI-video hero moments
- **Cinematic** — AI-generated video clips, higher budget

## Architecture

The engine reuses OpenMontage's existing infrastructure:

- `lib/pipeline_loader.py` — manifest loading + validation
- `lib/checkpoint.py` — per-stage checkpoint persistence + resume
- `tools/cost_tracker.py` — budget governance
- `schemas/artifacts/` — JSON schema validation for all artifacts
- `tools/audio/` — TTS selector, audio mixer, Piper, Pixabay music
- `tools/graphics/` — image selector, Pixabay/Pexels images
- `tools/video/` — video stitch, trimmer, compose, caption burn
- `tools/subtitle/subtitle_gen.py` — SRT/VTT generation

### New components added

- `pipeline_defs/youtube-romance-story.yaml` — 17-stage pipeline manifest
- `romance/` — Python package (engine, 17 stage directors, LLM bridge, CLI)
- `tools/llm/` — 3 new BaseTool implementations: `zai_image`, `zai_tts`, `zai_video`
- `skills/pipelines/youtube-romance-story/` — 18 stage director skill markdown files
- `schemas/artifacts/` — 6 new schemas: `story_bible`, `outline`, `continuity_ledger`, `youtube_package`, `thumbnail_concept`, `shorts_package`
- `tests/romance/` — 45 tests covering manifest, schemas, persistence, captions, scene plan, cost tracking, Z-AI tools

## Project Structure

```
projects/<project-slug>/
  project.json              # Project metadata + stage tracking
  intake.json               # User input + defaults
  brief.json                # Canonical brief artifact
  proposal_packet.json      # 3 concepts + selected concept
  story_bible.json          # Characters, world, locations, voices
  outline.json              # 10 emotional beats
  script.json               # Timestamped narration sections
  continuity_ledger.json    # Character state + quality scores
  scene_plan.json           # Per-scene visual plan
  asset_manifest.json       # All generated assets
  render_report.json        # Compose stage output
  final_review.json         # Final quality checks
  review.json               # Quality review scores
  shorts_package.json       # Extracted Shorts
  thumbnail_concept.json    # 3 thumbnail concepts
  youtube_package.json      # Complete YouTube metadata
  publish_log.json          # Publish verification
  assets/
    characters/             # Character reference images
    images/                 # Scene images
    video/                  # Per-scene Ken Burns clips
    voice/                  # Narration + section audio
    music/                  # Synthesized music beds
    sfx/                    # Sound effects
    captions/               # SRT + VTT
    thumbnails/             # Thumbnail images
  renders/
    youtube-16x9.mp4        # Final video
    clean-video.mp4         # Video without burned captions
    short-01-9x16.mp4       # Vertical Short 1
    short-02-9x16.mp4       # Vertical Short 2
  youtube/
    titles.md               # 10 title options + 3 recommended
    description.md          # Full description
    chapters.md             # YouTube chapters
    tags.md                 # Tags + hashtags
    pinned-comment.md       # Pinned comment
    community-post.md       # Community tab post
    shorts.md               # 3 Shorts hooks + scripts
  pipeline/                 # OpenMontage checkpoints
  logs/                     # Per-stage logs
```

## Tests

```bash
# Run romance pipeline tests (45 tests)
python -m pytest tests/romance/ -v

# Run full OpenMontage test suite (381 tests, 2 pre-existing failures)
python -m pytest tests/ --ignore=tests/eval --ignore=tests/qa -q
```

## Environment Requirements

- Python 3.11+
- ffmpeg + ffprobe
- `z-ai` CLI (for LLM, TTS, image generation) — already available in this environment
- Node.js (for z-ai CLI)

## Content Safety

- All romantic characters are adults (18+)
- No sexual content involving minors
- No non-consensual sexual content, incest, or glorified abuse
- Manipulation/stalking/coercion framed as problems, not romance
- No real private people's faces or voices without permission
- No copyrighted characters or direct imitation of living authors
- Confession stories labeled as fictional

## Demo: "He Came to the Diner Every Friday"

The canonical demo is included. To reproduce:

```bash
python -m romance.cli demo
```

This creates a complete project from the premise:
> Emma, a 34-year-old waitress rebuilding her life after a painful divorce,
> notices that Daniel, a quiet and apparently wealthy customer, requests the
> same corner booth every Friday. She assumes he is waiting for someone. When
> she finally asks, she discovers that the booth is connected to a promise he
> made years earlier—and that Emma has unknowingly become part of it.

The demo produces:
- 11-section script (~940 words, "The Corner Booth Promise")
- 4 character reference images (Emma, Daniel, Martha, Tom)
- 33 scene images
- 11 narration audio files
- 7 music tracks + SFX
- 720p MP4 (62s, 2.5MB)
- 2 vertical Shorts (9:16, 45s each)
- 3 thumbnail concepts with images
- Complete YouTube metadata package
