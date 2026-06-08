"""Tests for the Meta creative preview-URL resolver (quality + helpers)."""
import io
from unittest.mock import patch

from PIL import Image

from app.services.material_url_sync import (
    _collect_image_hashes,
    _extract_preview_url,
    _parse_meta_time,
    _snapshot_data_url,
)


def _png_bytes(size=(1200, 1200), color=(120, 60, 200)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


class _FakeResp:
    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        pass


def test_extract_prefers_image_url():
    assert _extract_preview_url({"image_url": "FULL", "thumbnail_url": "tiny"}) == "FULL"


def test_extract_prefers_asset_feed_image_over_thumbnail():
    c = {"thumbnail_url": "tiny", "asset_feed_spec": {"images": [{"url": "BIG"}]}}
    assert _extract_preview_url(c) == "BIG"


def test_extract_thumbnail_is_last_resort():
    # Only a thumbnail available → use it, but only because nothing fuller exists.
    assert _extract_preview_url({"thumbnail_url": "tiny"}) == "tiny"


def test_extract_link_picture_beats_thumbnail():
    c = {
        "thumbnail_url": "tiny",
        "object_story_spec": {"link_data": {"picture": "PIC"}},
    }
    assert _extract_preview_url(c) == "PIC"


def test_extract_none_when_empty():
    assert _extract_preview_url({}) is None


def test_collect_image_hashes_deduped_in_order():
    c = {
        "object_story_spec": {
            "link_data": {
                "image_hash": "h1",
                "child_attachments": [{"image_hash": "h2"}],
            }
        },
        "asset_feed_spec": {"images": [{"hash": "h3"}, {"hash": "h1"}]},
    }
    assert _collect_image_hashes(c) == ["h1", "h2", "h3"]


def test_collect_image_hashes_empty():
    assert _collect_image_hashes({}) == []


def test_parse_meta_time_offset():
    dt = _parse_meta_time("2026-04-01T10:00:00+0700")
    assert dt is not None
    assert dt.utcoffset().total_seconds() == 7 * 3600


def test_parse_meta_time_invalid():
    assert _parse_meta_time("not-a-date") is None
    assert _parse_meta_time(None) is None


def test_snapshot_returns_jpeg_data_url():
    with patch("app.services.material_url_sync.requests.get",
               return_value=_FakeResp(_png_bytes())):
        out = _snapshot_data_url("https://meta.cdn/expiring.png")
    assert out is not None
    assert out.startswith("data:image/jpeg;base64,")


def test_snapshot_respects_max_dim_and_byte_cap():
    from app.config import settings
    with patch("app.services.material_url_sync.requests.get",
               return_value=_FakeResp(_png_bytes((4000, 4000)))):
        out = _snapshot_data_url("https://meta.cdn/huge.png")
    assert out is not None
    # Decode the base64 payload and confirm it fits both caps.
    import base64
    raw = base64.b64decode(out.split(",", 1)[1])
    assert len(raw) <= settings.CREATIVE_SNAPSHOT_MAX_BYTES
    img = Image.open(io.BytesIO(raw))
    assert max(img.size) <= settings.CREATIVE_SNAPSHOT_MAX_DIM


def test_snapshot_returns_none_on_download_failure():
    with patch("app.services.material_url_sync.requests.get",
               side_effect=Exception("network down")):
        assert _snapshot_data_url("https://meta.cdn/x.png") is None
