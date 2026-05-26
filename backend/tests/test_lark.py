"""Tests for the Lark (Feishu) Bitable task integration."""
import pytest

from app.config import settings
from app.services import lark_service
from app.services.lark_client import LarkClient, LarkClientError


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
    assert fields["Status"] == "Not started"        # always-on default
    assert fields["PIC"] == "nora@staymeander.com"  # always-on default
    assert "Project" not in fields                  # no branch → no project


def test_build_task_fields_requires_name():
    with pytest.raises(LarkClientError):
        lark_service.build_task_fields(task_name="   ", description="x")


def test_build_task_fields_project_from_branch():
    f1 = lark_service.build_task_fields(task_name="T", description="d", branch_name="Meander Saigon")
    assert f1["Project"] == "[Sai Gon] Ads"   # note the space — matches the live board
    f2 = lark_service.build_task_fields(task_name="T", description="d", branch_name="Meander 1948")
    assert f2["Project"] == "[1948] Ads"
    f3 = lark_service.build_task_fields(task_name="T", description="d", branch_name="Oani (Taipei)")
    assert f3["Project"] == "[Oani] Ads"


def test_project_for_branch_unknown_returns_none():
    assert lark_service.project_for_branch("Some Random Brand") is None
    assert lark_service.project_for_branch(None) is None


def test_explicit_status_overrides_default(monkeypatch):
    monkeypatch.setattr(settings, "LARK_TASKS_DEFAULT_STATUS", "")
    fields = lark_service.build_task_fields(task_name="T", description="d", status="Review")
    assert fields["Status"] == "Review"
    assert fields["PIC"] == "nora@staymeander.com"  # untouched default


def test_settings_override_pic(monkeypatch):
    monkeypatch.setattr(settings, "LARK_DEFAULT_PIC", "someone@staymeander.com")
    fields = lark_service.build_task_fields(task_name="T", description="d")
    assert fields["PIC"] == "someone@staymeander.com"


def test_create_brief_task_uses_client(monkeypatch):
    monkeypatch.setattr(settings, "LARK_BASE_APP_TOKEN", "basAPP")
    monkeypatch.setattr(settings, "LARK_TASKS_TABLE_ID", "tblTASKS")
    fake = FakeLarkClient()

    result = lark_service.create_brief_task(
        task_name="[Osaka] Image_AU - Couple - Romantic theme",
        description="full brief",
        branch_name="Meander Osaka",
        client=fake,
    )

    assert result["record_id"] == "recFAKE123"
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["app_token"] == "basAPP"
    assert call["table_id"] == "tblTASKS"
    assert call["fields"]["Task"] == "[Osaka] Image_AU - Couple - Romantic theme"
    assert call["fields"]["Description"] == "full brief"
    assert call["fields"]["Project"] == "[Osaka] Ads"
    assert call["fields"]["Status"] == "Not started"
    assert call["fields"]["PIC"] == "nora@staymeander.com"


def test_client_token_requires_credentials():
    c = LarkClient(app_id="", app_secret="")
    with pytest.raises(LarkClientError):
        c._tenant_token()


def test_client_create_record_requires_target():
    # Missing app_token/table_id should fail fast, before any network call.
    c = LarkClient(app_id="cli_x", app_secret="secret")
    with pytest.raises(LarkClientError):
        c.create_bitable_record(app_token="", table_id="", fields={"Task": "x"})


def test_client_list_fields_requires_target():
    c = LarkClient(app_id="cli_x", app_secret="secret")
    with pytest.raises(LarkClientError):
        c.list_table_fields(app_token="", table_id="")
