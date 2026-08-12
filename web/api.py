"""FastAPI backend for the YouTube Romance Story Engine.

Provides REST endpoints for:
  - Project CRUD (list, create, get status, delete)
  - Stage execution (run a single stage or the full pipeline)
  - Artifact access (get/edit script, scene_plan, etc.)
  - Provider status (ComfyUI, z-ai, ffmpeg)
  - Render monitor (poll progress, cost, logs)

Run with:
    python -m web.api
    # or
    uvicorn web.api:app --reload --port 8000
"""

from __future__ import annotations

import json
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from romance.engine import PROJECTS_ROOT, RomanceEngine, create_project, load_intake_defaults
from romance.constants import (
    GENRES, FORMATS, VISUAL_MODES, GENRE_LABELS, FORMAT_LABELS, VISUAL_MODE_LABELS,
    ERAS, ERA_LABELS, VISUAL_STYLES, VISUAL_STYLE_LABELS,
)

app = FastAPI(title="YouTube Romance Story Engine", version="1.0")


@app.get("/api/health")
async def health():
    """Health check endpoint for gateway/service discovery."""
    return {"status": "ok", "service": "romance-engine", "version": "1.0"}


@app.get("/health")
async def health_root():
    """Root health check."""
    return {"status": "ok"}

# ---- Input validation ----

# Project ids are slugs produced by romance.engine.slugify (lowercase
# alphanumerics + hyphens). Reject anything else — in particular anything
# containing '.', '/', '\\', or empty — so project_id can never escape
# PROJECTS_ROOT.
PROJECT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,127}$")

# Artifact / stage / log names are snake_case identifiers (e.g.
# 'story_bible', 'quality_review').
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_]{0,127}$")


def _require_project_id(project_id: str) -> None:
    if not PROJECT_ID_RE.fullmatch(project_id or ""):
        raise HTTPException(status_code=400, detail=f"Invalid project id: {project_id!r}")


def _require_name(name: str, what: str = "name") -> None:
    if not NAME_RE.fullmatch(name or ""):
        raise HTTPException(status_code=400, detail=f"Invalid {what}: {name!r}")


# ---- Background job tracking ----

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


# ---- Models ----

class CreateProjectRequest(BaseModel):
    premise: str
    genre: str | None = None
    format: str | None = None
    target_duration: int | None = None
    visual_mode: str | None = None
    era: str | None = None
    visual_style: str | None = None
    max_budget_usd: float | None = None
    output_aspect_ratio: str | None = None
    channel_name: str | None = None
    title: str | None = None
    main_character_names: list[str] | None = None
    character_ages: list[int] | None = None
    character_descriptions: list[str] | None = None
    narrator_voice: str | None = None
    music_style: str | None = None
    language: str | None = None
    emotional_tone: str | None = None
    setting: str | None = None
    narration_perspective: str | None = None
    desired_ending: str | None = None


class RunStageRequest(BaseModel):
    stage: str
    payload: dict | None = None


class UpdateArtifactRequest(BaseModel):
    data: dict


# ---- Helpers ----

def _engine(project_id: str) -> RomanceEngine:
    """Resolve a project_id to a RomanceEngine, rejecting traversal attempts."""
    _require_project_id(project_id)
    project_dir = PROJECTS_ROOT / project_id
    # Defense in depth: even if the regex is ever bypassed (encoded separators
    # etc.), make sure the resolved path stays strictly inside PROJECTS_ROOT.
    try:
        root = PROJECTS_ROOT.resolve()
        resolved = project_dir.resolve()
    except OSError:
        raise HTTPException(status_code=400, detail="Invalid project path")
    if not resolved.is_relative_to(root) or resolved == root:
        raise HTTPException(status_code=400, detail=f"Invalid project path: {project_id!r}")
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    return RomanceEngine(project_dir)


