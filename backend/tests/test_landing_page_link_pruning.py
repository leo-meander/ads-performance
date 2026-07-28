"""Stale PMax ad-link pruning.

The importer only ever upserted, so a Performance Max asset group repointed at
a new landing page kept its old link forever and the old page went on
collecting that campaign's entire spend. These cover the pruning that ends it.
"""
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.google_asset_group import GoogleAssetGroup
from app.models.landing_page_ad_link import LandingPageAdLink
from app.services.landing_page_importer import _prune_asset_group_links

OLD_URL = "https://1948.staymeander.com/solo-traveler-direct-zh"
NEW_URL = "https://1948.staymeander.com/taipei-heritage-hotel-cn"
SEEN_AT = datetime(2026, 5, 1, tzinfo=timezone.utc)


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _asset_group(db, final_urls):
    """Pruning only reads ag.id and the link table, so the parent campaign and
    account rows are irrelevant here."""
    ag = GoogleAssetGroup(
        id=str(uuid.uuid4()),
        campaign_id=str(uuid.uuid4()),
        account_id=str(uuid.uuid4()),
        platform_asset_group_id="ag-1",
        name="Solo ZH TW",
        status="ACTIVE",
        final_urls=final_urls,
    )
    db.add(ag)
    db.commit()
    return ag


def _link(db, ag, destination_url, *, asset_group_id=...):
    link = LandingPageAdLink(
        id=str(uuid.uuid4()),
        landing_page_id=str(uuid.uuid4()),
        platform="google",
        campaign_id=ag.campaign_id,
        asset_group_id=ag.id if asset_group_id is ... else asset_group_id,
        destination_url=destination_url,
        discovered_at=SEEN_AT,
        last_seen_at=SEEN_AT,
    )
    db.add(link)
    db.commit()
    return link


def test_link_to_a_url_no_longer_in_final_urls_is_removed(db):
    ag = _asset_group(db, [NEW_URL])
    stale_id = _link(db, ag, OLD_URL).id

    removed = _prune_asset_group_links(db, ag, [NEW_URL])
    db.commit()

    assert removed == 1
    assert db.query(LandingPageAdLink).filter_by(id=stale_id).first() is None


def test_link_still_in_final_urls_is_kept(db):
    ag = _asset_group(db, [NEW_URL])
    keep = _link(db, ag, NEW_URL)

    removed = _prune_asset_group_links(db, ag, [NEW_URL])
    db.commit()

    assert removed == 0
    assert db.query(LandingPageAdLink).filter_by(id=keep.id).first() is not None


def test_utm_and_trailing_slash_differences_do_not_count_as_stale(db):
    """Links are stored with whatever URL was seen; only the canonical part
    identifies the page, so query strings must not trigger a delete."""
    ag = _asset_group(db, [NEW_URL])
    keep = _link(db, ag, NEW_URL + "/?utm_source=google&utm_campaign=x")

    removed = _prune_asset_group_links(db, ag, [NEW_URL])
    db.commit()

    assert removed == 0
    assert db.query(LandingPageAdLink).filter_by(id=keep.id).first() is not None


def test_links_belonging_to_other_sources_are_untouched(db):
    """Meta links and Clarity-derived campaign-level links carry no
    asset_group_id and must never be pruned by this pass."""
    ag = _asset_group(db, [NEW_URL])
    other = _link(db, ag, OLD_URL, asset_group_id=None)

    removed = _prune_asset_group_links(db, ag, [NEW_URL])
    db.commit()

    assert removed == 0
    assert db.query(LandingPageAdLink).filter_by(id=other.id).first() is not None


def test_every_link_goes_when_final_urls_is_emptied(db):
    ag = _asset_group(db, [])
    ids = [_link(db, ag, OLD_URL).id, _link(db, ag, NEW_URL).id]

    removed = _prune_asset_group_links(db, ag, [])
    db.commit()

    assert removed == 2
    assert db.query(LandingPageAdLink).filter(LandingPageAdLink.id.in_(ids)).count() == 0


def test_unparseable_destination_is_pruned(db):
    ag = _asset_group(db, [NEW_URL])
    junk_id = _link(db, ag, "not-a-url").id

    removed = _prune_asset_group_links(db, ag, [NEW_URL])
    db.commit()

    assert removed == 1
    assert db.query(LandingPageAdLink).filter_by(id=junk_id).first() is None
