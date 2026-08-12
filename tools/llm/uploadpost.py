"""UploadPost social media publishing tool.

Calls the UploadPost API (https://api.upload-post.com) to publish videos,
photos, and text to 22+ social networks with a single API call.

Supported platforms: YouTube, TikTok, Instagram, LinkedIn, Facebook, X (Twitter),
Threads, Pinterest, Bluesky, Reddit, Discord, Telegram, Google Business Profile.

Auth: Set UPLOADPOST_API_KEY in your environment.
User: Set UPLOADPOST_USER to your connected social account profile name.

Endpoints:
  POST /api/upload         — upload video (multipart: video, title, user, platform[])
  POST /api/upload_photos  — upload photos (multipart: photos[], user, platform[], title, description)
  GET  /api/status/{id}    — check upload status
  GET  /api/analytics/{id} — get engagement metrics

The romance pipeline uses this in the publish stage to push finished videos
directly to YouTube (and optionally TikTok/Instagram for Shorts).
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any

from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    RetryPolicy,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolStatus,
    ToolTier,
)


UPLOADPOST_API_URL = os.environ.get("UPLOADPOST_API_URL", "https://api.upload-post.com")

# All supported platforms
SUPPORTED_PLATFORMS = [
    "youtube", "tiktok", "instagram", "linkedin", "facebook",
    "twitter", "threads", "pinterest", "bluesky", "reddit",
    "discord", "telegram", "google_business",
]


class UploadPostTool(BaseTool):
    """Publish media to 22+ social networks via UploadPost API."""

    name = "uploadpost"
    version = "0.1.0"
    tier = ToolTier.CORE
    capability = "publishing"
    provider = "uploadpost"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.API

    dependencies = ["env:UPLOADPOST_API_KEY"]
    install_instructions = (
        "UploadPost requires an API key.\n"
        "1. Sign up at https://upload-post.com\n"
        "2. Connect your social media accounts (YouTube, TikTok, etc.)\n"
        "3. Create a user profile name in the dashboard\n"
        "4. Generate an API key\n"
        "5. Set environment variables:\n"
        "   export UPLOADPOST_API_KEY=your_key_here\n"
        "   export UPLOADPOST_USER=your_profile_name\n"
        "Free plan: 10 uploads per month"
    )
    agent_skills = ["social-publishing", "youtube-upload", "multi-platform"]

    capabilities = [
        "upload_video", "upload_photos", "upload_text",
        "multi_platform", "scheduling", "status_check", "analytics",
    ]
    supports = {
        "platforms": SUPPORTED_PLATFORMS,
        "video_upload": True,
        "photo_upload": True,
        "scheduling": True,
        "analytics": True,
        "webhooks": True,
        "auto_transcoding": True,
    }
    best_for = [
        "publishing finished videos to YouTube/TikTok/Instagram in one call",
        "multi-platform social media distribution",
        "automated content publishing pipelines",
        "unified analytics across platforms",
    ]
    not_good_for = [
        "use without an API key",
        "offline publishing",
        "platforms not in the supported list",
    ]

    input_schema = {
        "type": "object",
        "required": ["operation"],
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["upload_video", "upload_photos", "status", "analytics", "list_platforms"],
                "description": (
                    "upload_video: POST /api/upload (multipart: video, title, user, platform[]). "
                    "upload_photos: POST /api/upload_photos. "
                    "status: GET /api/status/{request_id}. "
                    "analytics: GET /api/analytics/{request_id}. "
                    "list_platforms: return supported platforms."
                ),
            },
            "video_path": {"type": "string", "description": "Local path to video file (upload_video)"},
            "photo_paths": {"type": "array", "items": {"type": "string"}, "description": "Local paths to photo files (upload_photos)"},
            "title": {"type": "string", "description": "Post title"},
            "description": {"type": "string", "description": "Post description/caption"},
            "user": {"type": "string", "description": "UploadPost user profile name. Falls back to UPLOADPOST_USER env var."},
            "platforms": {
                "type": "array",
                "items": {"type": "string", "enum": SUPPORTED_PLATFORMS},
                "description": "Target platforms (e.g. ['youtube', 'tiktok'])",
            },
            "request_id": {"type": "string", "description": "Request ID for status/analytics checks"},
            "schedule_time": {"type": "string", "description": "ISO 8601 datetime for scheduled publishing"},
            "tags": {"type": "array", "items": {"type": "string"}, "description": "Tags/hashtags"},
        },
    }

    resource_profile = ResourceProfile(cpu_cores=1, ram_mb=128, vram_mb=0, disk_mb=50, network_required=True)
    retry_policy = RetryPolicy(max_retries=2, retryable_errors=["timeout", "5xx"])
    idempotency_key_fields = ["operation", "video_path", "title", "platforms"]
    side_effects = ["uploads media to social platforms", "creates public posts"]
    user_visible_verification = ["Check the returned post URLs on each platform"]

    def get_status(self) -> ToolStatus:
        if os.environ.get("UPLOADPOST_API_KEY"):
            return ToolStatus.AVAILABLE
        return ToolStatus.UNAVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        # Free plan: 10 uploads/month. Paid plans start at ~$0.10 per upload.
        return 0.10

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        operation = inputs.get("operation")
        if not operation:
            return ToolResult(success=False, error="Missing required input: operation")

        # list_platforms works without an API key (returns static list)
        if operation == "list_platforms":
            return ToolResult(
                success=True,
                data={"platforms": SUPPORTED_PLATFORMS, "count": len(SUPPORTED_PLATFORMS)},
            )

        # All other operations require an API key
        api_key = os.environ.get("UPLOADPOST_API_KEY")
        if not api_key:
            return ToolResult(success=False, error="UPLOADPOST_API_KEY not set. " + self.install_instructions)

        if operation == "upload_video":
            return self._upload_video(inputs, api_key)
        elif operation == "upload_photos":
            return self._upload_photos(inputs, api_key)
        elif operation == "status":
            return self._check_status(inputs, api_key)
        elif operation == "analytics":
            return self._get_analytics(inputs, api_key)
        else:
            return ToolResult(success=False, error=f"Unknown operation: {operation}")

    def _build_multipart(self, fields: list[tuple[str, str | bytes]], files: list[tuple[str, str, bytes]]) -> bytes:
        """Build a multipart/form-data body."""
        boundary = f"----UploadPostBoundary{int(time.time()*1000)}"
        lines: list[bytes] = []

        for name, value in fields:
            lines.append(f"--{boundary}".encode())
            lines.append(f'Content-Disposition: form-data; name="{name}"'.encode())
            lines.append(b"")
            lines.append(str(value).encode())

        for field_name, filename, file_data in files:
            lines.append(f"--{boundary}".encode())
            lines.append(
                f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"'.encode()
            )
            lines.append(b"Content-Type: application/octet-stream")
            lines.append(b"")
            lines.append(file_data)

        lines.append(f"--{boundary}--".encode())
        lines.append(b"")

        return b"\r\n".join(lines), boundary

    def _upload_video(self, inputs: dict[str, Any], api_key: str) -> ToolResult:
        video_path = inputs.get("video_path")
        if not video_path:
            return ToolResult(success=False, error="Missing required input: video_path")
        video_path = Path(video_path)
        if not video_path.exists():
            return ToolResult(success=False, error=f"Video file not found: {video_path}")

        title = inputs.get("title", video_path.stem)
        description = inputs.get("description", "")
        user = inputs.get("user") or os.environ.get("UPLOADPOST_USER", "")
        if not user:
            return ToolResult(success=False, error="No user specified. Set UPLOADPOST_USER or pass user in inputs.")
        platforms = inputs.get("platforms", ["youtube"])
        tags = inputs.get("tags", [])

        # Build multipart form
        fields: list[tuple[str, str]] = [
            ("title", title),
            ("user", user),
        ]
        if description:
            fields.append(("description", description))
        if tags:
            fields.append(("tags", ",".join(tags)))
        for p in platforms:
            fields.append(("platform[]", p))

        video_data = video_path.read_bytes()
        files = [("video", video_path.name, video_data)]

        body, boundary = self._build_multipart(fields, files)

        headers = {
            "Authorization": f"Apikey {api_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        }

        url = f"{UPLOADPOST_API_URL}/api/upload"
        start = time.time()
        try:
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=300) as resp:
                response_data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")[:500]
            return ToolResult(success=False, error=f"UploadPost API error {exc.code}: {error_body}")
        except Exception as exc:
            return ToolResult(success=False, error=f"UploadPost request failed: {exc}")

        return ToolResult(
            success=response_data.get("success", False),
            data={
                "provider": self.provider,
                "operation": "upload_video",
                "title": title,
                "platforms": platforms,
                "user": user,
                "response": response_data,
                "request_id": response_data.get("request_id"),
            },
            artifacts=[],
            duration_seconds=round(time.time() - start, 2),
        )

    def _upload_photos(self, inputs: dict[str, Any], api_key: str) -> ToolResult:
        photo_paths = inputs.get("photo_paths", [])
        if not photo_paths:
            return ToolResult(success=False, error="Missing required input: photo_paths")

        title = inputs.get("title", "")
        description = inputs.get("description", "")
        user = inputs.get("user") or os.environ.get("UPLOADPOST_USER", "")
        if not user:
            return ToolResult(success=False, error="No user specified. Set UPLOADPOST_USER or pass user in inputs.")
        platforms = inputs.get("platforms", ["instagram"])

        fields: list[tuple[str, str]] = [
            ("title", title),
            ("user", user),
        ]
        if description:
            fields.append(("description", description))
        for p in platforms:
            fields.append(("platform[]", p))

        files: list[tuple[str, str, bytes]] = []
        for pp in photo_paths:
            p = Path(pp)
            if not p.exists():
                return ToolResult(success=False, error=f"Photo file not found: {pp}")
            files.append(("photos[]", p.name, p.read_bytes()))

        body, boundary = self._build_multipart(fields, files)

        headers = {
            "Authorization": f"Apikey {api_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        }

        url = f"{UPLOADPOST_API_URL}/api/upload_photos"
        start = time.time()
        try:
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=120) as resp:
                response_data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")[:500]
            return ToolResult(success=False, error=f"UploadPost API error {exc.code}: {error_body}")
        except Exception as exc:
            return ToolResult(success=False, error=f"UploadPost request failed: {exc}")

        return ToolResult(
            success=response_data.get("success", False),
            data={
                "provider": self.provider,
                "operation": "upload_photos",
                "title": title,
                "platforms": platforms,
                "user": user,
                "photo_count": len(photo_paths),
                "response": response_data,
                "request_id": response_data.get("request_id"),
            },
            duration_seconds=round(time.time() - start, 2),
        )

    def _check_status(self, inputs: dict[str, Any], api_key: str) -> ToolResult:
        request_id = inputs.get("request_id")
        if not request_id:
            return ToolResult(success=False, error="Missing required input: request_id")

        url = f"{UPLOADPOST_API_URL}/api/status/{request_id}"
        headers = {"Authorization": f"Apikey {api_key}"}

        try:
            req = urllib.request.Request(url, headers=headers, method="GET")
            with urllib.request.urlopen(req, timeout=30) as resp:
                response_data = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            return ToolResult(success=False, error=f"Status check failed: {exc}")

        return ToolResult(
            success=True,
            data={"request_id": request_id, "status": response_data},
        )

    def _get_analytics(self, inputs: dict[str, Any], api_key: str) -> ToolResult:
        request_id = inputs.get("request_id")
        if not request_id:
            return ToolResult(success=False, error="Missing required input: request_id")

        url = f"{UPLOADPOST_API_URL}/api/analytics/{request_id}"
        headers = {"Authorization": f"Apikey {api_key}"}

        try:
            req = urllib.request.Request(url, headers=headers, method="GET")
            with urllib.request.urlopen(req, timeout=30) as resp:
                response_data = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            return ToolResult(success=False, error=f"Analytics fetch failed: {exc}")

        return ToolResult(
            success=True,
            data={"request_id": request_id, "analytics": response_data},
        )
