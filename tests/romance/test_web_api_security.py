"""Security regression tests for the web API.

Covers:
- project_id validation (no '..', '.', slashes, or empty ids)
- path traversal attempts on asset serving, artifacts, logs, and delete
- engine-level artifact name guards (defense in depth)

Uses an isolated PROJECTS_ROOT under tmp_path so nothing real is touched.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import romance.engine as romance_engine
import web.api as web_api
from romance.engine import create_project
from web.api import app


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Isolated projects root with one real project and decoy secret files."""
    projects = tmp_path / "projects"
    projects.mkdir()

    monkeypatch.setattr(web_api, "PROJECTS_ROOT", projects)
    monkeypatch.setattr(romance_engine, "PROJECTS_ROOT", projects)

    engine = create_project(
        "Security test premise", {}, projects_root=projects
    )
    # A decoy secret INSIDE the projects root but OUTSIDE the project dir
    (projects / "secret.json").write_text("SECRET_INSIDE_ROOT")
    # A decoy secret OUTSIDE the projects root entirely
    (tmp_path / "outside.env").write_text("SECRET_OUTSIDE_ROOT")
    # A legit asset inside the project
    asset = engine.asset_path("images", "scene-sc1.png")
    asset.write_bytes(b"\x89PNG fake image bytes")

    client = TestClient(app)
    return {
        "client": client,
        "engine": engine,
        "pid": engine.project_id,
        "projects": projects,
        "tmp_path": tmp_path,
    }


# ---- project_id validation ----


class TestProjectIdValidation:
    @pytest.mark.parametrize(
        # Note: '.', '../..' and '' are omitted here because HTTP clients
        # collapse those segments before the request reaches the app, landing
        # on the benign list/index routes (200). The server-side handlers DO
        # reject them — covered by TestHandlerLevelGuards below.
        "bad_id",
        ["..", "a/../b", "a\\..\\b", "..%2F..", "%2e%2e", "a b", "-abc"],
    )
    def test_traversal_project_ids_rejected(self, env, bad_id):
        """Hostile ids are rejected (400 from our validation, or 404 because
        the HTTP client collapses the path before it reaches a route). Either
        way: never 200, never leaks a secret."""
        client = env["client"]
        resp = client.get(f"/api/projects/{bad_id}")
        assert resp.status_code in (400, 404), resp.text
        assert "SECRET" not in resp.text

    def test_valid_project_id_works(self, env):
        client = env["client"]
        resp = client.get(f"/api/projects/{env['pid']}")
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"]["project_id"] == env["pid"]

    def test_leading_hyphen_premise_slug_is_api_accessible(self, env):
        """slugify must never produce a leading/trailing hyphen, or the API
        could create a project it can never open."""
        engine = create_project("- something", {}, projects_root=env["projects"])
        pid = engine.project_id
        assert not pid.startswith("-")
        assert not pid.endswith("-")
        resp = env["client"].get(f"/api/projects/{pid}")
        assert resp.status_code == 200, resp.text

    def test_delete_with_traversal_id_rejected_and_nothing_deleted(self, env):
        client = env["client"]
        resp = client.delete("/api/projects/%2e%2e")
        assert resp.status_code in (400, 404), resp.text
        assert (env["projects"] / "secret.json").exists()
        assert (env["tmp_path"] / "outside.env").exists()
        assert env["engine"].project_dir.exists()


# ---- asset serving ----


class TestAssetServing:
    def test_serve_legit_asset(self, env):
        client = env["client"]
        resp = client.get(f"/api/projects/{env['pid']}/assets/images/scene-sc1.png")
        assert resp.status_code == 200, resp.text
        assert resp.content == b"\x89PNG fake image bytes"

    def test_asset_traversal_inside_root_blocked(self, env):
        client = env["client"]
        # Resolves to projects/secret.json — outside the project dir
        resp = client.get(f"/api/projects/{env['pid']}/assets/%2e%2e/secret.json")
        assert resp.status_code == 404, resp.text
        assert "SECRET_INSIDE_ROOT" not in resp.text

    def test_asset_traversal_outside_root_blocked(self, env):
        client = env["client"]
        resp = client.get(f"/api/projects/{env['pid']}/assets/%2e%2e/%2e%2e/outside.env")
        assert resp.status_code == 404, resp.text
        assert "SECRET_OUTSIDE_ROOT" not in resp.text

    def test_asset_literal_dotdot_blocked(self, env):
        client = env["client"]
        # Fully-encoded slashes + dot-dots; must not be served
        resp = client.get(f"/api/projects/{env['pid']}/assets/%2e%2e%2f%2e%2e%2fsecret.json")
        assert resp.status_code == 404, resp.text
        assert "SECRET_INSIDE_ROOT" not in resp.text


