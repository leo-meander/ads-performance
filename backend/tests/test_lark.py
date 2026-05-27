"""Tests for the Lark (Feishu) Bitable task integration."""
from datetime import datetime, timezone

import pytest

from app.config import settings
from app.services import lark_service
from app.services.lark_client import LarkClient, LarkClientError

NORA = "recv6JxUlC2N9p"  # PIC default — nora's Members record


class FakeLarkClient:
    """Captures create_bitable_record calls instead of hitting the network."""

    def __init__(self):
        self.calls = []

    def create_bitable_record(self, *, app_token, table_id, fields):
        self.calls.append({"app_token": app_token, "table_id": table_id, "fields": fields})
        return {"record_id": "recFAKE123", "fields": fields}


def test_build_task_fields_core_defaults():
    fields = lark_service.build_task_fields(
        task_name="  [1948] Image_VN - Solo - Direct Call-Out  ",
        description="Hook: x\n\nCTA: Book Now",
    )
    assert fields["Task"] == "[1948] Image_VN - Solo - Direct Call-Out"  # trimmed
    assert fields["Description"] == "Hook: x\n\nCTA: Book Now"
    assert fields["Status"] == "Not started"   # always-on default
    assert fields["PIC"] == [NORA]             # link field → array of record_ids
    assert "Project" not in fields             # no branch → no project


def test_build_task_fields_requires_name():
    with pytest.raises(LarkClientError):
        lark_service.build_task_fields(task_name="   ", description="x")


def test_project_record_for_branch():
    assert lark_service.project_record_for_branch("Meander Saigon") == "recv6sW5Nl2wBI"
    assert lark_service.project_record_for_branch("Meander 1948") == "recv8gCr8yrhVb"
    assert lark_service.project_record_for_branch("Oani (Taipei)") == "recvfwkeNSVTRp"
    assert lark_service.project_record_for_branch("Meander Osaka") == "recv6sswLo9olH"
    assert lark_service.project_record_for_branch("Some Random Brand") is None
    assert lark_service.project_record_for_branch(None) is None


def test_build_task_fields_project_link_array():
    fields = lark_service.build_task_fields(
        task_name="T", description="d", branch_name="Meander Saigon"
    )
    assert fields["Project"] == ["recv6sW5Nl2wBI"]  # link → array of record_ids


def test_build_task_fields_deadline_ms():
    fields = lark_service.build_task_fields(task_name="T", description="d", deadline="2026-06-30")
    expected = int(datetime(2026, 6, 30, 12, tzinfo=timezone.utc).timestamp() * 1000)
    assert fields["Deadline"] == expected


def test_build_task_fields_no_deadline_omitted():
    fields = lark_service.build_task_fields(task_name="T", description="d")
    assert "Deadline" not in fields


def test_build_task_fields_bad_deadline_omitted():
    fields = lark_service.build_task_fields(task_name="T", description="d", deadline="not-a-date")
    assert "Deadline" not in fields


def test_explicit_status_overrides_default(monkeypatch):
    monkeypatch.setattr(settings, "LARK_TASKS_DEFAULT_STATUS", "")
    fields = lark_service.build_task_fields(task_name="T", description="d", status="Review")
    assert fields["Status"] == "Review"
    assert fields["PIC"] == [NORA]  # untouched default


def test_settings_override_pic(monkeypatch):
    monkeypatch.setattr(settings, "LARK_DEFAULT_PIC_RECORD_ID", "recCUSTOM")
    fields = lark_service.build_task_fields(task_name="T", description="d")
    assert fields["PIC"] == ["recCUSTOM"]


def test_create_brief_task_uses_client(monkeypatch):
    monkeypatch.setattr(settings, "LARK_BASE_APP_TOKEN", "basAPP")
    monkeypatch.setattr(settings, "LARK_TASKS_TABLE_ID", "tblTASKS")
    fake = FakeLarkClient()

    result = lark_service.create_brief_task(
        task_name="[Osaka] Image_AU - Couple - Romantic theme",
        description="full brief",
        branch_name="Meander Osaka",
        deadline="2026-06-15",
        client=fake,
    )

    assert result["record_id"] == "recFAKE123"
    assert len(fake.calls) == 1
    f = fake.calls[0]["fields"]
    assert fake.calls[0]["app_token"] == "basAPP"
    assert fake.calls[0]["table_id"] == "tblTASKS"
    assert f["Task"] == "[Osaka] Image_AU - Couple - Romantic theme"
    assert f["Description"] == "full brief"
    assert f["Project"] == ["recv6sswLo9olH"]  # [Osaka] Ads
    assert f["PIC"] == [NORA]
    assert f["Status"] == "Not started"
    assert "Deadline" in f


def test_client_token_requires_credentials():
    c = LarkClient(app_id="", app_secret="")
    with pytest.raises(LarkClientError):
        c._tenant_token()


def test_client_create_record_requires_target():
    c = LarkClient(app_id="cli_x", app_secret="secret")
    with pytest.raises(LarkClientError):
        c.create_bitable_record(app_token="", table_id="", fields={"Task": "x"})


def test_client_list_fields_requires_target():
    c = LarkClient(app_id="cli_x", app_secret="secret")
    with pytest.raises(LarkClientError):
        c.list_table_fields(app_token="", table_id="")