def _provider_status() -> dict:
    """Check which providers are available."""
    from tools.base_tool import ToolStatus

    providers = {}

    # ComfyUI
    try:
        from tools.llm.comfy_image import ComfyImage
        tool = ComfyImage()
        providers["comfyui"] = {
            "available": tool.get_status() == ToolStatus.AVAILABLE,
            "name": "ComfyUI (Local Stable Diffusion)",
            "url": __import__("os").environ.get("COMFYUI_URL", "http://localhost:8188"),
        }
    except Exception:
        providers["comfyui"] = {"available": False, "name": "ComfyUI"}

    # z-ai
    try:
        from tools.llm.zai_image import ZaiImage
        from tools.llm.zai_tts import ZaiTTS
        img = ZaiImage()
        tts = ZaiTTS()
        providers["zai_image"] = {
            "available": img.get_status() == ToolStatus.AVAILABLE,
            "name": "Z-AI Image (Cloud)",
        }
        providers["zai_tts"] = {
            "available": tts.get_status() == ToolStatus.AVAILABLE,
            "name": "Z-AI TTS (Cloud)",
        }
    except Exception:
        pass

    # ffmpeg
    import shutil as sh
    providers["ffmpeg"] = {
        "available": bool(sh.which("ffmpeg")),
        "name": "FFmpeg",
        "version": _ffmpeg_version(),
    }

    # whisper
    try:
        import faster_whisper
        providers["whisper"] = {
            "available": True,
            "name": "Faster-Whisper (Local ASR)",
            "version": faster_whisper.__version__,
        }
    except Exception:
        providers["whisper"] = {"available": False, "name": "Faster-Whisper"}

    return providers


def _ffmpeg_version() -> str:
    import subprocess
    try:
        proc = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=5)
        return proc.stdout.split("\n")[0] if proc.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


# ---- Routes: pages ----

