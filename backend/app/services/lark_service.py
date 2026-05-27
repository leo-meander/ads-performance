"""Build + push design-brief tasks into the Lark Base "Tasks" table.

Field types confirmed by introspecting the live board
(LarkClient.list_table_fields):
  Task / Description  → text            (string)
  Status              → single-select   (option name string; "Not started" ok)
  Deadline            → date            (epoch milliseconds)
  Project / PIC       → two-way LINK    → an array of linked record_ids
                        (a plain string write rejects the WHOLE record)

Project links to a row in the "Projects" table and PIC to a row in "Members".
Those record_ids are stable, so they're mapped directly below — re-run the
introspection (list_table_fields + record dumps) if the board is rebuilt.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from app.config import settings
from app.services.lark_client import LarkClient, LarkClientError

# Column names on the live "Tasks" board.
FIELD_TASK = "Task"
FIELD_DESCRIPTION = "Description"
FIELD_STATUS = "Status"
FIELD_PIC = "PIC"
FIELD_PROJECT = "Project"
FIELD_DEADLINE = "Deadline"

DEFAULT_STATUS = "Not started"
# nora@staymeander.com in the Members table — the standing design PIC.
DEFAULT_PIC_RECORD_ID = "recv6JxUlC2N9p"

# Branch → record_id of its "[<branch>] Ads" row in the Projects table.
# Linked by id (not name) because the board's labels are inconsistently spaced
# (e.g. "[Sai Gon]  Ads" with two spaces). Bread maps to the "[BE] Ads" row.
PROJECT_RECORD_IDS: dict[str, str] = {
    "1948": "recv8gCr8yrhVb",
    "oani": "recvfwkeNSVTRp",
    "osaka": "recv6sswLo9olH",
    "saigon": "recv6sW5Nl2wBI",
    "taipei": "recv8gCt0GGu9B",
    "bread": "recv6WJTeN5WHx",
}


def project_record_for_branch(branch_name: Optional[str]) -> Optional[str]:
    """Map a branch/account name to its Projects-table record_id."""
    if not branch_name:
        return None
    n = branch_name.lower()
    for needle, rid in PROJECT_RECORD_IDS.items():
        if needle in n:
            return rid
    return None


def _deadline_ms(deadline: Optional[str]) -> Optional[int]:
    """Parse a YYYY-MM-DD (or ISO) string into a Bitable date value.

    Bitable date fields take a millisecond epoch timestamp. We anchor a
    date-only value to 12:00 UTC so it can't slip a day in the tenant timezone.
    Returns None on empty/invalid input so a bad date never blocks the create.
    """
    if not deadline or not deadline.strip():
        return None
    s = deadline.strip()
    try:
        if len(s) == 10:  # YYYY-MM-DD from a date input
            dt = datetime.strptime(s, "%Y-%m-%d").replace(hour=12, tzinfo=timezone.utc)
        else:
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None
    return int(dt.timestamp() * 1000)


def build_task_fields(
    *,
    task_name: str,
    description: str,
    branch_name: Optional[str] = None,
    status: Optional[str] = None,
    pic_record_id: Optional[str] = None,
    deadline: Optional[str] = None,
) -> dict[str, Any]:
    """Map final values + always-on fields onto the Base columns.

    Link fields (Project, PIC) are written as arrays of record_ids.
    """
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

    pic_id = (pic_record_id or settings.LARK_DEFAULT_PIC_RECORD_ID or DEFAULT_PIC_RECORD_ID).strip()
    if pic_id:
        fields[FIELD_PIC] = [pic_id]  # link field → array of record_ids

    project_id = project_record_for_branch(branch_name)
    if project_id:
        fields[FIELD_PROJECT] = [project_id]  # link field → array of record_ids

    ms = _deadline_ms(deadline)
    if ms is not None:
        fields[FIELD_DEADLINE] = ms

    return fields


def create_brief_task(
    *,
    task_name: str,
    description: str,
    branch_name: Optional[str] = None,
    status: Optional[str] = None,
    pic_record_id: Optional[str] = None,
    deadline: Optional[str] = None,
    client: Optional[LarkClient] = None,
) -> dict[str, Any]:
    """Create one row in the Lark Base "Tasks" table from an AI brief."""
    c = client or LarkClient()
    fields = build_task_fields(
        task_name=task_name,
        description=description,
        branch_name=branch_name,
        status=status,
        pic_record_id=pic_record_id,
        deadline=deadline,
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
