# Concept Director — YouTube Romance Story Pipeline

## When To Use

This stage takes the validated intake brief and generates 3 distinct romance
story concepts with different emotional angles. The user (or the auto-select
logic) picks one, which becomes the foundation for all downstream stages.

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Schema | `schemas/artifacts/proposal_packet.schema.json` | Artifact validation |
| Prior artifact | `brief` (from intake) | Premise, genre, format, audience |
| Tools | LLM (z-ai chat) | Concept generation |

## Process

### 1. Read The Brief

Load the brief artifact. Extract:
- Premise (the one-sentence story idea)
- Genre, format, target duration
- Tone, setting, time period
- Character names/descriptions (if provided)

### 2. Generate 3 Concepts

Call the LLM with the concept prompt. Require:
- 3 DIFFERENT emotional angles (e.g. mystery-led, character-led, situation-led)
- Each concept has a hook ≤ 30 words that creates immediate curiosity
- All 10 required emotional beats are present in each concept's beat_summary
- Original only — no copyrighted characters, no imitation of living authors

### 3. Select The Best Concept

Pick the concept with the strongest hook, most believable conflict, and most
satisfying payoff. Store the selection rationale in the decision_log.

### 4. Build The Proposal Packet

Produce a proposal_packet artifact conforming to the existing OpenMontage
schema. Romance-specific data (selected_concept, all_concepts, etc.) goes
under metadata.

## Render Runtime Selection

This pipeline uses `render_runtime: ffmpeg` for the compose stage. The
choice is between:

- **ffmpeg** — Ken Burns image animation + concat + audio mux + caption burn.
  Simplest, most reliable, no external dependencies. Best for faceless
  romance videos where the visual is character-led still images with motion.
- **hyperframes** — HTML/CSS/GSAP-driven composition. Better for kinetic title
  cards and text-message-style scenes. Requires the HyperFrames CLI.
- **remotion** — React-based composition. Best for data-driven or template-
  heavy videos. Requires the Remotion composer.

**Present both** ffmpeg and hyperframes to the user when the visual_mode is
`economical` or `hybrid`. For `cinematic` mode, ffmpeg is the only option
that reliably handles AI-generated video clips.

The `render_runtime` field is locked in the proposal_packet's production_plan.
A `render_runtime_selection` decision is logged in the decision_log. The
compose stage cannot silently change this — any swap must be a logged
decision with user approval.

## Quality Gate

- 3 distinct concepts with different emotional angles
- Hook ≤ 30 words, creates immediate curiosity
- All 10 emotional beats present
- No copyrighted characters or direct imitation
- Selected concept has clear romantic arc and meaningful mystery

## Common Pitfalls

- Starting with background exposition instead of a hook
- Generic AI prose ("In a world where...")
- Instant love without development
- Plot twists with no setup