@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the main SPA."""
    html_path = Path(__file__).parent / "static" / "index.html"
    return HTMLResponse(content=html_path.read_text(), status_code=200)


# ---- Routes: metadata ----

@app.get("/api/meta")
async def get_metadata():
    """Return genres, formats, visual modes, eras, styles, and labels for the intake form."""
    return {
        "genres": [{"value": g, "label": GENRE_LABELS.get(g, g)} for g in GENRES],
        "formats": [{"value": f, "label": FORMAT_LABELS.get(f, f)} for f in FORMATS],
        "visual_modes": [{"value": v, "label": VISUAL_MODE_LABELS.get(v, v)} for v in VISUAL_MODES],
        "eras": [{"value": e, "label": ERA_LABELS.get(e, e)} for e in ERAS],
        "visual_styles": [{"value": s, "label": VISUAL_STYLE_LABELS.get(s, s)} for s in VISUAL_STYLES],
        "defaults": load_intake_defaults({}),
    }


@app.get("/api/providers")
async def get_providers():
    """Return provider availability status."""
    return _provider_status()


@app.get("/api/tts-providers")
async def get_tts_providers():
    """Return all TTS providers and their availability."""
    from romance.stages._shared import list_tts_providers, get_best_tts_tool
    providers = list_tts_providers()
    best, best_name = get_best_tts_tool()
    return {
        "providers": providers,
        "best_available": best_name,
    }


@app.get("/api/publish-providers")
async def get_publish_providers():
    """Return publishing tool availability."""
    from romance.stages._shared import get_publish_tool
    from tools.llm.uploadpost import SUPPORTED_PLATFORMS
    tool, name = get_publish_tool()
    import os
    return {
        "uploadpost": {
            "available": name is not None,
            "name": "UploadPost (22+ social networks)",
            "platforms": SUPPORTED_PLATFORMS,
            "api_key_set": bool(os.environ.get("UPLOADPOST_API_KEY")),
            "user_set": bool(os.environ.get("UPLOADPOST_USER")),
            "install_instructions": (
                "1. Sign up at https://upload-post.com\n"
                "2. Connect social accounts (YouTube, TikTok, Instagram, etc.)\n"
                "3. Create a user profile name\n"
                "4. Set env vars:\n"
                "   export UPLOADPOST_API_KEY=your_key\n"
                "   export UPLOADPOST_USER=your_profile_name\n"
                "Free plan: 10 uploads/month"
            ),
        },
    }


class PublishRequest(BaseModel):
    platforms: list[str]
    publish_shorts: bool = True
    publish_thumbnails: bool = False


# ---- Routes: projects ----

@app.get("/api/projects")
async def list_projects():
    """List all projects with their status."""
    projects = []
    if not PROJECTS_ROOT.exists():
        return {"projects": []}
    for p in sorted(PROJECTS_ROOT.iterdir()):
        if not p.is_dir():
            continue
        try:
            engine = RomanceEngine(p)
            status = engine.status()
            projects.append({
                "project_id": status["project_id"],
                "stages_completed": status["stages_completed"],
                "stages_total": status["stages_total"],
                "current_stage": status["current_stage"],
                "next_stage": status["next_stage"],
                "cost": status["cost_snapshot"],
                "title": (engine.load_artifact("brief") or {}).get("title", status["project_id"]),
                "premise": (engine.load_intake() or {}).get("premise", ""),
            })
        except Exception as exc:
            projects.append({
                "project_id": p.name,
                "error": str(exc),
                "stages_completed": 0,
                "stages_total": 17,
            })
    return {"projects": projects}


@app.post("/api/projects")
async def create_project_endpoint(req: CreateProjectRequest):
    """Create a new project from a premise."""
    intake = {}
    for field in ["genre", "format", "target_duration", "visual_mode", "era", "visual_style",
                  "max_budget_usd", "output_aspect_ratio", "channel_name", "title",
                  "main_character_names", "character_ages", "character_descriptions",
                  "narrator_voice", "music_style", "language", "emotional_tone",
                  "setting", "narration_perspective", "desired_ending"]:
        val = getattr(req, field, None)
        if val is not None:
            intake[field] = val
    engine = create_project(req.premise, intake)
    return {
        "project_id": engine.project_id,
        "project_dir": str(engine.project_dir),
        "status": engine.status(),
    }


@app.post("/api/projects/{project_id}/auto-run")
async def auto_run_pipeline(project_id: str, until: str | None = None):
    """Start the full pipeline in the background for an existing project.

    This is the same as /pipeline but returns immediately with a job_id.
    Use GET /api/projects/{project_id}/jobs/{job_id} to poll progress.
    """
    engine = _engine(project_id)
    job_id = f"{project_id}-{int(time.time())}"

    def _run():
        with _jobs_lock:
            _jobs[job_id] = {"status": "running", "stage": "starting", "started_at": time.time(), "completed_stages": []}
        try:
            for stage in engine.stages:
                if until and stage == until:
                    break
                with _jobs_lock:
                    _jobs[job_id]["stage"] = stage
                result = engine.run(stage)
                with _jobs_lock:
                    if result.get("error"):
                        _jobs[job_id]["status"] = "failed"
                        _jobs[job_id]["error"] = result["error"]
                        return
                    _jobs[job_id]["completed_stages"].append(stage)
            with _jobs_lock:
                _jobs[job_id]["status"] = "completed"
                _jobs[job_id]["completed_at"] = time.time()
        except Exception as exc:
            with _jobs_lock:
                _jobs[job_id]["status"] = "failed"
                _jobs[job_id]["error"] = str(exc)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return {"job_id": job_id, "status": "started"}


@app.post("/api/auto-create-run")
async def auto_create_and_run(req: CreateProjectRequest):
    """Create a new project AND immediately start the full pipeline.

    Combines POST /api/projects + POST /api/projects/{id}/auto-run in one call.
    Returns the project_id and job_id for monitoring.
    """
    # Create the project
    intake = {}
    for field in ["genre", "format", "target_duration", "visual_mode", "era", "visual_style",
                  "max_budget_usd", "output_aspect_ratio", "channel_name", "title",
                  "main_character_names", "character_ages", "character_descriptions",
                  "narrator_voice", "music_style", "language", "emotional_tone",
                  "setting", "narration_perspective", "desired_ending"]:
        val = getattr(req, field, None)
        if val is not None:
            intake[field] = val
    engine = create_project(req.premise, intake)
    project_id = engine.project_id

    # Start the pipeline in background
    job_id = f"{project_id}-{int(time.time())}"

    def _run():
        with _jobs_lock:
            _jobs[job_id] = {"status": "running", "stage": "starting", "started_at": time.time(), "completed_stages": []}
        try:
            for stage in engine.stages:
                with _jobs_lock:
                    _jobs[job_id]["stage"] = stage
                result = engine.run(stage)
                with _jobs_lock:
                    if result.get("error"):
                        _jobs[job_id]["status"] = "failed"
                        _jobs[job_id]["error"] = result["error"]
                        return
                    _jobs[job_id]["completed_stages"].append(stage)
            with _jobs_lock:
                _jobs[job_id]["status"] = "completed"
                _jobs[job_id]["completed_at"] = time.time()
        except Exception as exc:
            with _jobs_lock:
                _jobs[job_id]["status"] = "failed"
                _jobs[job_id]["error"] = str(exc)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    return {
        "project_id": project_id,
        "job_id": job_id,
        "status": "started",
        "message": f"Project created and pipeline started. Monitor at /api/projects/{project_id}/jobs/{job_id}",
    }


@app.get("/api/projects/{project_id}")
async def get_project(project_id: str):
    """Get full project status + all artifacts."""
    engine = _engine(project_id)
    status = engine.status()
    artifacts = {}
    for name in status.get("artifacts_on_disk", []):
        artifact_name = name.replace(".json", "")
        try:
            data = engine.load_artifact(artifact_name)
        except ValueError:
            # Skip non-conforming artifact files (e.g. legacy hyphenated names)
            continue
        if data:
            artifacts[artifact_name] = data
    intake = engine.load_intake()
    return {
        "status": status,
        "intake": intake,
        "artifacts": artifacts,
    }


@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: str):
    """Delete a project."""
    engine = _engine(project_id)
    shutil.rmtree(engine.project_dir)
    return {"deleted": project_id}


# ---- Routes: stage execution ----

@app.post("/api/projects/{project_id}/stages")
async def run_stage(project_id: str, req: RunStageRequest):
    """Run a single stage synchronously (for quick LLM stages)."""
    engine = _engine(project_id)
    _require_name(req.stage, "stage name")
    try:
        result = engine.run(req.stage, req.payload or {})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "stage": req.stage,
        "result": result,
        "status": engine.status(),
    }


@app.post("/api/projects/{project_id}/pipeline")
async def run_pipeline(project_id: str, background: bool = True):
    """Run the full pipeline. Returns a job_id for progress polling."""
    engine = _engine(project_id)
    job_id = f"{project_id}-{int(time.time())}"

    def _run():
        with _jobs_lock:
            _jobs[job_id] = {"status": "running", "stage": "starting", "started_at": time.time()}
        try:
            for stage in engine.stages:
                with _jobs_lock:
                    _jobs[job_id]["stage"] = stage
                result = engine.run(stage)
                with _jobs_lock:
                    _jobs[job_id]["last_result"] = {
                        "stage": stage,
                        "error": result.get("error"),
                        "duration": result.get("duration_seconds"),
                    }
                if result.get("error"):
                    with _jobs_lock:
                        _jobs[job_id]["status"] = "failed"
                        _jobs[job_id]["error"] = result["error"]
                    return
            with _jobs_lock:
                _jobs[job_id]["status"] = "completed"
                _jobs[job_id]["completed_at"] = time.time()
        except Exception as exc:
            with _jobs_lock:
                _jobs[job_id]["status"] = "failed"
                _jobs[job_id]["error"] = str(exc)

    if background:
        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        return {"job_id": job_id, "status": "started"}
    else:
        _run()
        with _jobs_lock:
            return {"job_id": job_id, **_jobs.get(job_id, {})}


@app.get("/api/projects/{project_id}/jobs/{job_id}")
async def get_job_status(project_id: str, job_id: str):
    """Poll a background job's progress."""
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    engine = _engine(project_id)
    return {
        **job,
        "project_status": engine.status(),
    }


