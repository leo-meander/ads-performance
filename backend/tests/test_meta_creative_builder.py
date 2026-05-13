"""Unit tests for the Figma → Meta creative pipeline.

Covers:
  - CTA keyword mapping (multilingual + default fallback)
  - Happy path: Figma render → adimages upload → adcreative create
  - Hash cache: a second call skips render+upload
  - Error paths: missing page_id, missing destination URL, missing
    figma_file_key/figma_node_id, missing material/copy

All external IO (Figma REST, Meta SDK, httpx) is mocked.
"""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.account import AdAccount
from app.models.ad_combo import AdCombo
from app.models.ad_copy import AdCopy
from app.models.ad_material import AdMaterial
from app.models.base import Base
from app.services.figma_client import FigmaExport
from app.services.meta_creative_builder import (
    CreativeBuilderError,
    build_or_get_meta_creative,
    meta_cta_for,
)


# ── Fixtures ─────────────────────────────────────────────────


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def _make_account(db, **overrides) -> AdAccount:
    defaults = dict(
        id=str(uuid.uuid4()),
        platform="meta",
        account_id="123456789",
        account_name="Meander Saigon",
        currency="VND",
        access_token_enc="fake-token",
        meta_page_id="page_42",
        default_destination_url="https://meandersaigon.com/book",
    )
    defaults.update(overrides)
    account = AdAccount(**defaults)
    db.add(account)
    db.commit()
    return account


def _make_material(db, branch_id, **overrides) -> AdMaterial:
    defaults = dict(
        id=str(uuid.uuid4()),
        branch_id=branch_id,
        material_id="MAT-001",
        material_type="image",
        file_url="https://drive.google.com/file/d/foo/view",
        figma_file_key="FIGFILEKEY",
        figma_node_id="2:1",
    )
    defaults.update(overrides)
    material = AdMaterial(**defaults)
    db.add(material)
    db.commit()
    return material


def _make_copy(db, branch_id, **overrides) -> AdCopy:
    defaults = dict(
        id=str(uuid.uuid4()),
        branch_id=branch_id,
        copy_id="CPY-001",
        target_audience="Solo",
        headline="Stay in Saigon",
        body_text="Boutique hostel in the heart of D1.",
        cta="Book Now",
        language="en",
    )
    defaults.update(overrides)
    copy = AdCopy(**defaults)
    db.add(copy)
    db.commit()
    return copy


def _make_combo(db, branch_id, **overrides) -> AdCombo:
    defaults = dict(
        id=str(uuid.uuid4()),
        branch_id=branch_id,
        combo_id="CMB-001",
        copy_id="CPY-001",
        material_id="MAT-001",
    )
    defaults.update(overrides)
    combo = AdCombo(**defaults)
    db.add(combo)
    db.commit()
    return combo


# ── CTA mapping ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Book Now", "BOOK_TRAVEL"),
        ("Đặt phòng ngay", "BOOK_TRAVEL"),
        ("予約する", "BOOK_TRAVEL"),
        ("立即預訂", "BOOK_TRAVEL"),
        ("Shop Now", "SHOP_NOW"),
        ("Mua ngay hôm nay", "SHOP_NOW"),
        ("Sign Up Today", "SIGN_UP"),
        ("Đăng ký miễn phí", "SIGN_UP"),
        ("Contact us for details", "CONTACT_US"),
        ("Get Offer", "GET_OFFER"),
        ("Download the brochure", "DOWNLOAD"),
        ("Order Now", "ORDER_NOW"),
        ("Learn More", "LEARN_MORE"),
        ("", "LEARN_MORE"),
        (None, "LEARN_MORE"),
        ("totally unrecognised string", "LEARN_MORE"),
    ],
)
def test_cta_mapping(text, expected):
    assert meta_cta_for(text) == expected


# ── Happy path ───────────────────────────────────────────────


