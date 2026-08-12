"""Stage 16: YouTube Package.

Generates the complete YouTube metadata package: 10 title options, 3
recommended titles, description, chapters, tags, hashtags, pinned comment,
community post, thumbnail text options (already in thumbnail_concept),
playlist & end-screen recs, 3 Shorts hooks + 3 Shorts scripts, file names.

Writes individual .md files to projects/<slug>/youtube/ for easy upload.
"""

from __future__ import annotations

import json
from pathlib import Path

from romance.llm_bridge import zai_available
from romance.stages._shared import ROMANCE_SYSTEM_PROMPT, SAFETY_PROMPT, brief_meta, llm_json, timed


YOUTUBE_PACKAGE_PROMPT = """You are producing the complete YouTube metadata package for a romance video.

EPISODE TITLE: {title}
LOGLINE: {logline}
CENTRAL CONFLICT: {central_conflict}
MYSTERY PROMISE: {mystery_promise}
PAYOFF: {payoff}
FINAL BUTTON: {final_button}
GENRE: {genre}
CHANNEL: {channel_name}
CALL TO ACTION: {cta}

SCRIPT SECTIONS (for chapters):
{script_block}

Generate:
- 10 emotionally specific, curiosity-driven title options (NO keyword stuffing).
  Each title ≤ 70 characters.
- 3 recommended titles (pick the strongest).
- opening_description_lines: the first 2-3 lines of the description (before the fold) — must hook the reader.
- description: the full description (3-5 paragraphs, includes the premise, what's at stake, and a CTA).
- chapters: one per major script beat (use the section's start_seconds as time_seconds).
- tags: 15-25 relevant tags.
- hashtags: 3-5 hashtags.
- pinned_comment: a comment that deepens engagement (e.g. a question or behind-the-scenes note).
- community_post: a short post for the channel's community tab.
- playlist_recommendation: a suggested playlist name.
- end_screen_recommendation: a suggested end-screen video link (text only).
- suggested_next_episode: a hook for the next video (even if standalone).
- shorts_hooks: 3 distinct Shorts hook lines.
- shorts_scripts: 3 Shorts scripts (title, hook, body, cliffhanger, target_duration_seconds 45-90).
- file_names: recommended file names for the long-form video, Shorts, and thumbnails.

Respond with ONLY this JSON (no fences):
{{
  "version": "1.0",
  "project_id": "{project_id}",
  "titles": ["<10 title options>"],
  "recommended_titles": ["<3 recommended titles>"],
  "opening_description_lines": ["<2-3 lines>"],
  "description": "<full description>",
  "chapters": [
    {{"time_seconds": 0, "title": "<chapter title>"}}
  ],
  "tags": ["<tag>", "..."],
  "hashtags": ["<hashtag>", "..."],
  "pinned_comment": "<text>",
  "community_post": "<text>",
  "playlist_recommendation": "<text>",
  "end_screen_recommendation": "<text>",
  "suggested_next_episode": "<text>",
  "shorts_hooks": ["<hook>", "<hook>", "<hook>"],
  "shorts_scripts": [
    {{"title": "<title>", "hook": "<text>", "body": "<text>", "cliffhanger": "<text>", "target_duration_seconds": 60}}
  ],
  "file_names": {{
    "long_form_video": "<filename.mp4>",
    "short_video": ["<short1.mp4>", "<short2.mp4>"],
    "thumbnail": ["<thumb1.png>", "<thumb2.png>", "<thumb3.png>"]
  }}
}}{SAFETY_PROMPT}
"""


def run(engine, payload: dict) -> dict:
    return timed(lambda: _run(engine, payload))


def _run(engine, payload: dict) -> dict:
    proposal = engine.load_artifact("proposal_packet")
    script = engine.load_artifact("script")
    render_report = engine.load_artifact("render_report")
    brief = engine.load_artifact("brief") or {}
    if not proposal or not script:
        return {"error": "Missing proposal_packet or script"}

    concept = proposal.get("metadata", {}).get("selected_concept", proposal.get("selected_concept", {}))
    meta = brief_meta(brief)
    script_block = "\n".join(
        f"- {s['id']} ({s.get('start_seconds',0):.1f}s): {s.get('label','')} — {s.get('text','')[:100]}"
        for s in script.get("sections", [])
    )

    if payload.get("youtube_package_override"):
        data = payload["youtube_package_override"]
    elif not zai_available():
        return {"error": "z-ai CLI not available — cannot generate YouTube package."}
    else:
        try:
            data = llm_json(
                YOUTUBE_PACKAGE_PROMPT.format(
                    title=concept.get("title", ""),
                    logline=concept.get("logline", ""),
                    central_conflict=concept.get("central_conflict", ""),
                    mystery_promise=concept.get("mystery_promise", ""),
                    payoff=concept.get("payoff", ""),
                    final_button=concept.get("final_button", ""),
                    genre=meta.get("genre_label", meta.get("genre", "")),
                    channel_name=meta.get("channel_name", ""),
                    cta=brief.get("cta", ""),
                    script_block=script_block,
                    project_id=engine.project_id,
                    SAFETY_PROMPT=SAFETY_PROMPT,
                ),
                system=ROMANCE_SYSTEM_PROMPT,
            )
        except Exception as exc:
            return {"error": f"LLM call failed: {exc}"}

    data["version"] = "1.0"
    data["project_id"] = engine.project_id

    # Validate required fields
    if len(data.get("titles", [])) < 10:
        # Pad if short
        while len(data.get("titles", [])) < 10:
            data.setdefault("titles", []).append(f"{concept.get('title','')} — Part {len(data['titles'])+1}")
    if len(data.get("recommended_titles", [])) < 3:
        data["recommended_titles"] = data.get("titles", [])[:3]

    # Write individual .md files for easy upload
    yt_dir = engine.project_dir / "youtube"
    yt_dir.mkdir(parents=True, exist_ok=True)
    (yt_dir / "titles.md").write_text(
        "# Title Options\n\n"
        + "\n".join(f"- {t}" for t in data.get("titles", []))
        + "\n\n## Recommended\n\n"
        + "\n".join(f"1. {t}" for t in data.get("recommended_titles", []))
    )
    (yt_dir / "description.md").write_text(
        "\n".join(data.get("opening_description_lines", []))
        + "\n\n"
        + data.get("description", "")
    )
    (yt_dir / "chapters.md").write_text(
        "\n".join(
            f"{int(c['time_seconds'])//60:02d}:{int(c['time_seconds'])%60:02d} {c['title']}"
            for c in data.get("chapters", [])
        )
    )
    (yt_dir / "tags.md").write_text(
        "Tags: " + ", ".join(data.get("tags", []))
        + "\n\nHashtags: " + " ".join(data.get("hashtags", []))
    )
    (yt_dir / "pinned-comment.md").write_text(data.get("pinned_comment", ""))
    (yt_dir / "community-post.md").write_text(data.get("community_post", ""))
    (yt_dir / "shorts.md").write_text(
        "# Shorts Hooks\n\n"
        + "\n".join(f"- {h}" for h in data.get("shorts_hooks", []))
        + "\n\n# Shorts Scripts\n\n"
        + "\n\n".join(
            f"## {s['title']}\nHook: {s['hook']}\nBody: {s['body']}\nCliffhanger: {s['cliffhanger']}\nTarget: {s.get('target_duration_seconds',60)}s"
            for s in data.get("shorts_scripts", [])
        )
    )

    engine.log("youtube_package",
               "YouTube package generated",
               titles=len(data.get("titles", [])),
               chapters=len(data.get("chapters", [])))
    return {
        "artifact": "youtube_package",
        "data": data,
    }
