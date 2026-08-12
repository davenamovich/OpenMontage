"""YouTube Romance Story Engine.

A modular extension to OpenMontage that turns a one-sentence romance premise
into a complete, faceless YouTube video package. Drives the
`youtube-romance-story` pipeline manifest via Python so it can be called from
the CLI, tests, or the FastAPI web UI.

Public API:
    from romance import RomanceEngine, load_intake_defaults, GENRES, FORMATS

Typical use:
    engine = RomanceEngine(project_dir="projects/diner-friday")
    engine.run("intake", intake_dict)
    engine.run("concept")
    engine.run("story_bible")
    ...
    engine.run("publish")
"""

from romance.engine import RomanceEngine, load_intake_defaults
from romance.constants import GENRES, FORMATS, VISUAL_MODES, EMOTIONAL_BEATS, RETENTION_BEATS

__all__ = [
    "RomanceEngine",
    "load_intake_defaults",
    "GENRES",
    "FORMATS",
    "VISUAL_MODES",
    "EMOTIONAL_BEATS",
    "RETENTION_BEATS",
]
