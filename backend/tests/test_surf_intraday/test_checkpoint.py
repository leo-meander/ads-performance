"""Tests for the SurfRun + SurfCheckpoint persistence layer.

These run against the SQLite test DB (created by conftest), so they
exercise both ORM semantics + the UNIQUE / CHECK constraints from
migration 043.
"""

import uuid
from datetime import date, datetime, timezone

import pytest

from app.models import AdAccount, Campaign, SurfCheckpoint, SurfRun, Tactic
from app.models.surf import (
    NO_ACTION,
    SURF_RUN_STATUS_ACTIVE,
    SURF_RUN_STATUS_CAPPED,
    TIER_2,
)
from app.services.surf_intraday.checkpoint import (
    append_checkpoint,
    get_or_create_run,
    latest_checkpoint,
    local_date_for,
    update_run_after_action,
    was_noop_at_threshold,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def saigon_account(db):
    acc = AdAccount(
        id=str(uuid.uuid4()), platform="meta", account_id="act_saigon",
        account_name="Meander Saigon", currency="VND", is_active=True,
        timezone="Asia/Ho_Chi_Minh",
    )
    db.add(acc); db.commit(); db.refresh(acc)
    return acc


@pytest.fixture
def osaka_account(db):
    acc = AdAccount(
        id=str(uuid.uuid4()), platform="meta", account_id="act_osaka",
        account_name="Meander Osaka", currency="JPY", is_active=True,
        timezone="Asia/Tokyo",
    )
    db.add(acc); db.commit(); db.refresh(acc)
    return acc


@pytest.fixture
def tactic_for(db, saigon_account):
    t = Tactic(
        name="surf-test", preset_type="surf_intraday_campaign",
        platform="meta", account_id=saigon_account.id,
        config={"dry_run": True}, is_active=True,
    )
    db.add(t); db.commit(); db.refresh(t)
    return t


@pytest.fixture
def campaign_for(db, saigon_account):
    c = Campaign(
        id=str(uuid.uuid4()), platform="meta", account_id=saigon_account.id,
        name="C1", platform_campaign_id="1001", status="ACTIVE",
        daily_budget=300,
    )
    db.add(c); db.commit(); db.refresh(c)
    return c


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLocalDateFor:
    def test_saigon_morning(self):
        """16:30 UTC = 23:30 Saigon → today still."""
        d = local_date_for("Asia/Ho_Chi_Minh", datetime(2026, 5, 28, 16, 30, tzinfo=timezone.utc))
        assert d == date(2026, 5, 28)

    def test_saigon_after_midnight_local(self):
        """17:30 UTC = 00:30 Saigon → tomorrow."""
        d = local_date_for("Asia/Ho_Chi_Minh", datetime(2026, 5, 28, 17, 30, tzinfo=timezone.utc))
        assert d == date(2026, 5, 29)

    def test_osaka(self):
        """15:30 UTC = 00:30 Osaka → tomorrow."""
        d = local_date_for("Asia/Tokyo", datetime(2026, 5, 28, 15, 30, tzinfo=timezone.utc))
        assert d == date(2026, 5, 29)


class TestGetOrCreateRun:
    def test_creates_on_first_call(self, db, tactic_for, campaign_for, saigon_account):
        run, created = get_or_create_run(
            db,
            tactic_id=tactic_for.id, campaign=campaign_for,
            account_tz=saigon_account.timezone,
            account_currency=saigon_account.currency,
            origin_budget=300,
        )
        assert created is True
        assert float(run.origin_budget) == 300
        assert float(run.current_budget) == 300
        assert run.status == SURF_RUN_STATUS_ACTIVE
        assert run.last_threshold_hit is None

    def test_returns_existing_on_second_call(self, db, tactic_for, campaign_for, saigon_account):
        run1, c1 = get_or_create_run(
            db, tactic_id=tactic_for.id, campaign=campaign_for,
            account_tz=saigon_account.timezone, account_currency=saigon_account.currency,
            origin_budget=300,
        )
        run2, c2 = get_or_create_run(
            db, tactic_id=tactic_for.id, campaign=campaign_for,
            account_tz=saigon_account.timezone, account_currency=saigon_account.currency,
            origin_budget=999,  # this is ignored — run already snapshotted
        )
        assert c1 is True
        assert c2 is False
        assert run1.id == run2.id
        assert float(run2.origin_budget) == 300  # NOT 999


class TestCheckpoints:
    def test_append_and_read_latest(self, db, tactic_for, campaign_for, saigon_account):
        run, _ = get_or_create_run(
            db, tactic_id=tactic_for.id, campaign=campaign_for,
            account_tz=saigon_account.timezone, account_currency=saigon_account.currency,
            origin_budget=300,
        )
        # Insert 2 checkpoints, second is most recent.
        cp1 = append_checkpoint(
            db, run=run, checked_at=datetime(2026, 5, 28, 8, 0, tzinfo=timezone.utc),
            spend_at_check=80, roas_at_check=2.0, threshold_crossed=None,
            tier_label=NO_ACTION, multiplier_applied=None,
            budget_before=300, budget_after=300, capped_by=None,
            meta_api_called=False, meta_api_success=None, meta_api_error=None,
            raw_meta_response=None,
        )
        cp2 = append_checkpoint(
            db, run=run, checked_at=datetime(2026, 5, 28, 9, 0, tzinfo=timezone.utc),
            spend_at_check=150, roas_at_check=2.2, threshold_crossed=90.0,
            tier_label=TIER_2, multiplier_applied=1.50,
            budget_before=300, budget_after=450, capped_by=None,
            meta_api_called=True, meta_api_success=True, meta_api_error=None,
            raw_meta_response={"foo": 1},
        )
        latest = latest_checkpoint(db, run.id)
        assert latest is not None
        assert latest.id == cp2.id
        assert float(latest.roas_at_check) == 2.2


class TestWasNoopAtThreshold:
    def test_no_previous_checkpoint(self):
        assert was_noop_at_threshold(None, 90.0) is False

    def test_threshold_not_yet_acted(self):
        class FakeCP:
            threshold_crossed = None
        assert was_noop_at_threshold(FakeCP(), 90.0) is False

    def test_threshold_already_acted(self):
        class FakeCP:
            threshold_crossed = 90.0
        assert was_noop_at_threshold(FakeCP(), 90.0) is True

    def test_higher_threshold_acted_blocks_lower(self):
        class FakeCP:
            threshold_crossed = 150.0
        assert was_noop_at_threshold(FakeCP(), 90.0) is True


class TestUpdateRunAfterAction:
    def test_increments_total_and_advances_threshold(self, db, tactic_for, campaign_for, saigon_account):
        run, _ = get_or_create_run(
            db, tactic_id=tactic_for.id, campaign=campaign_for,
            account_tz=saigon_account.timezone, account_currency=saigon_account.currency,
            origin_budget=300,
        )
        update_run_after_action(
            db, run=run,
            new_current_budget=450, increase_amount=150,
            threshold_crossed=90.0, roas_at_check=2.2,
            capped_today=False,
        )
        assert float(run.current_budget) == 450
        assert float(run.total_increase_today) == 150
        assert float(run.last_threshold_hit) == 90.0
        assert float(run.last_roas_at_check) == 2.2
        assert run.status == SURF_RUN_STATUS_ACTIVE

    def test_capped_today_flips_status(self, db, tactic_for, campaign_for, saigon_account):
        run, _ = get_or_create_run(
            db, tactic_id=tactic_for.id, campaign=campaign_for,
            account_tz=saigon_account.timezone, account_currency=saigon_account.currency,
            origin_budget=300,
        )
        update_run_after_action(
            db, run=run, new_current_budget=600, increase_amount=300,
            threshold_crossed=210.0, roas_at_check=3.5,
            capped_today=True,
        )
        assert run.status == SURF_RUN_STATUS_CAPPED
