"""Strict, privacy-preserving schemas for recruitment email synchronization."""

from __future__ import annotations

import re
from copy import deepcopy
from numbers import Real

from .models import (
    APPLICATION_STATUSES,
    SCHEMA_VERSION,
    ValidationError,
    _reject_unknown,
    _require_text,
    _validate_iso,
)


EMAIL_CLASSIFICATIONS = {"actionable", "incomplete", "conflict", "irrelevant"}
EMAIL_EVENT_STATES = {"pending", "confirmed", "ignored", "error"}
EMAIL_SYNC_KEYS = {
    "schemaVersion",
    "provider",
    "mailboxHash",
    "folder",
    "initialWindowDays",
    "uidValidity",
    "lastSeenUid",
    "lastSyncedAt",
}
EMAIL_EVENT_KEYS = {
    "schemaVersion",
    "id",
    "messageKeyHash",
    "receivedAt",
    "senderDomain",
    "subjectSummary",
    "company",
    "title",
    "proposedStatus",
    "interviewStage",
    "nextAction",
    "nextActionAt",
    "classification",
    "confidence",
    "reasons",
    "matchedApplicationId",
    "state",
    "createdAt",
    "updatedAt",
    "processedAt",
}
HASH_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")

DEFAULT_EMAIL_SYNC_STATE = {
    "schemaVersion": SCHEMA_VERSION,
    "provider": None,
    "mailboxHash": None,
    "folder": "INBOX",
    "initialWindowDays": 60,
    "uidValidity": None,
    "lastSeenUid": None,
    "lastSyncedAt": None,
}


def _validate_hash(value: str | None, key: str) -> None:
    if value is not None and not (
        isinstance(value, str) and HASH_PATTERN.fullmatch(value)
    ):
        raise ValidationError(f"{key} must be a sha256 hash")


def _validate_optional_text(value: object, key: str) -> None:
    if value is not None and (not isinstance(value, str) or not value.strip()):
        raise ValidationError(f"{key} must be non-empty text or null")


def _validate_optional_uid(value: object, key: str) -> None:
    if value is not None and (
        isinstance(value, bool) or not isinstance(value, int) or value < 0
    ):
        raise ValidationError(f"{key} must be a non-negative integer or null")


def validate_email_sync_state(value: dict) -> dict:
    if not isinstance(value, dict):
        raise ValidationError("email sync state must be an object")
    result = deepcopy(value)
    _reject_unknown(result, EMAIL_SYNC_KEYS, "email sync")
    if result.get("schemaVersion") != SCHEMA_VERSION:
        raise ValidationError("unsupported schemaVersion")
    _validate_optional_text(result.get("provider"), "provider")
    _validate_hash(result.get("mailboxHash"), "mailboxHash")
    _require_text(result, "folder")
    window = result.get("initialWindowDays")
    if isinstance(window, bool) or not isinstance(window, int) or window <= 0:
        raise ValidationError("initialWindowDays must be a positive integer")
    _validate_optional_uid(result.get("uidValidity"), "uidValidity")
    _validate_optional_uid(result.get("lastSeenUid"), "lastSeenUid")
    _validate_iso(result.get("lastSyncedAt"), "lastSyncedAt")
    return result


def validate_email_event(value: dict) -> dict:
    if not isinstance(value, dict):
        raise ValidationError("email event must be an object")
    result = deepcopy(value)
    _reject_unknown(result, EMAIL_EVENT_KEYS, "email event")
    if result.get("schemaVersion") != SCHEMA_VERSION:
        raise ValidationError("unsupported schemaVersion")
    for key in ("id", "messageKeyHash", "receivedAt", "classification", "state"):
        _require_text(result, key)
    _validate_hash(result.get("messageKeyHash"), "messageKeyHash")
    for key in ("receivedAt", "nextActionAt", "createdAt", "updatedAt", "processedAt"):
        _validate_iso(result.get(key), key)
    for key in (
        "senderDomain",
        "subjectSummary",
        "company",
        "title",
        "interviewStage",
        "nextAction",
        "matchedApplicationId",
    ):
        _validate_optional_text(result.get(key), key)
    status = result.get("proposedStatus")
    if status is not None and status not in APPLICATION_STATUSES:
        raise ValidationError("proposedStatus is unsupported")
    if result.get("classification") not in EMAIL_CLASSIFICATIONS:
        raise ValidationError("classification is unsupported")
    if result.get("state") not in EMAIL_EVENT_STATES:
        raise ValidationError("state is unsupported")
    confidence = result.get("confidence")
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, Real)
        or not 0 <= confidence <= 1
    ):
        raise ValidationError("confidence must be numeric from 0 to 1")
    reasons = result.get("reasons")
    if not isinstance(reasons, list) or any(
        not isinstance(reason, str) or not reason.strip() for reason in reasons
    ):
        raise ValidationError("reasons must be a list of non-empty strings")
    return result


def validate_email_events(value: list[dict]) -> list[dict]:
    if not isinstance(value, list):
        raise ValidationError("email events must be a list")
    result = [validate_email_event(event) for event in value]
    ids = [event["id"] for event in result]
    if len(ids) != len(set(ids)):
        raise ValidationError("duplicate email event ids")
    keys = [event["messageKeyHash"] for event in result]
    if len(keys) != len(set(keys)):
        raise ValidationError("duplicate email message keys")
    return result
