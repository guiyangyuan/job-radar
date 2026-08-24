"""Application creation, optimistic updates, archival, and audit history."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from uuid import uuid4

from .models import SCHEMA_VERSION, validate_application, validate_job


UPDATE_FIELDS = {
    "status",
    "interviewStage",
    "nextAction",
    "nextActionAt",
    "notes",
    "evidenceLinks",
}
UPDATE_CHANNELS = {"conversation", "dashboard", "email", "screenshot", "portal"}


class ApplicationNotFound(LookupError):
    """Raised when an application ID does not exist in the canonical store."""


class ApplicationConflict(RuntimeError):
    """Raised when an optimistic update targets an older record version."""


def _timestamp(value: datetime | str) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value


def _validate_channel(channel: str) -> None:
    if channel not in UPDATE_CHANNELS:
        raise ValueError(f"unsupported update channel: {channel}")


def find_application(applications: list[dict], application_id: str) -> dict:
    for application in applications:
        if application.get("id") == application_id:
            return validate_application(application)
    raise ApplicationNotFound(f"application not found: {application_id}")


def create_application(
    job: dict,
    now: datetime | str,
    *,
    confirmed: bool,
    channel: str = "conversation",
) -> tuple[dict, dict]:
    """Create an application only after the user explicitly confirms submission."""

    if not confirmed:
        raise ValueError("explicit confirmation is required before recording an application")
    _validate_channel(channel)
    source_job = validate_job(job)
    if not str(source_job.get("id", "")).strip():
        raise ValueError("job id is required before recording an application")
    timestamp = _timestamp(now)
    created = {
        "schemaVersion": SCHEMA_VERSION,
        "id": str(uuid4()),
        "jobId": source_job["id"],
        "company": source_job["company"],
        "title": source_job["title"],
        "officialUrl": source_job.get("officialUrl"),
        "applyUrl": source_job.get("applyUrl"),
        "recruitmentType": source_job["recruitmentType"],
        "cities": deepcopy(source_job.get("cities", [])),
        "appliedAt": timestamp,
        "status": "applied",
        "interviewStage": None,
        "nextAction": None,
        "nextActionAt": None,
        "notes": "",
        "evidenceLinks": [],
        "updatedAt": timestamp,
        "history": [
            {
                "timestamp": timestamp,
                "channel": channel,
                "changes": {"status": {"old": None, "new": "applied"}},
            }
        ],
    }
    updated_job = deepcopy(source_job)
    updated_job["poolStatus"] = "applied"
    return validate_application(created), validate_job(updated_job)


def update_application(
    application: dict,
    updates: dict,
    now: datetime | str,
    channel: str,
    *,
    expected_updated_at: str | None = None,
) -> dict:
    """Apply an optimistic, auditable patch to mutable application fields."""

    current = validate_application(application)
    _validate_channel(channel)
    if not isinstance(updates, dict):
        raise ValueError("updates must be an object")
    unknown = sorted(set(updates) - UPDATE_FIELDS)
    if unknown:
        raise ValueError(f"unsupported update fields: {', '.join(unknown)}")
    if expected_updated_at is not None and expected_updated_at != current["updatedAt"]:
        raise ApplicationConflict(
            f"stale application version: expected {expected_updated_at}, "
            f"found {current['updatedAt']}"
        )

    changes = {
        key: {"old": deepcopy(current.get(key)), "new": deepcopy(value)}
        for key, value in updates.items()
        if current.get(key) != value
    }
    if not changes:
        return current

    timestamp = _timestamp(now)
    updated = deepcopy(current)
    for key, change in changes.items():
        updated[key] = change["new"]
    updated["updatedAt"] = timestamp
    updated["history"].append(
        {"timestamp": timestamp, "channel": channel, "changes": changes}
    )
    return validate_application(updated)


def archive_application(
    application: dict,
    now: datetime | str,
    channel: str,
    *,
    expected_updated_at: str | None = None,
) -> dict:
    """Archive an application while retaining the record and its history."""

    return update_application(
        application,
        {"status": "archived"},
        now,
        channel,
        expected_updated_at=expected_updated_at,
    )
