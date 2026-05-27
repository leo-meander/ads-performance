"""Tests for the Meta creative preview-URL resolver (quality + helpers)."""
from app.services.material_url_sync import (
    _collect_image_hashes,
    _extract_preview_url,
    _parse_meta_time,
)


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
