"""One bad row must not cost a whole import phase.

Every asset-group ad-link in prod froze at a single timestamp and stayed
frozen for nine days: the scan loops caught exceptions per item, but the
INSERTs stayed pending until the phase commit, so a constraint violation
surfaced there instead — after the loop, with the phase's work rolled back and
the offending row unidentified. The scans now take a SAVEPOINT and flush per
item, so a failure is attributed and skipped while the rest still land.
"""
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.landing_page import LandingPage
from app.models.landing_page_ad_link import LandingPageAdLink
from app.services import landing_page_importer as importer


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _page(db, slug):
    page = LandingPage(
        id=str(uuid.uuid4()),
        source="external",
        title=slug,
        domain="osk.staymeander.com",
        slug=slug,
        status="published",
        is_active=True,
    )
    db.add(page)
    db.commit()
    return page


def _summary():
    return {
        "pages_created": 0,
        "ad_links_created": 0,
        "ad_links_updated": 0,
        "google_urls_found": 0,
        "errors": 0,
        "error_samples": [],
    }


def _link_one(db, summary, page, url, now):
    """Drive _link_urls the way a scan phase does, inside a savepoint."""
    with db.begin_nested():
        importer._link_urls(
            db,
            summary,
            [url],
            platform="google",
            campaign_id=None,
            ad_id=None,
            ad_set_id=None,
            asset_group_id=str(uuid.uuid4()),
            now=now,
            url_counter="google_urls_found",
        )
        db.flush()


def test_a_failing_item_does_not_discard_the_ones_around_it(db, monkeypatch):
    from datetime import datetime, timezone

    now = datetime(2026, 7, 28, tzinfo=timezone.utc)
    good_a = _page(db, "couple-explore-osaka")
    good_b = _page(db, "friend-group-v2")
    bad = _page(db, "poison")

    real = importer.get_or_create_external_page

    def fake(db_, *, raw_url, **kw):
        if "poison" in raw_url:
            raise RuntimeError("constraint violation on flush")
        return {
            "https://osk.staymeander.com/couple-explore-osaka": good_a,
            "https://osk.staymeander.com/friend-group-v2": good_b,
        }[raw_url]

    monkeypatch.setattr(importer, "get_or_create_external_page", fake)

    summary = _summary()
    for url in (
        "https://osk.staymeander.com/couple-explore-osaka",
        "https://osk.staymeander.com/poison",
        "https://osk.staymeander.com/friend-group-v2",
    ):
        try:
            _link_one(db, summary, None, url, now)
        except Exception as e:
            importer._record_item_error(summary, f"item:{url}", e)
    db.commit()

    importer.get_or_create_external_page = real

    # The poisoned item is the only casualty.
    assert summary["errors"] == 1
    assert summary["ad_links_created"] == 2
    assert db.query(LandingPageAdLink).count() == 2
    linked_pages = {l.landing_page_id for l in db.query(LandingPageAdLink).all()}
    assert linked_pages == {good_a.id, good_b.id}
    assert bad.id not in linked_pages


def test_error_samples_name_the_failing_item():
    summary = _summary()
    importer._record_item_error(summary, "asset-group:ag-1", ValueError("boom"))

    assert summary["errors"] == 1
    assert summary["error_samples"] == ["asset-group:ag-1: ValueError: boom"]


def test_error_samples_are_capped():
    summary = _summary()
    for i in range(25):
        importer._record_item_error(summary, f"item:{i}", ValueError("boom"))

    assert summary["errors"] == 25
    assert len(summary["error_samples"]) == 10