# ---- artifacts & logs ----


class TestArtifactAndLogNames:
    def test_get_artifact_traversal_name_rejected(self, env):
        client = env["client"]
        resp = client.get(f"/api/projects/{env['pid']}/artifacts/%2e%2e%2fsecret")
        assert resp.status_code in (400, 404), resp.text
        assert "SECRET" not in resp.text

    def test_put_artifact_traversal_name_rejected(self, env):
        client = env["client"]
        resp = client.put(
            f"/api/projects/{env['pid']}/artifacts/%2e%2e%2fsecret",
            json={"data": {"version": "1.0", "evil": True}},
        )
        assert resp.status_code in (400, 404), resp.text
        # No stray file written outside the project
        assert not (env["projects"] / "secret.json~").exists()

    def test_get_artifact_legit_name_works(self, env):
        client = env["client"]
        resp = client.get(f"/api/projects/{env['pid']}/artifacts/intake")
        assert resp.status_code in (200, 404)  # intake.json may not exist yet

    def test_logs_traversal_stage_rejected(self, env):
        client = env["client"]
        resp = client.get(f"/api/projects/{env['pid']}/logs/%2e%2e%2fsecret")
        assert resp.status_code in (400, 404), resp.text
        assert "SECRET" not in resp.text

    def test_logs_legit_stage_works(self, env):
        env["engine"].log("intake", "hello")
        client = env["client"]
        resp = client.get(f"/api/projects/{env['pid']}/logs/intake")
        assert resp.status_code == 200, resp.text
        assert resp.json()["logs"][0]["message"] == "hello"


# ---- handler-level guards (defense in depth, bypasses client normalization) ----


class TestHandlerLevelGuards:
    """Call the route handlers directly with hostile strings so the server-side
    validation is exercised even when an HTTP client collapses the path first."""

    def test_engine_rejects_traversal_ids(self, env):
        from fastapi import HTTPException
        for bad in ("..", ".", "../..", "a/../b", "a\\..\\b", "", "a b", "-abc"):
            with pytest.raises(HTTPException) as excinfo:
                web_api._engine(bad)
            assert excinfo.value.status_code == 400

    def test_serve_asset_blocks_escaping_path(self, env):
        import asyncio
        from fastapi import HTTPException
        # '../../secret.json' resolves OUTSIDE the project dir
        with pytest.raises(HTTPException) as excinfo:
            asyncio.run(web_api.serve_asset(env["pid"], "../../secret.json"))
        assert excinfo.value.status_code == 404

    def test_get_artifact_blocks_traversal_name(self, env):
        import asyncio
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as excinfo:
            asyncio.run(web_api.get_artifact(env["pid"], "../secret"))
        assert excinfo.value.status_code == 400

    def test_update_artifact_blocks_traversal_name(self, env):
        import asyncio
        from fastapi import HTTPException
        from web.api import UpdateArtifactRequest
        with pytest.raises(HTTPException) as excinfo:
            asyncio.run(web_api.update_artifact(
                env["pid"], "../secret", UpdateArtifactRequest(data={"version": "1.0"})
            ))
        assert excinfo.value.status_code == 400

    def test_logs_blocks_traversal_stage(self, env):
        import asyncio
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as excinfo:
            asyncio.run(web_api.get_logs(env["pid"], "../secret"))
        assert excinfo.value.status_code == 400

    def test_delete_blocks_traversal_id(self, env):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as excinfo:
            web_api._engine("..")  # delete_project routes through _engine
        assert excinfo.value.status_code == 400
        assert (env["projects"] / "secret.json").exists()


# ---- engine-level guards (defense in depth) ----


class TestEngineNameGuards:
    def test_save_artifact_rejects_unsafe_name(self, env):
        with pytest.raises(ValueError):
            env["engine"].save_artifact("../evil", {"version": "1.0"})
        with pytest.raises(ValueError):
            env["engine"].save_artifact("a/b", {"version": "1.0"})
        # Nothing written outside the project
        assert not (env["projects"] / "evil.json").exists()

    def test_load_artifact_rejects_unsafe_name(self, env):
        with pytest.raises(ValueError):
            env["engine"].load_artifact("../secret")

    def test_safe_names_still_work(self, env):
        env["engine"].save_artifact("story_bible", {"version": "1.0", "ok": True})
        assert env["engine"].load_artifact("story_bible")["ok"] is True
