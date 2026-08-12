"""LLM bridge — wraps the z-ai CLI for chat completions.

This is a single-dependency bridge: it shells out to `z-ai chat` and parses
the JSON response. Using the CLI means we get the same auth, model routing,
and rate limits as the user's local environment with zero extra config.

If `z-ai` is unavailable, callers get a clear RuntimeError with install
instructions. The romance pipeline degrades gracefully — every stage that
calls LLM is wrapped in try/except and produces a structured error artifact.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any


def zai_available() -> bool:
    """Return True if the `z-ai` CLI is on PATH and responds."""
    if not shutil.which("z-ai"):
        return False
    return True


def chat(
    prompt: str,
    *,
    system: str | None = None,
    thinking: bool = False,
    timeout: int = 240,
    retries: int = 2,
) -> str:
    """Send a single-turn chat request via `z-ai chat`. Returns the message content.

    Raises RuntimeError if z-ai is unavailable or returns a non-2xx after retries.
    Uses --output flag to write to a temp file, avoiding stdout buffering timeouts
    on long responses.
    """
    if not zai_available():
        raise RuntimeError(
            "z-ai CLI is not available on PATH. Install it via `npm i -g z-ai-web-dev-sdk` "
            "or set up the local environment per the skills/LLM/SKILL.md instructions."
        )

    # Use a temp file for output — avoids stdout buffering issues on long responses
    import tempfile
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, prefix="zai_")
    tmp.close()
    output_file = tmp.name

    cmd = ["z-ai", "chat", "--prompt", prompt, "--output", output_file]
    if system:
        cmd += ["--system", system]
    if thinking:
        cmd.append("--thinking")

    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if proc.returncode != 0:
                raise RuntimeError(
                    f"z-ai chat failed (exit {proc.returncode}): {proc.stderr[:500]}"
                )
            # Read the JSON output file
            from pathlib import Path
            out_path = Path(output_file)
            if not out_path.exists() or out_path.stat().st_size == 0:
                # Fallback: try parsing stdout
                stdout = proc.stdout
                json_start = stdout.find("{")
                if json_start < 0:
                    raise RuntimeError(f"No JSON in z-ai output: {stdout[:500]}")
                payload = json.loads(stdout[json_start:])
            else:
                payload = json.loads(out_path.read_text())
            choices = payload.get("choices") or []
            if not choices:
                raise RuntimeError(f"Empty choices in z-ai response: {payload}")
            content = choices[0].get("message", {}).get("content", "")
            try:
                out_path.unlink()
            except Exception:
                pass
            return content.strip()
        except Exception as exc:
            last_err = exc
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
            continue
    try:
        from pathlib import Path
        Path(output_file).unlink(missing_ok=True)
    except Exception:
        pass
    raise RuntimeError(f"z-ai chat failed after {retries+1} attempts: {last_err}")


def chat_json(
    prompt: str,
    *,
    system: str | None = None,
    thinking: bool = False,
    timeout: int = 240,
    retries: int = 2,
) -> Any:
    """Send a chat request and parse the response as JSON.

    The prompt should explicitly instruct the model to return only valid JSON.
    This helper tolerates JSON fenced in ```json ... ``` blocks.
    """
    content = chat(prompt, system=system, thinking=thinking, timeout=timeout, retries=retries)
    return _extract_json(content)


def _extract_json(content: str) -> Any:
    """Best-effort extract a JSON object/array from an LLM response."""
    if not content:
        raise ValueError("Empty LLM response — cannot parse JSON")

    # Try direct parse first
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # Strip ```json ... ``` fences
    fence_match = re.search(r"```(?:json)?\s*(.+?)```", content, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Find the outermost { ... } or [ ... ]
    for opener, closer in (("{", "}"), ("[", "]")):
        start = content.find(opener)
        end = content.rfind(closer)
        if start >= 0 and end > start:
            try:
                return json.loads(content[start : end + 1])
            except json.JSONDecodeError:
                continue

    raise ValueError(
        f"Could not extract JSON from LLM response. First 500 chars: {content[:500]!r}"
    )
