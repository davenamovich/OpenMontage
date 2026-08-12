"""CLI entry point for the youtube-romance-story pipeline.

Usage:
    # Create a new project from a one-sentence premise
    python -m romance.cli create "A struggling waitress falls in love with a wealthy customer..."

    # Run the full pipeline end-to-end
    python -m romance.cli run projects/<slug>

    # Run a single stage
    python -m romance.cli run-stage projects/<slug> concept

    # Show status
    python -m romance.cli status projects/<slug>

    # Resume from where we left off
    python -m romance.cli resume projects/<slug>

    # List all projects
    python -m romance.cli list
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from romance.engine import PROJECTS_ROOT, RomanceEngine, create_project, load_intake_defaults


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="romance", description="YouTube Romance Story Engine")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_create = sub.add_parser("create", help="Create a new project from a premise")
    p_create.add_argument("premise", help="One-sentence story premise")
    p_create.add_argument("--genre", default=None, help="Override genre")
    p_create.add_argument("--format", default=None, help="Override format")
    p_create.add_argument("--duration", type=int, default=None, help="Override target duration (seconds)")
    p_create.add_argument("--visual-mode", default=None, help="Override visual mode")
    p_create.add_argument("--era", default=None, help="Override era/decade (e.g. victorian, roaring_20s, neon_80s)")
    p_create.add_argument("--visual-style", default=None, help="Override visual style (e.g. anime, oil_painting, caricature)")
    p_create.add_argument("--budget", type=float, default=None, help="Override max budget USD")
    p_create.add_argument("--aspect", default=None, help="Override aspect ratio")

    p_run = sub.add_parser("run", help="Run the full pipeline")
    p_run.add_argument("project_dir", help="Project directory")
    p_run.add_argument("--until", default=None, help="Stop after this stage")

    p_stage = sub.add_parser("run-stage", help="Run a single stage")
    p_stage.add_argument("project_dir")
    p_stage.add_argument("stage", help="Stage name (e.g. concept, story_bible, script, ...)")
    p_stage.add_argument("--payload", default=None, help="JSON payload file")

    p_status = sub.add_parser("status", help="Show project status")
    p_status.add_argument("project_dir")

    p_resume = sub.add_parser("resume", help="Resume from the next incomplete stage")
    p_resume.add_argument("project_dir")

    sub.add_parser("list", help="List all projects")

    p_serve = sub.add_parser("serve", help="Start the web UI server")
    p_serve.add_argument("--port", type=int, default=8000, help="Port (default 8000)")
    p_serve.add_argument("--host", default="0.0.0.0", help="Host (default 0.0.0.0)")

    p_demo = sub.add_parser("demo", help="Create the canonical demo project")
    p_demo.add_argument("--skip-render", action="store_true", help="Skip the asset/render stages (LLM-only smoke test)")

    p_auto = sub.add_parser("auto", help="Create a project and immediately run the full pipeline")
    p_auto.add_argument("premise", help="One-sentence story premise")
    p_auto.add_argument("--genre", default=None)
    p_auto.add_argument("--format", default=None)
    p_auto.add_argument("--duration", type=int, default=None)
    p_auto.add_argument("--visual-mode", default=None)
    p_auto.add_argument("--era", default=None, help="Era/decade (victorian, roaring_20s, neon_80s, etc.)")
    p_auto.add_argument("--visual-style", default=None, help="Visual style (anime, oil_painting, caricature, etc.)")
    p_auto.add_argument("--budget", type=float, default=None)
    p_auto.add_argument("--background", action="store_true", help="Run in background (returns job_id immediately)")
    p_auto.add_argument("--until", default=None, help="Stop after this stage")

    args = parser.parse_args(argv)

    if args.cmd == "create":
        intake = {}
        if args.genre: intake["genre"] = args.genre
        if args.format: intake["format"] = args.format
        if args.duration: intake["target_duration"] = args.duration
        if args.visual_mode: intake["visual_mode"] = args.visual_mode
        if args.era: intake["era"] = args.era
        if args.visual_style: intake["visual_style"] = args.visual_style
        if args.budget: intake["max_budget_usd"] = args.budget
        if args.aspect: intake["output_aspect_ratio"] = args.aspect
        engine = create_project(args.premise, intake)
        print(f"Created project: {engine.project_dir}")
        print(f"  slug: {engine.project_id}")
        print(f"  next: run `python -m romance.cli run {engine.project_dir}`")
        return 0

    if args.cmd == "run":
        engine = RomanceEngine(args.project_dir)
        result = engine.run_all(until=args.until)
        if result.get("error"):
            print(f"FAILED at stage {engine.project['current_stage']}: {result['error']}", file=sys.stderr)
            return 1
        print(f"Pipeline complete. Final stage: {engine.project['current_stage']}")
        print(json.dumps(engine.status(), indent=2, default=str))
        return 0

    if args.cmd == "run-stage":
        engine = RomanceEngine(args.project_dir)
        payload = {}
        if args.payload:
            payload = json.loads(Path(args.payload).read_text())
        result = engine.run(args.stage, payload)
        if result.get("error"):
            print(f"FAILED: {result['error']}", file=sys.stderr)
            return 1
        print(f"Stage {args.stage} complete.")
        if result.get("artifact"):
            print(f"  artifact: {result['artifact']}")
        print(f"  duration: {result.get('duration_seconds','?')}s")
        return 0

    if args.cmd == "status":
        engine = RomanceEngine(args.project_dir)
        print(json.dumps(engine.status(), indent=2, default=str))
        return 0

    if args.cmd == "resume":
        engine = RomanceEngine(args.project_dir)
        nxt = engine.resume()
        if nxt is None:
            print("Pipeline is complete — nothing to resume.")
            return 0
        print(f"Resuming from stage: {nxt}")
        result = engine.run_all()
        if result.get("error"):
            print(f"FAILED at stage {engine.project['current_stage']}: {result['error']}", file=sys.stderr)
            return 1
        print("Pipeline complete.")
        return 0

    if args.cmd == "list":
        root = PROJECTS_ROOT
        if not root.exists():
            print("No projects yet.")
            return 0
        for p in sorted(root.iterdir()):
            if p.is_dir():
                engine = RomanceEngine(p)
                status = engine.status()
                print(f"{p.name}: {status['stages_completed']}/{status['stages_total']} stages")
        return 0

    if args.cmd == "serve":
        import uvicorn
        from web.api import app
        print(f"Starting Romance Story Engine UI at http://localhost:{args.port}")
        uvicorn.run(app, host=args.host, port=args.port, log_level="info")
        return 0

    if args.cmd == "demo":
        return _create_demo(args.skip_render)

    if args.cmd == "auto":
        return _auto_run(args)

    return 0


def _auto_run(args) -> int:
    """Create a project and immediately run the full pipeline."""
    intake = {}
    if args.genre: intake["genre"] = args.genre
    if args.format: intake["format"] = args.format
    if args.duration: intake["target_duration"] = args.duration
    if args.visual_mode: intake["visual_mode"] = args.visual_mode
    if args.era: intake["era"] = args.era
    if args.visual_style: intake["visual_style"] = args.visual_style
    if args.budget: intake["max_budget_usd"] = args.budget

    engine = create_project(args.premise, intake)
    print(f"Created project: {engine.project_dir}")
    print(f"  slug: {engine.project_id}")

    if args.background:
        job_id = engine.run_all_background(until=args.until)
        print(f"\nStarted background job: {job_id}")
        print(f"Monitor with:")
        print(f"  python -m romance.cli status {engine.project_dir}")
        return 0

    print(f"\nRunning pipeline...")
    result = engine.run_all(until=args.until)
    if result.get("error"):
        print(f"\nFAILED at stage {engine.project['current_stage']}: {result['error']}", file=sys.stderr)
        print(f"\nResume with:")
        print(f"  python -m romance.cli resume {engine.project_dir}")
        return 1

    print(f"\nPipeline complete!")
    status = engine.status()
    print(f"  Stages: {status['stages_completed']}/{status['stages_total']}")
    print(f"  Cost: ${status['cost_snapshot']['total_spent_usd']:.2f}")
    if status.get("artifacts_on_disk"):
        print(f"  Artifacts: {', '.join(status['artifacts_on_disk'][:5])}...")
    return 0


def _create_demo(skip_render: bool = False) -> int:
    """Create the canonical demo: 'He Came to the Diner Every Friday'."""
    premise = (
        "Emma, a 34-year-old waitress rebuilding her life after a painful divorce, "
        "notices that Daniel, a quiet and apparently wealthy customer, requests the "
        "same corner booth every Friday. She assumes he is waiting for someone. When "
        "she finally asks, she discovers that the booth is connected to a promise he "
        "made years earlier—and that Emma has unknowingly become part of it."
    )
    intake = {
        "genre": "small_town",
        "format": "long_form",
        "target_duration": 540,  # 9 minutes
        "emotional_tone": "warm_cinematic_realism",
        "setting": "contemporary_small_town",
        "narration_perspective": "third_person_limited",
        "desired_ending": "satisfying_emotional_payoff",
        "romance_intensity": 6,
        "drama_intensity": 5,
        "mystery_intensity": 6,
        "visual_mode": "economical",
        "narrator_voice": "warm_female",
        "music_style": "warm_acoustic_cinematic",
        "language": "en",
        "output_aspect_ratio": "16:9",
        "max_budget_usd": 5.00,
        "channel_name": "Original Romance Stories",
        "call_to_action": "Subscribe for more original love stories.",
        "title": "He Came to the Diner Every Friday",
        "main_character_names": ["Emma", "Daniel"],
        "character_ages": [34, 38],
        "character_descriptions": [
            "Emma: 34, waitress rebuilding her life after divorce, warm brown eyes, shoulder-length auburn hair, navy diner uniform, resilient but guarded.",
            "Daniel: 38, quiet wealthy customer, graying temples, navy coat, reserved, carries a quiet sadness.",
        ],
    }
    engine = create_project(premise, intake)
    print(f"Demo project created: {engine.project_dir}")

    if skip_render:
        # Phase 1 only: run the LLM-only stages
        for stage in ["intake", "concept", "story_bible", "outline", "script", "continuity_review", "scene_plan"]:
            print(f"\n=== Running stage: {stage} ===")
            result = engine.run(stage)
            if result.get("error"):
                print(f"FAILED: {result['error']}", file=sys.stderr)
                return 1
            print(f"  artifact: {result.get('artifact')}")
            print(f"  duration: {result.get('duration_seconds','?')}s")
    else:
        # Full pipeline
        result = engine.run_all()
        if result.get("error"):
            print(f"FAILED at stage {engine.project['current_stage']}: {result['error']}", file=sys.stderr)
            return 1
        print("\nPipeline complete.")
        print(json.dumps(engine.status(), indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
