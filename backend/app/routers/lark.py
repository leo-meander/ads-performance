"""Lark (Feishu) integration endpoints."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.permissions import scoped_account_ids
from app.database import get_db
from app.dependencies.auth import require_section
from app.models.user import User
from app.services.lark_client import LarkClientError
from app.services.lark_service import create_brief_task

router = APIRouter()


def _api_response(data=None, error=None):
    return {
        "success": error is None,
        "data": data,
        "error": error,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


class LarkTaskCreate(BaseModel):
    branch_id: str
    task_name: str
    description: str = ""
    status: str | None = None


@router.post("/lark/tasks")
def create_lark_task(
    body: LarkTaskCreate,
    current_user: User = Depends(require_section("meta_ads")),
    db: Session = Depends(get_db),
):
    """Create a design-brief task in the Lark Base "Tasks" table from an AI brief.

    The task name + description are composed (and editable) on the client; this
    endpoint scopes the branch, then writes the row. Returns the new record id.
    """
    try:
        ok, _ids, err = scoped_account_ids(
            db, current_user, "meta_ads", requested_account_id=body.branch_id
        )
        if not ok:
            return _api_response(error=err)

        result = create_brief_task(
            task_name=body.task_name,
            description=body.description,
            status=body.status,
        )
        return _api_response(data=result)
    except LarkClientError as e:
        return _api_response(error=str(e))
    except Exception as e:
        return _api_response(error=str(e))
