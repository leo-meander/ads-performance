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

from datetime import datetime, timezone
from typing import Any, Optional

from app.config import settings
from app.services.lark_client import LarkClient, LarkClientError

# Column names as they appear on the live "Tasks" board.
FIELD_TASK = "Task"
FIELD_DESCRIPTION = "Description"
FIELD_STATUS = "Status"
FIELD_PIC = "PIC"
FIELD_PROJECT = "Project"
FIELD_DEADLINE = "Deadline"


def _deadline_ms(deadline: Optional[str]) -> Optional[int]:
    """Parse a YYYY-MM-DD (or ISO) string into a Bitable date value.

    Bitable date fields take a millisecond epoch timestamp. We anchor a
    date-only value to 12:00 UTC so it can't slip to the previous/next day in
    the tenant's timezone. Returns None on empty/invalid input so a bad date
    never blocks the create.
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

# Always-on defaults (overridable via settings).
DEFAULT_STATUS = "Not started"

# PIC + Project are DuplexLink fields, so they're written as arrays of linked
# record ids — NOT plain text. These ids were introspected from the live Base
# (table "🚩 Projects" / "🧑🏻‍💻 Members"); re-introspect (LarkClient.list_table_fields
# + list records) if the board is rebuilt.
DEFAULT_PIC_RECORD_ID = "recv6JxUlC2N9p"  # nora@staymeander.com (Members table)

# branch-name substring → "[…] Ads" Project record id (order matters: "oani"
# before "taipei" so Oani's "(Taipei)" suffix can't mis-match).
_PROJECT_RECORD_IDS: list[tuple[str, str]] = [
    ("1948", "recv8gCr8yrhVb"),   # [1948] Ads
    ("oani", "recvfwkeNSVTRp"),   # [Oani] Ads
    ("osaka", "recv6sswLo9olH"),  # [Osaka] Ads
    ("saigon", "recv6sW5Nl2wBI"), # [Sai Gon]  Ads
    ("taipei", "recv8gCt0GGu9B"), # [Taipei] Ads
    ("bread", "recv6WJTeN5WHx"),  # [BE] Ads
]


def project_record_for_branch(branch_name: Optional[str]) -> Optional[str]:
    """Map a branch/account name to its "[<tag>] Ads" Project record id."""
    if not branch_name:
        return None
    n = branch_name.lower()
    for needle, rid in _PROJECT_RECORD_IDS:
        if needle in n:
            return rid
    return None


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

    PIC and Project are DuplexLink fields → written as arrays of record ids.
    Status is a single-select (string), Deadline a datetime (ms), Task and
    Description are text.
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

    pic_rid = (pic_record_id or settings.LARK_DEFAULT_PIC_RECORD_ID or DEFAULT_PIC_RECORD_ID).strip()
    if pic_rid:
        fields[FIELD_PIC] = [pic_rid]

    project_rid = project_record_for_branch(branch_name)
    if project_rid:
        fields[FIELD_PROJECT] = [project_rid]

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
