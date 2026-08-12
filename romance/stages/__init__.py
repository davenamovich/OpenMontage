"""Stage directors for the youtube-romance-story pipeline.

Each module exposes a `run(engine, payload) -> dict` function that performs
the stage's work and returns a result dict with at minimum:
  - artifact: the canonical artifact name (e.g. "story_bible")
  - data: the artifact payload (dict)
  - error: optional error string if the stage failed
  - extra_artifacts: optional dict of {name: data} for supplementary outputs
  - duration_seconds: how long the stage took
"""
