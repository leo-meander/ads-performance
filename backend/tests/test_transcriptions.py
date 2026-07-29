"""Tests for transcription endpoints and AI classifier."""

import json
import uuid
from datetime import datetime, timezone
import requests
from unittest.mock import MagicMock, patch

import pytest

from app.models.video_transcript import VideoTranscript
from app.models.ad_material import AdMaterial
from app.models.ad_combo import AdCombo
from app.models.ad_angle import AdAngle, ANGLE_TYPES
from app.models.ad_copy import AdCopy
from app.models.keypoint import BranchKeypoint
from app.models.account import AdAccount
from tests.db import TestSession


# ── Test DB ──────────────────────────────────────────────────
@pytest.fixture
def db():
    session = TestSession()
    yield session
    session.close()


@pytest.fixture
def sample_account(db):
    acc = AdAccount(
        id=str(uuid.uuid4()),
        platform="meta",
        account_id="act_123",
        account_name="Test Branch",
        currency="VND",
        is_active=True,
    )
    db.add(acc)
    db.commit()
    return acc


@pytest.fixture
def sample_material(db, sample_account):
    mat = AdMaterial(
        id=str(uuid.uuid4()),
        branch_id=sample_account.id,
        material_id="MAT-001",
        material_type="video",
        file_url="https://example.com/video.mp4",
    )
    db.add(mat)
    db.commit()
    return mat


# ── AI Classifier Tests ─────────────────────────────────────
class TestAIClassifier:
    def test_classify_prompt_has_all_angle_types(self):
        from app.services.ai_classifier import _ANGLE_LIST
        for angle in ANGLE_TYPES:
            assert angle in _ANGLE_LIST

    @patch("app.services.ai_classifier.anthropic")
    def test_classify_transcript_returns_dict(self, mock_anthropic):
        mock_client = MagicMock()
        mock_anthropic.Anthropic.return_value = mock_client

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=json.dumps({
            "suggested_angle_type": "Before and After",
            "suggested_angle_explain": "Shows transformation",
            "suggested_hook_examples": ["See the difference"],
            "suggested_keypoints": [
                {"category": "experience", "title": "Stunning rooftop view"},
            ],
            "detected_ta": "Couple",
            "tone": "aspirational",
            "summary": "Hotel experience ad",
        }))]
        mock_client.messages.create.return_value = mock_response

        from app.services.ai_classifier import classify_transcript
        with patch("app.services.ai_classifier.settings") as mock_settings:
            mock_settings.ANTHROPIC_API_KEY = "test-key"
            result = classify_transcript("Beautiful hotel with stunning views...", "Test Branch", "en")

        assert result["suggested_angle_type"] == "Before and After"
        assert len(result["suggested_keypoints"]) == 1
        assert result["detected_ta"] == "Couple"
        assert result["tone"] == "aspirational"

    @patch("app.services.ai_classifier.anthropic")
    def test_classify_handles_code_block_response(self, mock_anthropic):
        mock_client = MagicMock()
        mock_anthropic.Anthropic.return_value = mock_client

        # Claude sometimes wraps JSON in code blocks
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='```json\n{"suggested_angle_type": "Use an authority", "suggested_angle_explain": "test", "suggested_hook_examples": [], "suggested_keypoints": [], "detected_ta": null, "tone": "informational", "summary": "test"}\n```')]
        mock_client.messages.create.return_value = mock_response

        from app.services.ai_classifier import classify_transcript
        with patch("app.services.ai_classifier.settings") as mock_settings:
            mock_settings.ANTHROPIC_API_KEY = "test-key"
            result = classify_transcript("Some ad transcript here for testing.", "Branch", "en")

        assert result["suggested_angle_type"] == "Use an authority"

    def test_classify_rejects_short_transcript(self):
        from app.services.ai_classifier import classify_transcript
        with pytest.raises(ValueError, match="too short"):
            classify_transcript("Hi", "Branch", "en")


# ── Video Transcript Model Tests ─────────────────────────────
class TestVideoTranscriptModel:
    def test_create_transcript(self, db):
        t = VideoTranscript(
            id=str(uuid.uuid4()),
            video_url="https://example.com/video.mp4",
            status="PENDING",
        )
        db.add(t)
        db.commit()

        found = db.query(VideoTranscript).first()
        assert found is not None
        assert found.status == "PENDING"
        assert found.video_url == "https://example.com/video.mp4"

    def test_transcript_with_analysis(self, db):
        analysis = {
            "suggested_angle_type": "Before and After",
            "suggested_keypoints": [{"category": "amenity", "title": "Pool"}],
        }
        t = VideoTranscript(
            id=str(uuid.uuid4()),
            video_url="https://example.com/v.mp4",
            transcript="Beautiful pool with mountain views",
            language="en",
            ai_analysis=analysis,
            status="COMPLETED",
            processing_time_seconds=15.3,
        )
        db.add(t)
        db.commit()

        found = db.query(VideoTranscript).first()
        assert found.transcript == "Beautiful pool with mountain views"
        assert found.ai_analysis["suggested_angle_type"] == "Before and After"
        assert found.processing_time_seconds == 15.3

    def test_transcript_linked_to_material(self, db, sample_material):
        t = VideoTranscript(
            id=str(uuid.uuid4()),
            video_url=sample_material.file_url,
            material_id=sample_material.id,
            status="PENDING",
        )
        db.add(t)
        db.commit()

        found = db.query(VideoTranscript).first()
        assert found.material_id == sample_material.id


# ── Transcription Service Tests ──────────────────────────────
class TestTranscriptionService:
    def test_download_direct_converts_gdrive_url(self):
        import requests as real_requests
        from app.services.transcription_service import _download_direct
        import tempfile
        import os

        mock_resp = MagicMock()
        mock_resp.iter_content.return_value = [b"fake video data"]
        mock_resp.raise_for_status = MagicMock()

        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.object(real_requests, "get", return_value=mock_resp) as mock_get:
            dest = os.path.join(tmpdir, "test.mp4")
            _download_direct("https://drive.google.com/file/d/ABC123/view?usp=sharing", dest)

            # Should convert to direct download URL
            call_url = mock_get.call_args[0][0]
            assert "uc?export=download" in call_url
            assert "ABC123" in call_url

    def test_needs_ytdlp_detection(self):
        from app.services.transcription_service import _needs_ytdlp
        assert _needs_ytdlp("https://www.facebook.com/page/videos/123") is True
        assert _needs_ytdlp("https://fb.watch/abc") is True
        assert _needs_ytdlp("https://www.instagram.com/reel/123") is True
        assert _needs_ytdlp("https://www.tiktok.com/@user/video/123") is True
        assert _needs_ytdlp("https://example.com/video.mp4") is False
        assert _needs_ytdlp("https://drive.google.com/file/d/abc") is False
