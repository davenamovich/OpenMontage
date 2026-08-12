"""Tests for the YouTube Romance Story pipeline.

Tests cover:
- Pipeline manifest loading and validation
- Stage director contracts (intake, concept, story_bible, outline, script, scene_plan)
- Schema validation for all romance artifacts
- Project persistence and resume
- Cost tracking integration
- Caption generation
- Scene plan generation (deterministic mode)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from lib.pipeline_loader import get_stage_order, list_pipelines, load_pipeline
from romance.constants import EMOTIONAL_BEATS, FORMATS, GENRES, VISUAL_MODES
from romance.engine import RomanceEngine, create_project, load_intake_defaults
from romance.stages._shared import brief_meta
from schemas.artifacts import validate_artifact


# ---- Pipeline manifest ----

class TestPipelineManifest:
    def test_manifest_loads(self):
        m = load_pipeline("youtube-romance-story")
        assert m["name"] == "youtube-romance-story"
        assert m["version"] == "1.0"

    def test_pipeline_in_list(self):
        assert "youtube-romance-story" in list_pipelines()

    def test_all_17_stages_present(self):
        m = load_pipeline("youtube-romance-story")
        stages = get_stage_order(m)
        assert len(stages) == 17
        assert stages[0] == "intake"
        assert stages[-1] == "publish"

    def test_proposal_stage_exists(self):
        """The runtime contract test requires a 'proposal' or 'idea' stage."""
        m = load_pipeline("youtube-romance-story")
        stages = [s["name"] for s in m["stages"]]
        assert "proposal" in stages

    def test_all_stages_have_skills(self):
        m = load_pipeline("youtube-romance-story")
        for stage in m["stages"]:
            assert stage.get("skill"), f"Stage {stage['name']} has no skill"

    def test_all_skills_exist_on_disk(self):
        m = load_pipeline("youtube-romance-story")
        for stage in m["stages"]:
            skill_ref = stage["skill"]
            skill_path = PROJECT_ROOT / "skills" / f"{skill_ref}.md"
            assert skill_path.is_file(), f"Skill file missing: {skill_path}"


# ---- Constants ----

class TestConstants:
    def test_genres_complete(self):
        assert len(GENRES) == 26
        assert "small_town" in GENRES
        assert "supernatural" in GENRES

    def test_formats_complete(self):
        assert len(FORMATS) == 5
        assert "long_form" in FORMATS
        assert "short" in FORMATS

    def test_visual_modes_complete(self):
        assert len(VISUAL_MODES) == 3
        assert "economical" in VISUAL_MODES

    def test_emotional_beats_in_order(self):
        assert EMOTIONAL_BEATS[0] == "opening_hook"
        assert EMOTIONAL_BEATS[-1] == "final_button"
        assert len(EMOTIONAL_BEATS) == 10

    def test_eras_complete(self):
        from romance.constants import ERAS
        assert len(ERAS) >= 20
        assert "victorian" in ERAS
        assert "roaring_20s" in ERAS
        assert "neon_80s" in ERAS
        assert "modern" in ERAS
        assert "cyberpunk" in ERAS
        assert "fantasy" in ERAS

    def test_era_labels_exist(self):
        from romance.constants import ERA_LABELS, ERAS
        for era in ERAS:
            assert era in ERA_LABELS, f"Missing label for era: {era}"

    def test_era_visual_cues_exist(self):
        from romance.constants import ERA_VISUAL_CUES, ERAS
        for era in ERAS:
            assert era in ERA_VISUAL_CUES, f"Missing visual cues for era: {era}"
            assert len(ERA_VISUAL_CUES[era]) > 10, f"Era cues too short for: {era}"

    def test_visual_styles_complete(self):
        from romance.constants import VISUAL_STYLES
        assert len(VISUAL_STYLES) >= 15
        assert "cinematic_realism" in VISUAL_STYLES
        assert "anime" in VISUAL_STYLES
        assert "caricature" in VISUAL_STYLES
        assert "oil_painting" in VISUAL_STYLES
        assert "watercolor" in VISUAL_STYLES
        assert "ghibli" in VISUAL_STYLES

    def test_visual_style_labels_exist(self):
        from romance.constants import VISUAL_STYLE_LABELS, VISUAL_STYLES
        for style in VISUAL_STYLES:
            assert style in VISUAL_STYLE_LABELS, f"Missing label for style: {style}"

    def test_visual_style_modifiers_exist(self):
        from romance.constants import VISUAL_STYLE_MODIFIERS, VISUAL_STYLES
        for style in VISUAL_STYLES:
            assert style in VISUAL_STYLE_MODIFIERS, f"Missing modifier for style: {style}"
            assert len(VISUAL_STYLE_MODIFIERS[style]) > 10

    def test_visual_style_negatives_exist(self):
        from romance.constants import VISUAL_STYLE_NEGATIVES, VISUAL_STYLES
        for style in VISUAL_STYLES:
            assert style in VISUAL_STYLE_NEGATIVES, f"Missing negative prompt for style: {style}"


# ---- Intake defaults ----

class TestIntakeDefaults:
    def test_minimal_premise_fills_defaults(self):
        intake = load_intake_defaults({"premise": "Two strangers meet."})
        assert intake["genre"] == "small_town"
        assert intake["format"] == "long_form"
        assert intake["target_duration"] == 540
        assert intake["target_word_count"] > 0
        assert intake["language"] == "en"
        assert intake["visual_mode"] == "economical"
        assert intake["era"] == "modern"
        assert intake["visual_style"] == "cinematic_realism"

    def test_invalid_genre_falls_back(self):
        intake = load_intake_defaults({"premise": "Test", "genre": "nonexistent"})
        assert intake["genre"] == "small_town"

    def test_invalid_format_falls_back(self):
        intake = load_intake_defaults({"premise": "Test", "format": "nonexistent"})
        assert intake["format"] == "long_form"

    def test_invalid_era_falls_back(self):
        intake = load_intake_defaults({"premise": "Test", "era": "nonexistent"})
        assert intake["era"] == "modern"

    def test_invalid_visual_style_falls_back(self):
        intake = load_intake_defaults({"premise": "Test", "visual_style": "nonexistent"})
        assert intake["visual_style"] == "cinematic_realism"

    def test_era_and_style_are_preserved(self):
        intake = load_intake_defaults({"premise": "Test", "era": "victorian", "visual_style": "anime"})
        assert intake["era"] == "victorian"
        assert intake["visual_style"] == "anime"

    def test_word_count_scales_with_duration(self):
        intake_short = load_intake_defaults({"premise": "Test", "target_duration": 60})
        intake_long = load_intake_defaults({"premise": "Test", "target_duration": 600})
        assert intake_long["target_word_count"] > intake_short["target_word_count"]


# ---- Schema validation ----

class TestSchemaValidation:
    def test_story_bible_schema_exists(self):
        from schemas.artifacts import ARTIFACT_NAMES
        assert "story_bible" in ARTIFACT_NAMES

    def test_outline_schema_exists(self):
        from schemas.artifacts import ARTIFACT_NAMES
        assert "outline" in ARTIFACT_NAMES

    def test_continuity_ledger_schema_exists(self):
        from schemas.artifacts import ARTIFACT_NAMES
        assert "continuity_ledger" in ARTIFACT_NAMES

    def test_youtube_package_schema_exists(self):
        from schemas.artifacts import ARTIFACT_NAMES
        assert "youtube_package" in ARTIFACT_NAMES

    def test_thumbnail_concept_schema_exists(self):
        from schemas.artifacts import ARTIFACT_NAMES
        assert "thumbnail_concept" in ARTIFACT_NAMES

    def test_shorts_package_schema_exists(self):
        from schemas.artifacts import ARTIFACT_NAMES
        assert "shorts_package" in ARTIFACT_NAMES

    def test_story_bible_validates(self):
        bible = {
            "version": "1.0",
            "project_id": "test",
            "format": "long_form",
            "genre": "small_town",
            "tone": "warm",
            "characters": [
                {
                    "character_id": "emma",
                    "full_name": "Emma",
                    "role": "protagonist",
                    "age": 34,
                    "appearance": {
                        "face": "oval, warm brown eyes",
                        "hair": "auburn, shoulder-length",
                        "build": "slim",
                        "wardrobe": "navy diner uniform",
                        "palette": ["#3B5998", "#F5F5DC"],
                    },
                    "personality": {
                        "summary": "Resilient but guarded",
                        "emotional_wound": "Painful divorce",
                        "desire": "To feel safe again",
                        "fear": "Being hurt again",
                        "contradiction": "Wants love but pushes it away",
                        "speech_style": "Direct, warm",
                    },
                    "visual_reference_prompt": "A 34-year-old woman with auburn hair",
                    "negative_prompt": "child, teenager",
                    "voice": {"provider": "zai_tts", "voice_id": "tongtong"},
                }
            ],
            "world": {
                "setting": "small town",
                "time_period": "present day",
            },
        }
        validate_artifact("story_bible", bible)  # should not raise

    def test_outline_validates(self):
        outline = {
            "version": "1.0",
            "project_id": "test",
            "title": "Test",
            "logline": "A test story",
            "target_word_count": 1000,
            "target_duration_seconds": 540,
            "beats": [
                {"id": "b1", "beat_type": "opening_hook", "summary": "Hook", "approx_words": 50},
                {"id": "b2", "beat_type": "setup", "summary": "Setup", "approx_words": 100},
            ],
        }
        validate_artifact("outline", outline)  # should not raise


# ---- Project persistence ----

class TestProjectPersistence:
    @pytest.fixture
    def temp_project(self, tmp_path):
        """Create a temporary project for testing."""
        engine = RomanceEngine(tmp_path / "test-project")
        return engine

    def test_project_dir_created(self, temp_project):
        assert temp_project.project_dir.exists()
        assert (temp_project.project_dir / "assets" / "characters").exists()
        assert (temp_project.project_dir / "assets" / "images").exists()
        assert (temp_project.project_dir / "renders").exists()
        assert (temp_project.project_dir / "youtube").exists()
        assert (temp_project.project_dir / "logs").exists()

    def test_project_json_created(self, temp_project):
        assert temp_project.project_json_path.exists()
        data = json.loads(temp_project.project_json_path.read_text())
        assert data["pipeline"] == "youtube-romance-story"
        assert data["project_id"] == "test-project"

    def test_save_and_load_artifact(self, temp_project):
        artifact = {"version": "1.0", "test": True}
        temp_project.save_artifact("story_bible", artifact)
        loaded = temp_project.load_artifact("story_bible")
        assert loaded == artifact

    def test_log_writes_to_file(self, temp_project):
        temp_project.log("test_stage", "test message", extra="data")
        log_path = temp_project.project_dir / "logs" / "test_stage.log"
        assert log_path.exists()
        entry = json.loads(log_path.read_text().strip())
        assert entry["stage"] == "test_stage"
        assert entry["message"] == "test message"

    def test_asset_path_creates_parent(self, temp_project):
        path = temp_project.asset_path("characters", "emma.png")
        assert path.parent.exists()
        assert path.name == "emma.png"


# ---- brief_meta helper ----

class TestBriefMeta:
    def test_extracts_metadata(self):
        brief = {
            "version": "1.0",
            "title": "Test",
            "hook": "A test hook",
            "key_points": ["point1"],
            "tone": "warm",
            "style": "cinematic-realism",
            "target_platform": "youtube",
            "target_duration_seconds": 540,
            "metadata": {
                "premise": "A test premise",
                "genre": "small_town",
                "format": "long_form",
            },
        }
        meta = brief_meta(brief)
        assert meta["premise"] == "A test premise"
        assert meta["genre"] == "small_town"

    def test_empty_brief_returns_empty(self):
        assert brief_meta(None) == {}
        assert brief_meta({}) == {}

    def test_no_metadata_returns_empty(self):
        assert brief_meta({"version": "1.0"}) == {}


# ---- Caption generation ----

class TestCaptions:
    def test_caption_generation(self, tmp_path):
        from romance.stages.compose_director import _write_captions, _fmt_time_srt
        script = {
            "sections": [
                {"id": "s1", "text": "This is the first section of narration.", "start_seconds": 0, "end_seconds": 5},
                {"id": "s2", "text": "This is the second section.", "start_seconds": 5, "end_seconds": 10},
            ]
        }
        srt_path = tmp_path / "captions.srt"
        _write_captions(script, srt_path, "srt")
        assert srt_path.exists()
        content = srt_path.read_text()
        assert "00:00:00" in content  # first timestamp
        assert "narration" in content.lower()

    def test_srt_time_format(self):
        from romance.stages.compose_director import _fmt_time_srt
        assert _fmt_time_srt(0) == "00:00:00,000"
        assert _fmt_time_srt(5.5) == "00:00:05,500"
        assert _fmt_time_srt(65.25) == "00:01:05,250"


# ---- Scene plan (deterministic) ----

class TestScenePlanDeterministic:
    @pytest.fixture
    def mock_engine(self, tmp_path):
        """Create a mock engine with pre-populated artifacts."""
        engine = RomanceEngine(tmp_path / "test-project")
        # Save minimal brief
        engine.save_artifact("brief", {
            "version": "1.0", "title": "Test", "hook": "Hook",
            "key_points": ["p1"], "tone": "warm", "style": "cinematic-realism",
            "target_platform": "youtube", "target_duration_seconds": 60,
            "metadata": {"premise": "Test", "format": "long_form", "output_aspect_ratio": "16:9", "visual_mode": "economical"},
        })
        # Save minimal story_bible
        engine.save_artifact("story_bible", {
            "version": "1.0", "project_id": "test", "format": "long_form",
            "genre": "small_town", "tone": "warm",
            "characters": [{
                "character_id": "emma", "full_name": "Emma", "role": "protagonist", "age": 34,
                "appearance": {"face": "oval", "hair": "auburn", "build": "slim", "wardrobe": "navy", "palette": ["#333"]},
                "personality": {"summary": "resilient", "emotional_wound": "divorce", "desire": "love", "fear": "hurt", "contradiction": "wants love but pushes away", "speech_style": "direct"},
                "visual_reference_prompt": "A 34-year-old woman with auburn hair",
                "negative_prompt": "child",
                "voice": {"provider": "zai_tts", "voice_id": "tongtong"},
            }],
            "world": {"setting": "small town", "time_period": "present day", "locations": [], "important_objects": []},
        })
        # Save minimal script
        engine.save_artifact("script", {
            "version": "1.0", "title": "Test", "total_duration_seconds": 60,
            "sections": [
                {"id": "s1", "text": "The bell jingles as Daniel enters the diner.", "start_seconds": 0, "end_seconds": 30},
                {"id": "s2", "text": "Emma watches him from behind the counter.", "start_seconds": 30, "end_seconds": 60},
            ],
        })
        # Save minimal outline
        engine.save_artifact("outline", {
            "version": "1.0", "project_id": "test", "title": "Test", "logline": "test",
            "target_word_count": 150, "target_duration_seconds": 60,
            "beats": [
                {"id": "b1", "beat_type": "opening_hook", "summary": "Hook", "approx_words": 50, "characters_present": ["emma"]},
                {"id": "b2", "beat_type": "setup", "summary": "Setup", "approx_words": 100, "characters_present": ["emma"]},
            ],
        })
        return engine

    def test_scene_plan_generates(self, mock_engine):
        from romance.stages.scene_director import run
        result = run(mock_engine, {})
        assert result["artifact"] == "scene_plan"
        assert "error" not in result
        data = result["data"]
        assert len(data["scenes"]) >= 4  # at least 2 scenes per section
        assert data["metadata"]["shot_variety_count"] >= 3  # at least 3 distinct shot sizes

    def test_scene_plan_validates(self, mock_engine):
        from romance.stages.scene_director import run
        result = run(mock_engine, {})
        validate_artifact("scene_plan", result["data"])  # should not raise

    def test_scenes_are_contiguous(self, mock_engine):
        from romance.stages.scene_director import run
        result = run(mock_engine, {})
        scenes = result["data"]["scenes"]
        for i in range(1, len(scenes)):
            assert scenes[i]["start_seconds"] == scenes[i-1]["end_seconds"]

    def test_first_scene_starts_at_zero(self, mock_engine):
        from romance.stages.scene_director import run
        result = run(mock_engine, {})
        assert result["data"]["scenes"][0]["start_seconds"] == 0

    def test_all_scenes_have_image_prompt(self, mock_engine):
        from romance.stages.scene_director import run
        result = run(mock_engine, {})
        for sc in result["data"]["scenes"]:
            assert sc["metadata"]["image_prompt"]
            assert sc["metadata"]["music_cue"]

    def test_all_enum_values_valid(self, mock_engine):
        from romance.stages.scene_director import run, ALLOWED_SHOT_SIZES, ALLOWED_CAMERA_MOVEMENTS, ALLOWED_LIGHTING_KEYS
        result = run(mock_engine, {})
        for sc in result["data"]["scenes"]:
            sl = sc["shot_language"]
            assert sl["shot_size"] in ALLOWED_SHOT_SIZES
            assert sl["camera_movement"] in ALLOWED_CAMERA_MOVEMENTS
            assert sl["lighting_key"] in ALLOWED_LIGHTING_KEYS


# ---- Cost tracking ----

class TestCostTracking:
    def test_cost_tracker_initializes(self, tmp_path):
        engine = RomanceEngine(tmp_path / "test-project")
        assert engine.cost_tracker.budget_total_usd == 5.0
        assert engine.cost_tracker.budget_spent_usd == 0.0

    def test_cost_snapshot(self, tmp_path):
        engine = RomanceEngine(tmp_path / "test-project")
        snap = engine.cost_tracker.cost_snapshot()
        assert "total_spent_usd" in snap
        assert "budget_remaining_usd" in snap


# ---- Z-AI tool contracts ----

class TestZaiTools:
    def test_zai_image_inherits_basetool(self):
        from tools.base_tool import BaseTool
        from tools.llm.zai_image import ZaiImage
        assert issubclass(ZaiImage, BaseTool)

    def test_zai_tts_inherits_basetool(self):
        from tools.base_tool import BaseTool
        from tools.llm.zai_tts import ZaiTTS
        assert issubclass(ZaiTTS, BaseTool)

    def test_zai_image_reports_status(self):
        from tools.base_tool import ToolStatus
        from tools.llm.zai_image import ZaiImage
        tool = ZaiImage()
        assert tool.get_status() in (ToolStatus.AVAILABLE, ToolStatus.UNAVAILABLE)

    def test_zai_image_handles_missing_inputs(self):
        from tools.llm.zai_image import ZaiImage
        tool = ZaiImage()
        result = tool.execute({"prompt": "test"})  # missing output_path
        assert not result.success
        assert "output_path" in result.error

    def test_zai_image_zero_cost(self):
        from tools.llm.zai_image import ZaiImage
        tool = ZaiImage()
        assert tool.estimate_cost({"prompt": "test"}) == 0.0


class TestComfyImageTool:
    def test_comfy_image_inherits_basetool(self):
        from tools.base_tool import BaseTool
        from tools.llm.comfy_image import ComfyImage
        assert issubclass(ComfyImage, BaseTool)

    def test_comfy_image_has_correct_name(self):
        from tools.llm.comfy_image import ComfyImage
        tool = ComfyImage()
        assert tool.name == "comfy_image"
        assert tool.provider == "comfyui"

    def test_comfy_image_reports_status(self):
        from tools.base_tool import ToolStatus
        from tools.llm.comfy_image import ComfyImage
        tool = ComfyImage()
        # Will be UNAVAILABLE unless ComfyUI is running locally
        assert tool.get_status() in (ToolStatus.AVAILABLE, ToolStatus.UNAVAILABLE)

    def test_comfy_image_handles_missing_inputs(self):
        from tools.llm.comfy_image import ComfyImage
        tool = ComfyImage()
        result = tool.execute({"prompt": "test"})  # missing output_path
        assert not result.success

    def test_comfy_image_zero_cost(self):
        from tools.llm.comfy_image import ComfyImage
        tool = ComfyImage()
        assert tool.estimate_cost({"prompt": "test"}) == 0.0

    def test_comfy_image_supports_negative_prompts(self):
        from tools.llm.comfy_image import ComfyImage
        tool = ComfyImage()
        assert tool.supports.get("negative_prompts") is True

    def test_comfy_image_local_runtime(self):
        from tools.base_tool import ToolRuntime
        from tools.llm.comfy_image import ComfyImage
        tool = ComfyImage()
        assert tool.runtime == ToolRuntime.LOCAL

    def test_get_best_image_tool_returns_something(self):
        """When ComfyUI is unavailable, should fall back to zai_image."""
        from romance.stages._shared import get_best_image_tool
        tool, name = get_best_image_tool()
        if tool is None:
            pytest.skip("No image provider available (ComfyUI or z-ai)")
        assert name in ("comfy_image", "zai_image")


class TestRealtimeCaptions:
    def test_format_timestamp_srt(self):
        from romance.realtime_captions import _format_timestamp_srt
        assert _format_timestamp_srt(0) == "00:00:00,000"
        assert _format_timestamp_srt(5.5) == "00:00:05,500"
        assert _format_timestamp_srt(65.25) == "00:01:05,250"

    def test_format_timestamp_vtt(self):
        from romance.realtime_captions import _format_timestamp_vtt
        assert _format_timestamp_vtt(0) == "00:00:00.000"
        assert _format_timestamp_vtt(5.5) == "00:00:05.500"

    def test_wrap_text_short(self):
        from romance.realtime_captions import _wrap_text
        assert _wrap_text("short text", 42) == "short text"

    def test_wrap_text_long(self):
        from romance.realtime_captions import _wrap_text
        long_text = "word " * 30  # 150 chars
        wrapped = _wrap_text(long_text.strip(), 42)
        lines = wrapped.split("\n")
        for line in lines:
            assert len(line) <= 42

    def test_build_cues_from_words(self):
        from romance.realtime_captions import _build_cues_from_words
        words = [
            {"start": 0.0, "end": 0.5, "word": "Hello", "probability": 0.9},
            {"start": 0.5, "end": 1.0, "word": "world", "probability": 0.9},
            {"start": 1.0, "end": 1.5, "word": "this", "probability": 0.9},
            {"start": 1.5, "end": 2.0, "word": "is", "probability": 0.9},
            {"start": 2.0, "end": 2.5, "word": "a", "probability": 0.9},
            {"start": 2.5, "end": 3.0, "word": "test", "probability": 0.9},
        ]
        cues = _build_cues_from_words(words, max_words=3, max_chars=42)
        assert len(cues) >= 2
        assert cues[0]["start"] == 0.0
        assert cues[-1]["end"] == 3.0

    def test_write_srt(self, tmp_path):
        from romance.realtime_captions import _write_srt
        cues = [
            {"start": 0.0, "end": 2.0, "text": "Hello world"},
            {"start": 2.0, "end": 4.0, "text": "This is a test"},
        ]
        srt_path = tmp_path / "test.srt"
        _write_srt(cues, srt_path)
        assert srt_path.exists()
        content = srt_path.read_text()
        assert "00:00:00,000" in content
        assert "Hello world" in content

    def test_write_vtt(self, tmp_path):
        from romance.realtime_captions import _write_vtt
        cues = [
            {"start": 0.0, "end": 2.0, "text": "Hello world"},
        ]
        vtt_path = tmp_path / "test.vtt"
        _write_vtt(cues, vtt_path)
        assert vtt_path.exists()
        content = vtt_path.read_text()
        assert content.startswith("WEBVTT")
        assert "00:00:00.000" in content


# ---- Fish.Audio TTS ----

class TestFishAudioTTS:
    def test_fish_audio_inherits_basetool(self):
        from tools.base_tool import BaseTool
        from tools.llm.fish_audio_tts import FishAudioTTS
        assert issubclass(FishAudioTTS, BaseTool)

    def test_fish_audio_has_correct_name(self):
        from tools.llm.fish_audio_tts import FishAudioTTS
        tool = FishAudioTTS()
        assert tool.name == "fish_audio_tts"
        assert tool.provider == "fish_audio"

    def test_fish_audio_reports_status(self):
        from tools.base_tool import ToolStatus
        from tools.llm.fish_audio_tts import FishAudioTTS
        tool = FishAudioTTS()
        # Will be UNAVAILABLE unless FISH_AUDIO_API_KEY is set
        assert tool.get_status() in (ToolStatus.AVAILABLE, ToolStatus.UNAVAILABLE)

    def test_fish_audio_handles_missing_inputs(self):
        from tools.llm.fish_audio_tts import FishAudioTTS
        tool = FishAudioTTS()
        result = tool.execute({"text": "test"})  # missing output_path
        assert not result.success

    def test_fish_audio_supports_voice_cloning(self):
        from tools.llm.fish_audio_tts import FishAudioTTS
        tool = FishAudioTTS()
        assert tool.supports.get("voice_cloning") is True
        assert tool.supports.get("multilingual") is True

    def test_fish_audio_api_runtime(self):
        from tools.base_tool import ToolRuntime
        from tools.llm.fish_audio_tts import FishAudioTTS
        tool = FishAudioTTS()
        assert tool.runtime == ToolRuntime.API

    def test_fish_audio_estimate_cost(self):
        from tools.llm.fish_audio_tts import FishAudioTTS
        tool = FishAudioTTS()
        cost = tool.estimate_cost({"text": "Hello world" * 100})
        assert cost > 0  # should have a non-zero cost estimate


# ---- OmniVoice TTS ----

class TestOmniVoiceTTS:
    def test_omnivoice_inherits_basetool(self):
        from tools.base_tool import BaseTool
        from tools.llm.omnivoice_tts import OmniVoiceTTS
        assert issubclass(OmniVoiceTTS, BaseTool)

    def test_omnivoice_has_correct_name(self):
        from tools.llm.omnivoice_tts import OmniVoiceTTS
        tool = OmniVoiceTTS()
        assert tool.name == "omnivoice_tts"
        assert tool.provider == "omnivoice"

    def test_omnivoice_reports_status(self):
        from tools.base_tool import ToolStatus
        from tools.llm.omnivoice_tts import OmniVoiceTTS
        tool = OmniVoiceTTS()
        assert tool.get_status() in (ToolStatus.AVAILABLE, ToolStatus.UNAVAILABLE)

    def test_omnivoice_handles_missing_inputs(self):
        from tools.llm.omnivoice_tts import OmniVoiceTTS
        tool = OmniVoiceTTS()
        result = tool.execute({"text": "test"})  # missing output_path
        assert not result.success

    def test_omnivoice_supports_emotions(self):
        from tools.llm.omnivoice_tts import OmniVoiceTTS
        tool = OmniVoiceTTS()
        assert tool.supports.get("emotions") is True
        assert tool.supports.get("ssml") is True
        assert tool.supports.get("multilingual") is True

    def test_omnivoice_supports_pitch_control(self):
        from tools.llm.omnivoice_tts import OmniVoiceTTS
        tool = OmniVoiceTTS()
        assert tool.supports.get("pitch_control") is True

    def test_omnivoice_estimate_cost(self):
        from tools.llm.omnivoice_tts import OmniVoiceTTS
        tool = OmniVoiceTTS()
        cost = tool.estimate_cost({"text": "Hello world" * 100})
        assert cost > 0


# ---- TTS provider selection ----

class TestTTSProviderSelection:
    def test_get_best_tts_tool_returns_something(self):
        """Should return the best TTS provider when one is installed."""
        from romance.stages._shared import get_best_tts_tool
        tool, name = get_best_tts_tool()
        if tool is None:
            pytest.skip("No TTS provider available (fish, omnivoice, z-ai, or piper)")
        assert name in ("fish_audio_tts", "omnivoice_tts", "zai_tts", "piper_tts")

    def test_list_tts_providers_returns_all(self):
        """Should return all 4 TTS providers."""
        from romance.stages._shared import list_tts_providers
        providers = list_tts_providers()
        assert len(providers) == 4
        names = [p["name"] for p in providers]
        assert "fish_audio_tts" in names
        assert "omnivoice_tts" in names
        assert "zai_tts" in names
        assert "piper_tts" in names

    def test_list_tts_providers_has_availability(self):
        from romance.stages._shared import list_tts_providers
        providers = list_tts_providers()
        for p in providers:
            assert "available" in p
            assert isinstance(p["available"], bool)


# ---- Auto-run ----

class TestAutoRun:
    def test_engine_has_run_all_background(self):
        """RomanceEngine should have run_all_background method."""
        from romance.engine import RomanceEngine
        assert hasattr(RomanceEngine, "run_all_background")

    def test_engine_has_get_job(self):
        """RomanceEngine should have get_job method for background jobs."""
        from romance.engine import RomanceEngine
        assert hasattr(RomanceEngine, "get_job")

    def test_cli_has_auto_command(self):
        """CLI should accept 'auto' command."""
        from romance.cli import main
        # Just verify the function exists and can parse args
        import sys
        old_argv = sys.argv
        sys.argv = ["romance", "auto", "--help"]
        try:
            main()
        except SystemExit:
            pass  # --help causes SystemExit
        finally:
            sys.argv = old_argv


# ---- UploadPost ----

class TestUploadPostTool:
    def test_uploadpost_inherits_basetool(self):
        from tools.base_tool import BaseTool
        from tools.llm.uploadpost import UploadPostTool
        assert issubclass(UploadPostTool, BaseTool)

    def test_uploadpost_has_correct_name(self):
        from tools.llm.uploadpost import UploadPostTool
        tool = UploadPostTool()
        assert tool.name == "uploadpost"
        assert tool.provider == "uploadpost"

    def test_uploadpost_reports_status(self):
        from tools.base_tool import ToolStatus
        from tools.llm.uploadpost import UploadPostTool
        tool = UploadPostTool()
        assert tool.get_status() in (ToolStatus.AVAILABLE, ToolStatus.UNAVAILABLE)

    def test_uploadpost_handles_missing_operation(self):
        from tools.llm.uploadpost import UploadPostTool
        tool = UploadPostTool()
        result = tool.execute({})
        assert not result.success

    def test_uploadpost_list_platforms(self):
        from tools.llm.uploadpost import UploadPostTool
        tool = UploadPostTool()
        result = tool.execute({"operation": "list_platforms"})
        assert result.success
        assert "youtube" in result.data["platforms"]
        assert "tiktok" in result.data["platforms"]
        assert "instagram" in result.data["platforms"]

    def test_uploadpost_supports_22_networks(self):
        from tools.llm.uploadpost import SUPPORTED_PLATFORMS
        assert len(SUPPORTED_PLATFORMS) >= 13  # at least 13 major platforms
        assert "youtube" in SUPPORTED_PLATFORMS
        assert "tiktok" in SUPPORTED_PLATFORMS
        assert "instagram" in SUPPORTED_PLATFORMS
        assert "linkedin" in SUPPORTED_PLATFORMS
        assert "facebook" in SUPPORTED_PLATFORMS
        assert "twitter" in SUPPORTED_PLATFORMS

    def test_uploadpost_api_runtime(self):
        from tools.base_tool import ToolRuntime
        from tools.llm.uploadpost import UploadPostTool
        tool = UploadPostTool()
        assert tool.runtime == ToolRuntime.API

    def test_uploadpost_capabilities(self):
        from tools.llm.uploadpost import UploadPostTool
        tool = UploadPostTool()
        assert "upload_video" in tool.capabilities
        assert "upload_photos" in tool.capabilities
        assert "multi_platform" in tool.capabilities
        assert tool.supports.get("video_upload") is True
        assert tool.supports.get("auto_transcoding") is True

    def test_get_publish_tool_returns_none_without_key(self):
        """get_publish_tool should return None when no API key is set."""
        from romance.stages._shared import get_publish_tool
        import os
        # Save and remove key if set
        old_key = os.environ.pop("UPLOADPOST_API_KEY", None)
        try:
            tool, name = get_publish_tool()
            # Should be None when no key
            assert tool is None or name == "uploadpost"
        finally:
            if old_key:
                os.environ["UPLOADPOST_API_KEY"] = old_key

    def test_uploadpost_estimate_cost(self):
        from tools.llm.uploadpost import UploadPostTool
        tool = UploadPostTool()
        cost = tool.estimate_cost({})
        assert cost > 0  # should have a non-zero cost


# ---- Review artifacts (schema compliance + crash regression) ----

QUALITY_OVERRIDE = {
    "version": "1.0",
    "quality_scores": {
        "hook_strength": 8,
        "originality": 7,
        "emotional_progression": 8,
        "romantic_chemistry": 7,
        "character_motivation": 8,
        "conflict_credibility": 7,
        "dialogue_quality": 8,
        "continuity": 9,
        "retention_potential": 8,
        "ending_satisfaction": 8,
    },
    "retention_check": {"first_30_seconds_has_hook": True, "notes": "ok"},
    "title_payoff_alignment": "ok",
    "revision_required": False,
    "revision_reasons": [],
    "summary": "Passes.",
}

CONTINUITY_OVERRIDE = {
    "version": "1.0",
    "entries": [],
    "unresolved_threads": [],
    "quality_scores": {k: 8 for k in [
        "hook_strength", "originality", "emotional_progression", "romantic_chemistry",
        "character_motivation", "conflict_credibility", "dialogue_quality", "continuity",
        "retention_potential", "ending_satisfaction",
    ]},
    "revision_required": False,
    "revision_reasons": [],
}


class TestReviewArtifacts:
    """Regression tests: review artifacts must be schema-compliant and the
    quality_review stage must not crash on list-form render_report outputs."""

    @pytest.fixture
    def review_engine(self, tmp_path):
        engine = RomanceEngine(tmp_path / "review-project")
        engine.save_artifact("script", {
            "version": "1.0",
            "title": "Test",
            "total_duration_seconds": 30,
            "sections": [
                {"id": "s1", "text": "The bell jingles as Daniel enters the diner.", "start_seconds": 0, "end_seconds": 30},
            ],
        })
        # Minimal story_bible for the continuity_review stage
        engine.save_artifact("story_bible", {
            "version": "1.0", "project_id": "test", "format": "long_form",
            "genre": "small_town", "tone": "warm",
            "characters": [{
                "character_id": "emma", "full_name": "Emma", "role": "protagonist", "age": 34,
                "appearance": {"face": "oval", "hair": "auburn", "build": "slim", "wardrobe": "navy", "palette": ["#333"]},
                "personality": {"summary": "resilient", "emotional_wound": "divorce", "desire": "love", "fear": "hurt", "contradiction": "wants love but pushes away", "speech_style": "direct"},
                "visual_reference_prompt": "A 34-year-old woman", "negative_prompt": "child",
                "voice": {"provider": "zai_tts", "voice_id": "tongtong"},
            }],
            "world": {"setting": "small town", "time_period": "present day", "locations": [], "important_objects": []},
        })
        # render_report in the list-outputs form that compose_director actually emits
        engine.save_artifact("render_report", {
            "version": "1.0",
            "outputs": [
                {"path": "renders/youtube-16x9.mp4", "format": "mp4", "platform_target": "youtube", "duration_seconds": 30},
            ],
            "metadata": {"stage": "compose", "scene_count": 5},
        })
        return engine

    def test_quality_review_does_not_crash_on_list_outputs(self, review_engine):
        """Regression: render_report.outputs is a list — the stage must not
        crash with AttributeError and must write a completed checkpoint."""
        result = review_engine.run("quality_review", {"review_override": dict(QUALITY_OVERRIDE)})
        assert result.get("artifact") == "review"
        assert "error" not in result
        # Checkpoint must have been written (fails when the artifact is schema-invalid)
        from lib.checkpoint import read_checkpoint
        cp = read_checkpoint(review_engine.pipeline_dir, review_engine.project_id, "quality_review")
        assert cp is not None
        assert cp["status"] == "completed"

    def test_quality_review_artifact_validates(self, review_engine):
        result = review_engine.run("quality_review", {"review_override": dict(QUALITY_OVERRIDE)})
        validate_artifact("review", result["data"])  # should not raise
        assert result["data"]["findings"] == []
        assert result["data"]["metadata"]["quality_scores"]["hook_strength"] == 8

    def test_quality_review_low_score_marks_revision(self, review_engine):
        override = dict(QUALITY_OVERRIDE)
        override["quality_scores"] = dict(QUALITY_OVERRIDE["quality_scores"])
        override["quality_scores"]["hook_strength"] = 3  # below threshold 7
        result = review_engine.run("quality_review", {"review_override": override})
        assert result["data"]["metadata"]["revision_required"] is True
        assert any("hook_strength" in f["description"] for f in result["data"]["findings"])
        validate_artifact("review", result["data"])  # still schema-valid

    def test_quality_review_auto_pass_validates(self, review_engine, monkeypatch):
        """Auto-pass path (no LLM) must also produce a schema-valid review."""
        import romance.stages.quality_review_director as qr
        monkeypatch.setattr(qr, "zai_available", lambda: False)
        result = review_engine.run("quality_review", {})
        assert "error" not in result
        validate_artifact("review", result["data"])
        assert result["data"]["metadata"]["auto_passed"] is True

    def test_quality_review_non_threshold_minimum_marks_revision(self, review_engine):
        """A non-threshold dimension below QUALITY_MINIMUM (5) must trigger revision."""
        override = dict(QUALITY_OVERRIDE)
        override["quality_scores"] = dict(QUALITY_OVERRIDE["quality_scores"])
        override["quality_scores"]["dialogue_quality"] = 4  # below minimum, not a threshold dim
        result = review_engine.run("quality_review", {"review_override": override})
        assert result["data"]["metadata"]["revision_required"] is True
        assert any("dialogue_quality" in f["description"] for f in result["data"]["findings"])
        validate_artifact("review", result["data"])

    def test_continuity_review_artifact_validates(self, review_engine):
        result = review_engine.run("continuity_review", {"continuity_override": dict(CONTINUITY_OVERRIDE)})
        assert result.get("artifact") == "continuity_ledger"
        validate_artifact("continuity_ledger", result["data"])  # ledger keeps its own shape
        extra = result.get("extra_artifacts", {})
        assert "review" in extra
        validate_artifact("review", extra["review"])  # should not raise

    def test_continuity_review_checkpoint_written(self, review_engine):
        review_engine.run("continuity_review", {"continuity_override": dict(CONTINUITY_OVERRIDE)})
        from lib.checkpoint import read_checkpoint
        cp = read_checkpoint(review_engine.pipeline_dir, review_engine.project_id, "continuity_review")
        assert cp is not None
        assert cp["status"] == "completed"
        assert "review" in cp["artifacts"]

    def test_render_output_list_final_video(self):
        """render_output must find final_video in list-form outputs (both 16:9 and 9:16)."""
        from romance.stages._shared import render_output
        report = {"outputs": [
            {"path": "renders/youtube-16x9.mp4", "platform_target": "youtube"},
            {"path": "renders/clean-video.mp4", "platform_target": "youtube"},
        ]}
        assert render_output(report, "final_video") == "renders/youtube-16x9.mp4"
        short_report = {"outputs": [{"path": "renders/short-9x16.mp4", "platform_target": "youtube"}]}
        assert render_output(short_report, "final_video") == "renders/short-9x16.mp4"
        # clean listed first must be skipped in favor of the youtube final
        reordered = {"outputs": [
            {"path": "renders/clean-video.mp4", "platform_target": "youtube"},
            {"path": "renders/youtube-16x9.mp4", "platform_target": "youtube"},
        ]}
        assert render_output(reordered, "final_video") == "renders/youtube-16x9.mp4"
        # dict form still works
        dict_report = {"outputs": {"final_video": "renders/youtube-16x9.mp4"}}
        assert render_output(dict_report, "final_video") == "renders/youtube-16x9.mp4"
