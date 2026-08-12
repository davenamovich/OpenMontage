"""Stage 17: Publish.

Final stage. Verifies all expected deliverables exist, writes the
`publish_log` artifact, and optionally publishes to social media platforms
via UploadPost (YouTube, TikTok, Instagram, etc.) when the user has
configured the UploadPost API key.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from romance.stages._shared import get_publish_tool, render_output, timed


EXPECTED_FILES = [
    "renders/youtube-16x9.mp4",
    "renders/clean-video.mp4",
    "assets/captions/captions.srt",
    "assets/captions/captions.vtt",
    "youtube/titles.md",
    "youtube/description.md",
    "youtube/chapters.md",
    "youtube/tags.md",
    "youtube/pinned-comment.md",
    "youtube/shorts.md",
]


def run(engine, payload: dict) -> dict:
    return timed(lambda: _run(engine, payload))


def _run(engine, payload: dict) -> dict:
    render_report = engine.load_artifact("render_report")
    youtube_package = engine.load_artifact("youtube_package")
    shorts_package = engine.load_artifact("shorts_package")
    thumbnail_concept = engine.load_artifact("thumbnail_concept")
    if not render_report or not youtube_package:
        return {"error": "Missing render_report or youtube_package"}

    # Verify expected files
    verified_files: dict[str, bool] = {}
    for relpath in EXPECTED_FILES:
        full = engine.project_dir / relpath
        verified_files[relpath] = full.exists()

    # Add Short and thumbnail files
    for short in (shorts_package or {}).get("shorts", []):
        rp = short.get("rendered_path", "")
        verified_files[f"short:{short['id']}"] = bool(rp and Path(rp).exists())
    for c in (thumbnail_concept or {}).get("concepts", []):
        rp = c.get("rendered_image_path", "")
        verified_files[f"thumbnail:{c['id']}"] = bool(rp and Path(rp).exists())

    all_present = all(verified_files.values())

    # Get the final video path
    final_video = render_output(render_report, "final_video")

    # Optional: publish to social media via UploadPost
    publish_results = []
    platforms = payload.get("platforms", [])
    publish_tool, publish_name = get_publish_tool()

    if platforms and publish_tool and final_video and Path(final_video).exists():
        # Use the first recommended title + description from youtube_package
        title = (youtube_package.get("recommended_titles") or ["Untitled"])[0]
        description = youtube_package.get("description", "")
        tags = youtube_package.get("tags", [])

        engine.log("publish", f"Publishing to platforms: {platforms}")

        # Publish the long-form video
        result = publish_tool.execute({
            "operation": "upload_video",
            "video_path": final_video,
            "title": title,
            "description": description,
            "platforms": platforms,
            "tags": tags,
        })
        if result.success:
            publish_results.append({
                "type": "long_form_video",
                "title": title,
                "platforms": platforms,
                "request_id": result.data.get("request_id"),
                "response": result.data.get("response", {}),
            })
            engine.log("publish", f"Long-form video published: {result.data.get('request_id')}")
        else:
            publish_results.append({
                "type": "long_form_video",
                "error": result.error,
            })
            engine.log("publish", f"Long-form publish failed: {result.error}")

        # Publish Shorts to TikTok/Instagram if requested
        if "tiktok" in platforms or "instagram" in platforms:
            short_platforms = [p for p in platforms if p in ("tiktok", "instagram", "youtube")]
            for short in (shorts_package or {}).get("shorts", []):
                short_path = short.get("rendered_path", "")
                if short_path and Path(short_path).exists():
                    short_result = publish_tool.execute({
                        "operation": "upload_video",
                        "video_path": short_path,
                        "title": short.get("title", f"{title} - Short"),
                        "description": short.get("hook", description[:200]),
                        "platforms": short_platforms,
                    })
                    if short_result.success:
                        publish_results.append({
                            "type": "short",
                            "title": short.get("title"),
                            "platforms": short_platforms,
                            "request_id": short_result.data.get("request_id"),
                        })
                        engine.log("publish", f"Short published: {short.get('title')}")

        # Publish thumbnails as photos if requested
        if "instagram" in platforms or "pinterest" in platforms:
            thumb_platforms = [p for p in platforms if p in ("instagram", "pinterest", "facebook")]
            thumb_paths = []
            for c in (thumbnail_concept or {}).get("concepts", []):
                rp = c.get("rendered_image_path", "")
                if rp and Path(rp).exists():
                    thumb_paths.append(rp)
            if thumb_paths:
                photo_result = publish_tool.execute({
                    "operation": "upload_photos",
                    "photo_paths": thumb_paths[:3],  # max 3
                    "title": title,
                    "description": description[:200],
                    "platforms": thumb_platforms,
                })
                if photo_result.success:
                    publish_results.append({
                        "type": "thumbnails",
                        "platforms": thumb_platforms,
                        "request_id": photo_result.data.get("request_id"),
                    })
    elif platforms and not publish_tool:
        engine.log("publish", "UploadPost not configured — skipping social media publishing. Set UPLOADPOST_API_KEY to enable.")

    publish_log = {
        "version": "1.0",
        "entries": [
            {
                "platform": "local" if not publish_results else ",".join(platforms),
                "status": "exported" if all_present else "failed",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "export_path": str(engine.project_dir / "renders"),
            }
        ],
        "metadata": {
            "stage": "publish",
            "published_at": datetime.now(timezone.utc).isoformat(),
            "status": "ready" if all_present else "incomplete",
            "deliverables": verified_files,
            "summary": {
                "long_form_video": final_video,
                "clean_video": render_output(render_report, "clean_video"),
                "captions_srt": render_output(render_report, "srt"),
                "captions_vtt": render_output(render_report, "vtt"),
                "shorts": [s.get("rendered_path") for s in (shorts_package or {}).get("shorts", [])],
                "thumbnails": [c.get("rendered_image_path") for c in (thumbnail_concept or {}).get("concepts", [])],
                "recommended_titles": youtube_package.get("recommended_titles", []),
                "chapters": youtube_package.get("chapters", []),
                "tags": youtube_package.get("tags", []),
            },
            "social_publishing": {
                "enabled": bool(publish_results),
                "platforms_requested": platforms,
                "uploadpost_available": publish_name is not None,
                "results": publish_results,
            },
            "cost_snapshot": engine.cost_tracker.cost_snapshot(),
        },
    }
    engine.log("publish",
               "Publish package complete",
               all_present=all_present,
               files_verified=len(verified_files),
               social_published=len(publish_results))
    return {
        "artifact": "publish_log",
        "data": publish_log,
    }
