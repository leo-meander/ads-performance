"""Build + push design-brief tasks into the Lark Base "Tasks" table.

The Task name is composed on the client following the team's CSV naming rule
(`[Branch] Format_Country (Lang) - TA - Theme`) and arrives here already
finalised + editable. This layer maps the final values plus the always-on
fields (PIC, Status, Project) onto the Base's column names. Column names live
here so a rename in Lark is a one-line change.

Field-type caveat: PIC exports as a plain email in the CSV, so it's treated as
a text field. "Project" groups the board as "[<tag>] Ads" — if that turns out
to be a LINK field (to the Projects table) rather than a single-select, a
plain string write will fail and we must switch to a record-id link. Confirm
with LarkClient.list_table_fields() once app_token/table_id are set.
"""
from __future__ import annotations

from typing import Any, Optional

from app.config import settings
from app.services.lark_client import LarkClient, LarkClientError

# Column names as they appear on the live "Tasks" board.
FIELD_TASK = "Task"
FIELD_DESCRIPTION = "Description"
FIELD_STATUS = "Status"
FIELD_PIC = "PIC"
FIELD_PROJECT = "Project"

# Always-on defaults (overridable via settings).
DEFAULT_STATUS = "Not started"
DEFAULT_PIC = "nora@staymeander.com"

# Branch → the Projects-table label used for grouping ("[<tag>] Ads").
# NOTE: the Project tag for Saigon is "Sai Gon" (with a space) — taken from the
# live board — which differs from the Task-name tag "Saigon" (no space).
_PROJECT_TAGS: list[tuple[str, str]] = [
    ("1948", "1948"),
    ("oani", "Oani"),
    ("osaka", "Osaka"),
    ("saigon", "Sai Gon"),
    ("taipei", "Taipei"),
    ("bread", "Bread"),
]


def project_for_branch(branch_name: Optional[str]) -> Optional[str]:
    """Map a branch/account name to its "[<tag>] Ads" Project label."""
    if not branch_name:
        return None
    n = branch_name.lower()
    for needle, tag in _PROJECT_TAGS:
        if needle in n:
            return f"[{tag}] Ads"
    return None


def build_task_fields(
    *,
    task_name: str,
    description: str,
    branch_name: Optional[str] = None,
    status: Optional[str] = None,
    pic: Optional[str] = None,
) -> dict[str, Any]:
    """Map final values + always-on fields onto the Base columns."""
    name = (task_name or "").strip()
    if not name:
        raise LarkClientError("Task name is required")

    fields: dict[str, Any] = {
        FIELD_TASK: name,
        FIELD_DESCRIPTION: (description or "").strip(),
    }

    eff_status = (status or settings.LARK_TASKS_DEFAULT_STATUS or DEFAULT_STATUS).strip()
    if eff_status:
        fields[FIELD_STATUS] = eff_status

    eff_pic = (pic or settings.LARK_DEFAULT_PIC or DEFAULT_PIC).strip()
    if eff_pic:
        fields[FIELD_PIC] = eff_pic

    project = project_for_branch(branch_name)
    if project:
        fields[FIELD_PROJECT] = project

    return fields


def create_brief_task(
    *,
    task_name: str,
    description: str,
    branch_name: Optional[str] = None,
    status: Optional[str] = None,
    pic: Optional[str] = None,
    client: Optional[LarkClient] = None,
) -> dict[str, Any]:
    """Create one row in the Lark Base "Tasks" table from an AI brief."""
    c = client or LarkClient()
    fields = build_task_fields(
        task_name=task_name,
        description=description,
        branch_name=branch_name,
        status=status,
        pic=pic,
    )
    record = c.create_bitable_record(
        app_token=settings.LARK_BASE_APP_TOKEN,
        table_id=settings.LARK_TASKS_TABLE_ID,
        fields=fields,
    )
    return {
        "record_id": record.get("record_id"),
        "task_name": fields[FIELD_TASK],
        "fields": fields,
    }