@patch("app.services.meta_creative_builder._create_adcreative")
@patch("app.services.meta_creative_builder._upload_adimage")
@patch("app.services.meta_creative_builder._download")
def test_builds_creative_from_figma(mock_download, mock_upload, mock_create, db):
    mock_download.return_value = b"png-bytes"
    mock_upload.return_value = "hash_xyz"
    mock_create.return_value = "creative_777"

    account = _make_account(db)
    _make_material(db, branch_id=account.id)
    _make_copy(db, branch_id=account.id)
    combo = _make_combo(db, branch_id=account.id)

    fake_figma = MagicMock()
    fake_figma.export_images.return_value = [
        FigmaExport(node_id="2:1", image_url="https://figma-cdn.example/foo.png", format="png")
    ]

    cid = build_or_get_meta_creative(db, account, combo, figma_client=fake_figma)
    assert cid == "creative_777"

    fake_figma.export_images.assert_called_once_with("FIGFILEKEY", ["2:1"], fmt="png")
    mock_download.assert_called_once_with("https://figma-cdn.example/foo.png", http_client=None)
    mock_upload.assert_called_once_with(account, b"png-bytes")

    # Creative ships with the right page + copy + mapped CTA.
    kwargs = mock_create.call_args.kwargs
    assert kwargs["page_id"] == "page_42"
    assert kwargs["image_hash"] == "hash_xyz"
    assert kwargs["headline"] == "Stay in Saigon"
    assert kwargs["cta_type"] == "BOOK_TRAVEL"
    assert kwargs["link"] == "https://meandersaigon.com/book"

    # Cache persisted.
    mat = db.query(AdMaterial).filter(AdMaterial.material_id == "MAT-001").first()
    assert mat.meta_image_hash == "hash_xyz"


@patch("app.services.meta_creative_builder._create_adcreative")
@patch("app.services.meta_creative_builder._upload_adimage")
@patch("app.services.meta_creative_builder._download")
def test_second_launch_uses_cached_hash(mock_download, mock_upload, mock_create, db):
    """Once meta_image_hash is set, render+upload must be skipped."""
    mock_create.return_value = "creative_reused"

    account = _make_account(db)
    _make_material(db, branch_id=account.id, meta_image_hash="cached_hash")
    _make_copy(db, branch_id=account.id)
    combo = _make_combo(db, branch_id=account.id)

    fake_figma = MagicMock()
    cid = build_or_get_meta_creative(db, account, combo, figma_client=fake_figma)
    assert cid == "creative_reused"

    fake_figma.export_images.assert_not_called()
    mock_download.assert_not_called()
    mock_upload.assert_not_called()

    # AdCreative still built with the cached hash.
    assert mock_create.call_args.kwargs["image_hash"] == "cached_hash"


# ── Error paths ──────────────────────────────────────────────


def test_raises_when_meta_page_id_missing(db):
    account = _make_account(db, meta_page_id=None)
    _make_material(db, branch_id=account.id)
    _make_copy(db, branch_id=account.id)
    combo = _make_combo(db, branch_id=account.id)

    with pytest.raises(CreativeBuilderError, match="meta_page_id"):
        build_or_get_meta_creative(db, account, combo)


def test_raises_when_destination_url_missing(db):
    account = _make_account(db, default_destination_url=None)
    _make_material(db, branch_id=account.id, meta_image_hash="cached")
    _make_copy(db, branch_id=account.id)
    combo = _make_combo(db, branch_id=account.id)

    with pytest.raises(CreativeBuilderError, match="default_destination_url"):
        build_or_get_meta_creative(db, account, combo)


def test_raises_when_no_figma_source(db):
    account = _make_account(db)
    _make_material(db, branch_id=account.id, figma_file_key=None, figma_node_id=None)
    _make_copy(db, branch_id=account.id)
    combo = _make_combo(db, branch_id=account.id)

    with pytest.raises(CreativeBuilderError, match="Drive-only sources"):
        build_or_get_meta_creative(db, account, combo)


def test_raises_when_material_missing(db):
    account = _make_account(db)
    _make_copy(db, branch_id=account.id)
    combo = _make_combo(db, branch_id=account.id)

    with pytest.raises(CreativeBuilderError, match="Material MAT-001 not found"):
        build_or_get_meta_creative(db, account, combo)


def test_raises_when_copy_missing(db):
    account = _make_account(db)
    _make_material(db, branch_id=account.id, meta_image_hash="cached")
    combo = _make_combo(db, branch_id=account.id)

    with pytest.raises(CreativeBuilderError, match="Copy CPY-001 not found"):
        build_or_get_meta_creative(db, account, combo)
