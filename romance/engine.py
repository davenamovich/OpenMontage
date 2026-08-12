"""RomanceEngine — the orchestrator for the youtube-romance-story pipeline.

This is the Python entry point that the CLI, tests, and FastAPI server call.
It is intentionally thin: each stage is a separate module under
`romance/stages/` so stages can be tested in isolation.

Responsibilities:
  - Load and persist project state (project.json, intake.json, per-stage artifacts)
  - Write OpenMontage-compatible checkpoints
  - Track cost via tools/cost_tracker.py
  - Route stage calls to the matching director module
  - Resume from the latest completed stage on restart

Design choices:
  - Project layout matches the spec exactly (projects/<slug>/{project.json,
    intake.json, story_bible.json, ...}).
  - All artifacts are JSON files at the project root for easy inspection.
  - Generated assets go under assets/{characters,images,video,voice,music,
    sfx,captions,thumbnails,renders}/.
  - Final rendered MP4s go under renders/.
  - YouTube metadata goes under youtube/.
  - Logs go under logs/.
"""

from __future__ import annotations

import json
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lib.checkpoint import (
    get_completed_stages,
    get_next_stage,
    read_checkpoint,
    write_checkpoint,
)
from lib.pipeline_loader import get_stage_order, load_pipeline
from romance.constants import (
    DURATION_RANGE,
    FORMATS,
    GENRES,
    VISUAL_MODES,
    WORDS_PER_MINUTE,
)
from romance.llm_bridge import zai_available
from tools.cost_tracker import BudgetMode, CostTracker

PIPELINE_NAME = "youtube-romance-story"
PROJECTS_ROOT = Path("projects")

# Artifact file names are snake_case identifiers — never accept anything that
# could escape the project directory (e.g. '../x' or 'x/../../y').
SAFE_ARTIFACT_NAME = re.compile(r"^[a-z0-9][a-z0-9_]{0,127}$")


def _require_safe_artifact_name(name: str) -> str:
    if not SAFE_ARTIFACT_NAME.fullmatch(name or ""):
        raise ValueError(f"Unsafe artifact name: {name!r}")
    return name


def load_intake_defaults(intake: dict[str, Any] | None = None) -> dict[str, Any]:
    """Fill in missing intake fields with sensible defaults.

    A user can submit only `premise` and the system fills everything else.
    """
    intake = dict(intake or {})
    defaults = {
        "genre": "small_town",
        "format": "long_form",
        "target_duration": 540,           # 9 min
        "target_audience": "adults_25_55",
        "emotional_tone": "warm_cinematic_realism",
        "setting": "contemporary_small_town",
        "time_period": "present_day",
        "era": "modern",                  # NEW: era/decade for visual consistency
        "visual_style": "cinematic_realism",  # NEW: artistic style for images
        "narration_perspective": "third_person_limited",
        "main_character_names": [],
        "character_ages": [],
        "character_descriptions": [],
        "relationship_dynamic": "slow_burn",
        "desired_ending": "satisfying_emotional_payoff",
        "romance_intensity": 6,            # 1-10
        "drama_intensity": 5,
        "mystery_intensity": 4,
        "number_of_episodes": 1,
        "narrator_voice": "warm_female",
        "character_voices": {},
        "music_style": "warm_acoustic_cinematic",
        "language": "en",
        "output_aspect_ratio": "16:9",
        "visual_mode": "economical",
        "provider_preference": "auto",
        "max_budget_usd": 5.00,
        "call_to_action": "Subscribe for more original love stories.",
        "channel_name": "Original Romance Stories",
        "reference_images": [],
        "source_text": "",
    }
    for k, v in defaults.items():
        intake.setdefault(k, v)
    # Validate enums
    if intake["genre"] not in GENRES:
        intake["genre"] = "small_town"
    if intake["format"] not in FORMATS:
        intake["format"] = "long_form"
    if intake["visual_mode"] not in VISUAL_MODES:
        intake["visual_mode"] = "economical"
    # Validate era and visual_style
    from romance.constants import ERAS, VISUAL_STYLES
    if intake.get("era") not in ERAS:
        intake["era"] = "modern"
    if intake.get("visual_style") not in VISUAL_STYLES:
        intake["visual_style"] = "cinematic_realism"
    # If duration unset, use midpoint of format range
    if not intake.get("target_duration"):
        lo, hi = DURATION_RANGE.get(intake["format"], (480, 900))
        intake["target_duration"] = (lo + hi) // 2
    # Compute target word count from duration × WPM
    wpm = WORDS_PER_MINUTE.get(intake["format"], 150)
    intake["target_word_count"] = round(intake["target_duration"] * wpm / 60)
    intake["mvp_demo"] = intake.get("mvp_demo", False)
    return intake