# ---- Routes: artifacts ----

@app.get("/api/projects/{project_id}/artifacts/{name}")
async def get_artifact(project_id: str, name: str):
    """Get a specific artifact."""
    engine = _engine(project_id)
    _require_name(name, "artifact name")
    data = engine.load_artifact(name)
    if not data:
        raise HTTPException(status_code=404, detail=f"Artifact not found: {name}")
    return data


@app.put("/api/projects/{project_id}/artifacts/{name}")
async def update_artifact(project_id: str, name: str, req: UpdateArtifactRequest):
    """Update an artifact (e.g., user edits the script)."""
    engine = _engine(project_id)
    _require_name(name, "artifact name")
    path = engine.save_artifact(name, req.data)
    return {"saved": str(path)}


# ---- Routes: assets ----

@app.get("/api/projects/{project_id}/assets")
async def list_assets(project_id: str):
    """List all generated asset files."""
    engine = _engine(project_id)
    assets_dir = engine.project_dir / "assets"
    files = []
    if assets_dir.exists():
        for f in assets_dir.rglob("*"):
            if f.is_file():
                rel = f.relative_to(engine.project_dir)
                files.append({
                    "path": str(rel),
                    "size": f.stat().st_size,
                    "category": str(rel).split("/")[1] if len(str(rel).split("/")) > 1 else "other",
                })
    renders_dir = engine.project_dir / "renders"
    if renders_dir.exists():
        for f in renders_dir.iterdir():
            if f.is_file():
                files.append({
                    "path": f"renders/{f.name}",
                    "size": f.stat().st_size,
                    "category": "render",
                })
    return {"assets": files}


