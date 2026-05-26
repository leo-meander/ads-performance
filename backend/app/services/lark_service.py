"""Build + push design-brief tasks into the Lark Base "Tasks" table.

The Task name is composed on the client following the team's CSV naming rule
(`[Branch] Format_Country (Lang) - TA - Theme`) and arrives here already
finalised + editable, so this layer only maps the final values onto the Base's
column names and creates the record. Keeping the column names in one place
means a rename in Lark is a one-line change here.
"""
from __future__ import annotations

from typing import Any, Optional

from app.config import settings
from app.services.lark_client import LarkClient, LarkClientError

# Column names as they appear in the exported "Tasks" table CSV header.
FIELD_TASK = "Task"
FIELD_DESCRIPTION = "Description"
FIELD_STATUS = "Status"


def build_task_fields(
    *,
    task_name: str,
    description: str,
    status: Optional[str] = None,
) -> dict[str, Any]:
    """Map final task name + description (+ optional status) onto Base columns."""
    name = (task_name or "").strip()
    if not name:
        raise LarkClientError("Task name is required")

    fields: dict[str, Any] = {
        FIELD_TASK: name,
        FIELD_DESCRIPTION: (description or "").strip(),
    }
    eff_status = (status or settings.LARK_TASKS_DEFAULT_STATUS or "").strip()
    if eff_status:
        fields[FIELD_STATUS] = eff_status
    return fields


def create_brief_task(
    *,
    task_name: str,
    description: str,
    status: Optional[str] = None,
    client: Optional[LarkClient] = None,
) -> dict[str, Any]:
    """Create one row in the Lark Base "Tasks" table from an AI brief."""
    c = client or LarkClient()
    fields = build_task_fields(task_name=task_name, description=description, status=status)
    record = c.create_bitable_record(
        app_token=settings.LARK_BASE_APP_TOKEN,
        table_id=settings.LARK_TASKS_TABLE_ID,
        fields=fields,
    )
    return {
        "record_id": record.get("record_id"),
        "task_name": fields[FIELD_TASK],
    }
