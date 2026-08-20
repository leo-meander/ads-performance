"""Regression tests for the TikTok Smart+ ad-name overflow.

On 2026-08-20 the Osaka TikTok advertiser stopped syncing entirely. The cause
was one auto-generated ad whose ad_name is the entire caption (~750 chars)
against a VARCHAR(500) column: Postgres raises StringDataRightTruncation rather
than truncating, and that aborts the whole transaction — so the live campaign
`Mason_OSK_[TOF] Lead US` never reached the database at all, and the branch
looked like it simply wasn't running ads.

What matters here:
  - names are fitted at the MODEL layer, so no write path can reintroduce it
  - fitting is deterministic, or a re-sync of an unchanged ad would look like a
    rename and fork its combo (see test_creative_rename)
  - two names sharing a 500-char prefix stay distinct — TikTok's generated
    names differ only in the timestamp they END with
"""
from __future__ import annotations

import uuid

from app.core.name_fit import NAME_MAX, fit_name

# The real shape of the name that broke the sync: a caption ending in a stamp.
_CAPTION = (
    "Send this to the friend who's always in charge of planning the trip. "
    "We've already done the hard part. " + ("We explored Osaka ourselves. " * 20)
)


def test_short_names_pass_through_untouched():
    assert fit_name("Mason_OSK_[TOF] Lead US") == "Mason_OSK_[TOF] Lead US"
    assert fit_name(None) is None
    exact = "x" * NAME_MAX
    assert fit_name(exact) == exact


def test_long_name_is_fitted_to_the_column_width():
    long_name = _CAPTION + "_Ad name2026-08-19 05:23:18"
    assert len(long_name) > NAME_MAX
    fitted = fit_name(long_name)
    assert len(fitted) == NAME_MAX
    assert fitted.startswith("Send this to the friend")


def test_fitting_is_deterministic():
    """A re-sync must produce the identical name or it reads as a rename."""
    long_name = _CAPTION + "_Ad name2026-08-19 05:23:18"
    assert fit_name(long_name) == fit_name(long_name)


def test_names_differing_only_in_their_tail_stay_distinct():
    """A plain head-cut would collide these two into one combo."""
    a = fit_name(_CAPTION + "_Ad name2026-08-19 05:23:18")
    b = fit_name(_CAPTION + "_Ad name2026-08-19 09:41:02")
    assert a != b
    assert len(a) == len(b) == NAME_MAX


def test_model_fits_the_name_on_assignment():
    """The guard lives on the model, so every write path inherits it."""
    from app.models.account import AdAccount
    from app.models.ad import Ad
    from app.models.ad_set import AdSet
    from app.models.campaign import Campaign
    from tests.db import TestSession

    long_name = _CAPTION + "_Ad name2026-08-19 05:23:18"
    db = TestSession()
    try:
        account = AdAccount(
            id=str(uuid.uuid4()), platform="tiktok", account_id="adv_1",
            account_name="Meander Osaka TikTok", currency="JPY", is_active=True,
        )
        campaign = Campaign(
            id=str(uuid.uuid4()), account_id=account.id, platform="tiktok",
            platform_campaign_id="c1", name="Mason_OSK_[TOF] Lead  US", status="ACTIVE",
        )
        adset = AdSet(
            id=str(uuid.uuid4()), campaign_id=campaign.id, account_id=account.id,
            platform="tiktok", platform_adset_id="ag1", name="US_adgroup", status="ACTIVE",
        )
        ad = Ad(
            id=str(uuid.uuid4()), ad_set_id=adset.id, campaign_id=campaign.id,
            account_id=account.id, platform="tiktok", platform_ad_id="1873939420337489",
            name=long_name, status="ACTIVE",
        )
        db.add_all([account, campaign, adset, ad])
        db.commit()

        stored = db.query(Ad).filter(Ad.platform_ad_id == "1873939420337489").one()
        assert len(stored.name) == NAME_MAX
        assert stored.name == fit_name(long_name)
        # The campaign alongside it is short and must be left alone.
        assert db.query(Campaign).one().name == "Mason_OSK_[TOF] Lead  US"
    finally:
        db.rollback()
        db.close()