# ---- Routes: logs ----

@app.get("/api/projects/{project_id}/logs/{stage}")
async def get_logs(project_id: str, stage: str):
    """Get logs for a specific stage."""
    engine = _engine(project_id)
    _require_name(stage, "stage name")
    log_path = engine.project_dir / "logs" / f"{stage}.log"
    if not log_path.exists():
        return {"logs": []}
    entries = []
    for line in log_path.read_text().strip().split("\n"):
        if line:
            try:
                entries.append(json.loads(line))
            except Exception:
                entries.append({"raw": line})
    return {"logs": entries}


@app.post("/api/projects/{project_id}/publish")
async def publish_to_social(project_id: str, req: PublishRequest):
    """Publish the project's video + shorts to social media via UploadPost."""
    engine = _engine(project_id)
    result = engine.run("publish", {"platforms": req.platforms})
    return {
        "stage": "publish",
        "result": result,
        "status": engine.status(),
    }


# ---- Routes: asset file serving ----

@app.get("/api/projects/{project_id}/assets/{file_path:path}")
async def serve_asset(project_id: str, file_path: str):
    """Serve an asset file (image, audio, video) from the project directory."""
    engine = _engine(project_id)
    project_root = engine.project_dir.resolve()
    # Try multiple base dirs
    for base in ["assets", "renders"]:
        # Resolve and verify containment before touching the filesystem —
        # blocks '..' segments (encoded or literal) escaping the project dir.
        try:
            full = (engine.project_dir / base / file_path).resolve()
        except OSError:
            continue
        if not full.is_relative_to(project_root):
            continue
        if full.exists() and full.is_file():
            # Determine content type
            ext = full.suffix.lower()
            content_types = {
                ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".mp4": "video/mp4", ".wav": "audio/wav", ".mp3": "audio/mpeg",
                ".srt": "text/plain", ".vtt": "text/vtt",
                ".md": "text/plain", ".json": "application/json",
            }
            ct = content_types.get(ext, "application/octet-stream")
            return FileResponse(str(full), media_type=ct)
    raise HTTPException(status_code=404, detail=f"Asset not found: {file_path}")


# ---- Mount static files ----

static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


def main():
    """Run the server."""
    import uvicorn
    print("Starting YouTube Romance Story Engine UI at http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")


if __name__ == "__main__":
    main()