def slugify(text: str) -> str:
    """Convert a premise/title to a filesystem-safe slug."""
    text = re.sub(r"[^A-Za-z0-9\s-]", "", text or "").strip().lower()
    text = re.sub(r"[\s-]+", "-", text)
    # Strip leading/trailing hyphens — the web API's project-id validation
    # requires slugs to start and end with an alphanumeric, and truncation
    # below can leave a dangling hyphen.
    text = text.strip("-")
    return text[:60].strip("-") or "untitled"


class RomanceEngine:
    """Drives the youtube-romance-story pipeline for one project."""

    STAGE_MODULES = {
        "intake": "romance.stages.intake_director",
        "concept": "romance.stages.concept_director",
        "proposal": "romance.stages.concept_director",  # alias for OpenMontage compatibility
        "story_bible": "romance.stages.story_bible_director",
        "outline": "romance.stages.outline_director",
        "script": "romance.stages.script_director",
        "continuity_review": "romance.stages.continuity_review_director",
        "scene_plan": "romance.stages.scene_director",
        "character_assets": "romance.stages.character_assets_director",
        "visual_assets": "romance.stages.visual_assets_director",
        "voice_generation": "romance.stages.voice_director",
        "music_and_sfx": "romance.stages.music_director",
        "compose": "romance.stages.compose_director",
        "quality_review": "romance.stages.quality_review_director",
        "shorts_extraction": "romance.stages.shorts_director",
        "thumbnail_generation": "romance.stages.thumbnail_director",
        "youtube_package": "romance.stages.youtube_package_director",
        "publish": "romance.stages.publish_director",
    }

    def __init__(
        self,
        project_dir: str | Path,
        *,
        pipeline_dir: str | Path | None = None,
        budget_total_usd: float | None = None,
    ) -> None:
        self.project_dir = Path(project_dir)
        self.project_dir.mkdir(parents=True, exist_ok=True)
        # OpenMontage checkpoint dir — separate from project_dir to keep
        # checkpoint files out of the user-visible artifact listing.
        self.pipeline_dir = Path(pipeline_dir) if pipeline_dir else self.project_dir / "pipeline"
        self.pipeline_dir.mkdir(parents=True, exist_ok=True)

        # Asset subdirs
        for sub in [
            "assets/characters", "assets/images", "assets/video",
            "assets/voice", "assets/music", "assets/sfx",
            "assets/captions", "assets/thumbnails", "renders",
            "youtube", "logs",
        ]:
            (self.project_dir / sub).mkdir(parents=True, exist_ok=True)

        # Load manifest
        self.manifest = load_pipeline(PIPELINE_NAME)
        self.stages = get_stage_order(self.manifest)
        self.project_id = self.project_dir.name

        # Load or init project.json
        self.project_json_path = self.project_dir / "project.json"
        if self.project_json_path.exists():
            self.project = json.loads(self.project_json_path.read_text())
        else:
            self.project = {
                "version": "1.0",
                "project_id": self.project_id,
                "pipeline": PIPELINE_NAME,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "stages_completed": [],
                "current_stage": None,
                "intake": None,
            }
            self._save_project()

        # Cost tracker — uses project_dir/cost_log.json
        intake = self.project.get("intake") or {}
        budget = budget_total_usd or intake.get("max_budget_usd", 5.00)
        self.cost_tracker = CostTracker(
            budget_total_usd=budget,
            mode=BudgetMode.WARN,
            cost_log_path=self.project_dir / "cost_log.json",
        )
        # z-ai calls are free for this environment but we still log them
        # so the cost_log has entries. The cost_tracker treats 0.0-USD
        # entries as free.
        self.cost_tracker.approve_tool("zai_chat")
        self.cost_tracker.approve_tool("zai_tts")
        self.cost_tracker.approve_tool("zai_image")
        self.cost_tracker.approve_tool("zai_image_search")
        self.cost_tracker.approve_tool("zai_video")
        self.cost_tracker.approve_tool("comfy_image")
        self.cost_tracker.approve_tool("fish_audio_tts")
        self.cost_tracker.approve_tool("omnivoice_tts")
        self.cost_tracker.approve_tool("pixabay_music")
        self.cost_tracker.approve_tool("piper_tts")
        self.cost_tracker.approve_tool("uploadpost")

    # ---- Public API ----

    def run(self, stage: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run a single stage. Returns the stage's result dict."""
        if stage not in self.STAGE_MODULES:
            raise ValueError(f"Unknown stage: {stage!r}. Known: {list(self.STAGE_MODULES)}")
        module_path = self.STAGE_MODULES[stage]
        import importlib
        mod = importlib.import_module(module_path)
        director = getattr(mod, "run")
        result = director(self, payload or {})
        # Persist result as artifact JSON if it returns one
        if isinstance(result, dict) and result.get("artifact"):
            self._save_artifact(result["artifact"], result.get("data", {}))
        # Write OpenMontage checkpoint
        self._checkpoint(stage, result)
        # Update project.json
        if stage not in self.project["stages_completed"]:
            self.project["stages_completed"].append(stage)
        self.project["current_stage"] = stage
        self._save_project()
        return result

    def run_all(self, until: str | None = None) -> dict[str, Any]:
        """Run every stage from the current resume point to the end (or `until`)."""
        last_result: dict[str, Any] = {}
        for stage in self.stages:
            if until and stage == until:
                last_result = self.run(stage)
                break
            # Skip already-completed stages
            cp = read_checkpoint(self.pipeline_dir, self.project_id, stage)
            if cp and cp.get("status") == "completed":
                continue
            last_result = self.run(stage)
            if last_result.get("error"):
                # Stop on error — caller can resume after fixing
                break
        return last_result

    def run_all_background(self, until: str | None = None) -> str:
        """Start run_all in a background thread. Returns a job_id for polling.

        The job_id can be passed to status() or the web UI's render monitor
        to track progress. The job runs independently of the calling thread.
        """
        import threading
        import time
        job_id = f"{self.project_id}-{int(time.time())}"

        # Store job state on the engine instance
        if not hasattr(self, "_jobs"):
            self._jobs = {}
        self._jobs[job_id] = {
            "status": "running",
            "stage": "starting",
            "started_at": time.time(),
            "errors": [],
            "completed_stages": [],
        }

        def _run():
            try:
                for stage in self.stages:
                    if until and stage == until:
                        break
                    cp = read_checkpoint(self.pipeline_dir, self.project_id, stage)
                    if cp and cp.get("status") == "completed":
                        continue
                    self._jobs[job_id]["stage"] = stage
                    result = self.run(stage)
                    if result.get("error"):
                        self._jobs[job_id]["errors"].append({
                            "stage": stage,
                            "error": result["error"],
                        })
                        self._jobs[job_id]["status"] = "failed"
                        return
                    self._jobs[job_id]["completed_stages"].append(stage)
                self._jobs[job_id]["status"] = "completed"
                self._jobs[job_id]["completed_at"] = time.time()
            except Exception as exc:
                self._jobs[job_id]["status"] = "failed"
                self._jobs[job_id]["errors"].append({"stage": "unknown", "error": str(exc)})

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        return job_id

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        """Get the status of a background job."""
        if not hasattr(self, "_jobs"):
            return None
        return self._jobs.get(job_id)

    def resume(self) -> str | None:
        """Return the next stage that needs to run, or None if pipeline is complete."""
        return get_next_stage(self.pipeline_dir, self.project_id, pipeline_type=PIPELINE_NAME)

    def status(self) -> dict[str, Any]:
        """Return a status snapshot for the render monitor UI."""
        completed = get_completed_stages(self.pipeline_dir, self.project_id, pipeline_type=PIPELINE_NAME)
        return {
            "project_id": self.project_id,
            "project_dir": str(self.project_dir),
            "pipeline": PIPELINE_NAME,
            "stages_total": len(self.stages),
            "stages_completed": len(completed),
            "stages_completed_names": completed,
            "current_stage": self.project.get("current_stage"),
            "next_stage": self.resume(),
            "cost_snapshot": self.cost_tracker.cost_snapshot(),
            "zai_available": zai_available(),
            "artifacts_on_disk": self._list_artifacts(),
        }

    # ---- Helpers used by stage directors ----

    def load_artifact(self, name: str) -> dict[str, Any] | None:
        """Load an artifact JSON by canonical name (e.g. 'story_bible', 'script')."""
        _require_safe_artifact_name(name)
        path = self.project_dir / f"{name}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text())

    def save_artifact(self, name: str, data: dict[str, Any]) -> Path:
        """Persist an artifact JSON. Validates against schema if available."""
        return self._save_artifact(name, data)

    def load_intake(self) -> dict[str, Any]:
        path = self.project_dir / "intake.json"
        if path.exists():
            return json.loads(path.read_text())
        return self.project.get("intake") or {}

    def log(self, stage: str, message: str, **extra: Any) -> None:
        """Append to the project log file."""
        log_path = self.project_dir / "logs" / f"{stage}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "stage": stage,
            "message": message,
            **extra,
        }
        with open(log_path, "a") as f:
            f.write(json.dumps(entry) + "\n")

    def asset_path(self, category: str, filename: str) -> Path:
        """Return an absolute asset path under assets/<category>/. Ensures parent exists."""
        path = self.project_dir / "assets" / category / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    # ---- Internals ----

    def _save_artifact(self, name: str, data: dict[str, Any]) -> Path:
        _require_safe_artifact_name(name)
        # Validate if a schema exists
        try:
            from schemas.artifacts import validate_artifact
            validate_artifact(name, data)
        except Exception as exc:
            # Log but don't crash — stage director may want to save partial work
            self.log("_save_artifact", f"Schema validation failed for {name}: {exc}")
        path = self.project_dir / f"{name}.json"
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        return path

    def _checkpoint(self, stage: str, result: dict[str, Any]) -> None:
        # Build the artifacts dict for this checkpoint
        artifact_name = result.get("artifact")
        artifacts: dict[str, Any] = {}
        if artifact_name and result.get("data"):
            artifacts[artifact_name] = result["data"]
        # Carry over any supplementary artifacts the stage explicitly produced
        for k, v in result.get("extra_artifacts", {}).items():
            artifacts[k] = v

        status = "completed" if not result.get("error") else "failed"
        try:
            write_checkpoint(
                self.pipeline_dir,
                self.project_id,
                stage,
                status,
                artifacts,
                pipeline_type=PIPELINE_NAME,
                checkpoint_policy="guided",
                human_approval_required=False,
                human_approved=True,
                cost_snapshot=self.cost_tracker.cost_snapshot(),
                error=result.get("error"),
                metadata={"duration_seconds": result.get("duration_seconds")},
            )
        except Exception as exc:
            # Checkpoint validation can fail for legitimate reasons (e.g. partial
            # artifacts during in_progress). Log and continue.
            self.log("_checkpoint", f"Checkpoint write failed for {stage}: {exc}")

    def _save_project(self) -> None:
        self.project_json_path.write_text(json.dumps(self.project, indent=2))

    def _list_artifacts(self) -> list[str]:
        return sorted(
            p.name for p in self.project_dir.glob("*.json")
            if p.name not in ("project.json", "cost_log.json", "intake.json")
        )


def create_project(premise: str, intake: dict[str, Any] | None = None, *, projects_root: Path | None = None) -> RomanceEngine:
    """Create a new project from a premise. Returns a ready-to-run engine."""
    projects_root = projects_root or PROJECTS_ROOT
    projects_root.mkdir(parents=True, exist_ok=True)
    slug = slugify(premise)
    # Ensure unique slug
    base = slug
    n = 2
    while (projects_root / slug).exists():
        slug = f"{base}-{n}"
        n += 1
    project_dir = projects_root / slug
    engine = RomanceEngine(project_dir)
    full_intake = load_intake_defaults({**intake, "premise": premise})
    # Save intake.json
    (project_dir / "intake.json").write_text(
        json.dumps(full_intake, indent=2, ensure_ascii=False)
    )
    engine.project["intake"] = full_intake
    engine._save_project()
    return engine
