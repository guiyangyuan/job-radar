"""Pending recruitment-email events, matching, review, and confirmation."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from datetime import datetime
from urllib.parse import urlparse

from .applications import (
    ApplicationConflict,
    ApplicationNotFound,
    create_application,
    update_application,
)
from .email_classification import EmailCandidate
from .email_models import validate_email_event, validate_email_events
from .imap_sync import FetchIssue, FetchedMessage
from .merge import stable_job_id
from .models import (
    APPLICATION_STATUSES,
    SCHEMA_VERSION,
    normalize_text,
    validate_application,
    validate_job,
)
from .storage import Workspace, read_json, write_json_bundle_atomic


ACTIVE_STAGE_RANK = {
    "applied": 0,
    "screening": 1,
    "assessment": 2,
    "interview": 3,
    "offer": 4,
}
TERMINAL_STATUSES = {"rejected", "closed", "withdrawn", "archived"}
EDITABLE_EVENT_FIELDS = {
    "company",
    "title",
    "proposedStatus",
    "interviewStage",
    "nextAction",
    "nextActionAt",
    "matchedApplicationId",
}
CONFIRM_FIELDS = {
    "confirmed",
    "status",
    "applicationId",
    "updatedAt",
    "applicationUpdatedAt",
    "company",
    "title",
    "recruitmentType",
}


class EventNotFound(LookupError):
    """Raised when an email event ID does not exist."""


class EventConflict(RuntimeError):
    """Raised for stale or invalid email-event lifecycle transitions."""


def _timestamp(value: datetime | str) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value


def _message_key(
    mailbox_hash: str,
    uid_validity: int,
    uid: int,
    message_id: str | None,
) -> str:
    payload = f"{mailbox_hash}|{uid_validity}|{uid}|{message_id or ''}"
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _find_event(events: list[dict], event_id: str) -> tuple[int, dict]:
    matches = [
        (index, event)
        for index, event in enumerate(events)
        if event.get("id") == event_id
    ]
    if not matches:
        raise EventNotFound(f"email event not found: {event_id}")
    if len(matches) != 1:
        raise EventConflict("email event id is not unique")
    index, event = matches[0]
    return index, validate_email_event(event)


def _job_for_application(
    application: dict, jobs_by_id: dict[str, dict]
) -> dict | None:
    return jobs_by_id.get(application.get("jobId"))


def _domain_matches(sender: str, url: str | None) -> bool:
    if not sender or not url:
        return False
    host = (urlparse(url).hostname or "").lower()
    sender = sender.lower()
    return bool(
        host
        and (
            sender == host
            or sender.endswith("." + host)
            or host.endswith("." + sender)
        )
    )


def _match_application(
    message: FetchedMessage,
    candidate: EmailCandidate,
    jobs: list[dict],
    applications: list[dict],
) -> tuple[dict | None, str | None, bool]:
    jobs_by_id = {item["id"]: item for item in jobs if item.get("id")}
    identifier = normalize_text(candidate.employer_job_id or "")
    if identifier:
        matches = []
        for application in applications:
            linked = _job_for_application(application, jobs_by_id)
            if normalize_text(application.get("id", "")) == identifier or (
                linked
                and normalize_text(linked.get("employerJobId", "")) == identifier
            ):
                matches.append(application)
        if len(matches) == 1:
            return matches[0], "通过职位编号精确匹配到投递记录", False
        if len(matches) > 1:
            return None, "职位编号匹配到多条投递记录", True

    company = normalize_text(candidate.company or "")
    title = normalize_text(candidate.title or "")
    if company and title:
        matches = [
            application
            for application in applications
            if normalize_text(application.get("company", "")) == company
            and normalize_text(application.get("title", "")) == title
        ]
        if len(matches) == 1:
            return matches[0], "通过公司和岗位名称匹配到投递记录", False
        if len(matches) > 1:
            return None, "公司和岗位名称匹配到多条投递记录", True

    if company and message.sender_domain:
        matches = []
        for application in applications:
            if normalize_text(application.get("company", "")) != company:
                continue
            linked = _job_for_application(application, jobs_by_id)
            urls = (
                application.get("officialUrl"),
                application.get("applyUrl"),
                linked.get("officialUrl") if linked else None,
                linked.get("applyUrl") if linked else None,
            )
            if any(_domain_matches(message.sender_domain, url) for url in urls):
                matches.append(application)
        if len(matches) == 1:
            return matches[0], "通过已知公司和招聘域名匹配到投递记录", False
        if len(matches) > 1:
            return None, "招聘域名匹配到多条投递记录", True
    return None, None, False


def _is_older(left: str, right: str) -> bool:
    return datetime.fromisoformat(left.replace("Z", "+00:00")) < datetime.fromisoformat(
        right.replace("Z", "+00:00")
    )


def _status_conflicts(
    proposal: str | None,
    application: dict,
    received_at: str,
) -> str | None:
    if not proposal:
        return None
    current = application["status"]
    if current in TERMINAL_STATUSES:
        return "目标投递记录已处于终态"
    if (
        current in ACTIVE_STAGE_RANK
        and proposal in ACTIVE_STAGE_RANK
        and ACTIVE_STAGE_RANK[proposal] < ACTIVE_STAGE_RANK[current]
    ):
        return "邮件建议阶段早于当前正式阶段"
    if _is_older(received_at, application["updatedAt"]):
        return "邮件时间早于投递记录的最近更新时间"
    return None


def build_event(
    message: FetchedMessage,
    candidate: EmailCandidate,
    mailbox_hash: str,
    jobs: list[dict],
    applications: list[dict],
    now: datetime,
) -> dict:
    safe_jobs = [validate_job(item) for item in jobs]
    safe_applications = [validate_application(item) for item in applications]
    matched, match_reason, ambiguous = _match_application(
        message, candidate, safe_jobs, safe_applications
    )
    reasons = list(candidate.reasons)
    if match_reason:
        reasons.append(match_reason)
    classification = candidate.classification
    if ambiguous:
        classification = "conflict"
    if matched:
        conflict = _status_conflicts(
            candidate.proposed_status, matched, message.received_at
        )
        if conflict:
            classification = "conflict"
            reasons.append(conflict)
    key = _message_key(
        mailbox_hash,
        message.uid_validity,
        message.uid,
        message.message_id,
    )
    timestamp = now.isoformat()
    event = {
        "schemaVersion": SCHEMA_VERSION,
        "id": "evt_" + key.removeprefix("sha256:")[:24],
        "messageKeyHash": key,
        "receivedAt": message.received_at,
        "senderDomain": message.sender_domain,
        "subjectSummary": message.subject.strip()[:160] or None,
        "company": candidate.company,
        "title": candidate.title,
        "proposedStatus": candidate.proposed_status,
        "interviewStage": candidate.interview_stage,
        "nextAction": candidate.next_action,
        "nextActionAt": candidate.next_action_at,
        "classification": classification,
        "confidence": candidate.confidence,
        "reasons": reasons,
        "matchedApplicationId": matched["id"] if matched else None,
        "state": "pending",
        "createdAt": timestamp,
        "updatedAt": timestamp,
        "processedAt": None,
    }
    return validate_email_event(event)


def build_error_event(
    issue: FetchIssue,
    mailbox_hash: str,
    now: datetime,
) -> dict:
    key = _message_key(
        mailbox_hash, issue.uid_validity, issue.uid, issue.message_id
    )
    timestamp = now.isoformat()
    return validate_email_event(
        {
            "schemaVersion": SCHEMA_VERSION,
            "id": "evt_" + key.removeprefix("sha256:")[:24],
            "messageKeyHash": key,
            "receivedAt": issue.received_at or timestamp,
            "senderDomain": issue.sender_domain,
            "subjectSummary": issue.subject.strip()[:160] or None,
            "company": None,
            "title": None,
            "proposedStatus": None,
            "interviewStage": None,
            "nextAction": None,
            "nextActionAt": None,
            "classification": "incomplete",
            "confidence": 0.0,
            "reasons": [f"邮件解析失败：{issue.error_category}"],
            "matchedApplicationId": None,
            "state": "error",
            "createdAt": timestamp,
            "updatedAt": timestamp,
            "processedAt": timestamp,
        }
    )


def merge_events(
    existing: list[dict], incoming: list[dict]
) -> tuple[list[dict], dict]:
    result = validate_email_events(existing)
    by_key = {event["messageKeyHash"]: index for index, event in enumerate(result)}
    by_id = {event["id"]: index for index, event in enumerate(result)}
    stats = {"added": 0, "updated": 0, "unchanged": 0}
    for raw in incoming:
        event = validate_email_event(raw)
        if event["messageKeyHash"] in by_key:
            stats["unchanged"] += 1
            continue
        if event["id"] in by_id:
            index = by_id[event["id"]]
            old_key = result[index]["messageKeyHash"]
            result[index] = event
            del by_key[old_key]
            by_key[event["messageKeyHash"]] = index
            stats["updated"] += 1
            continue
        result.append(event)
        index = len(result) - 1
        by_key[event["messageKeyHash"]] = index
        by_id[event["id"]] = index
        stats["added"] += 1
    result.sort(key=lambda event: (event["createdAt"], event["id"]))
    return validate_email_events(result), stats


def patch_event(
    event: dict,
    updates: dict,
    now: datetime,
    expected_updated_at: str,
) -> dict:
    current = validate_email_event(event)
    if current["state"] != "pending":
        raise EventConflict("only pending email events can be edited")
    if expected_updated_at != current["updatedAt"]:
        raise EventConflict("stale email event version")
    if not isinstance(updates, dict):
        raise ValueError("email event updates must be an object")
    unknown = sorted(set(updates) - EDITABLE_EVENT_FIELDS)
    if unknown:
        raise ValueError(
            f"unsupported email event fields: {', '.join(unknown)}"
        )
    updated = deepcopy(current)
    changed = False
    for key, value in updates.items():
        if updated.get(key) != value:
            updated[key] = deepcopy(value)
            changed = True
    if changed:
        updated["updatedAt"] = now.isoformat()
    return validate_email_event(updated)


def set_event_ignored(
    event_id: str,
    ignored: bool,
    workspace: Workspace,
    now: datetime,
    *,
    expected_updated_at: str,
) -> dict:
    events = validate_email_events(read_json(workspace.email_events))
    index, event = _find_event(events, event_id)
    if expected_updated_at != event["updatedAt"]:
        raise EventConflict("stale email event version")
    if event["state"] == "confirmed":
        raise EventConflict("confirmed email events cannot be ignored or restored")
    if ignored and event["state"] not in {"pending", "error"}:
        raise EventConflict("email event is not available to ignore")
    if not ignored and event["state"] != "ignored":
        raise EventConflict("email event is not ignored")
    updated = deepcopy(event)
    updated["state"] = "ignored" if ignored else "pending"
    updated["updatedAt"] = now.isoformat()
    updated["processedAt"] = now.isoformat() if ignored else None
    events[index] = validate_email_event(updated)
    write_json_bundle_atomic({workspace.email_events: events}, workspace.backups)
    return events[index]


def _confirmed_event(
    event: dict,
    application_id: str,
    status: str,
    now: datetime,
) -> dict:
    updated = deepcopy(event)
    updated["matchedApplicationId"] = application_id
    updated["proposedStatus"] = status
    updated["state"] = "confirmed"
    updated["updatedAt"] = now.isoformat()
    updated["processedAt"] = now.isoformat()
    return validate_email_event(updated)


def _minimal_email_job(
    company: str,
    title: str,
    recruitment_type: str,
    now: datetime,
) -> dict:
    timestamp = now.isoformat()
    value = {
        "schemaVersion": SCHEMA_VERSION,
        "id": "",
        "employerJobId": None,
        "company": company,
        "title": title,
        "recruitmentType": recruitment_type,
        "cities": [],
        "experienceMin": None,
        "experienceMax": None,
        "education": None,
        "graduationWindow": None,
        "skills": [],
        "industry": None,
        "companyType": None,
        "descriptionSummary": "由用户确认的招聘邮件创建",
        "publishedAt": None,
        "deadlineAt": None,
        "officialUrl": None,
        "applyUrl": None,
        "sources": [],
        "sourceTier": 4,
        "sourceConfidence": "email_confirmed",
        "firstDiscoveredAt": timestamp,
        "lastVerifiedAt": timestamp,
        "verificationState": "email_confirmed",
        "poolStatus": "saved",
        "score": 0,
        "scoreBreakdown": {},
        "recommendationReasons": [],
        "gaps": [],
        "riskFlags": ["email_confirmed"],
    }
    value["id"] = stable_job_id(value)
    return validate_job(value)


def confirm_event(
    event_id: str,
    payload: dict,
    workspace: Workspace,
    now: datetime,
) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("confirmation payload must be an object")
    unknown = sorted(set(payload) - CONFIRM_FIELDS)
    if unknown:
        raise ValueError(f"unsupported confirmation fields: {', '.join(unknown)}")
    if payload.get("confirmed") is not True:
        raise ValueError("explicit confirmation is required")
    status = payload.get("status")
    if status not in APPLICATION_STATUSES:
        raise ValueError("a supported status is required")

    events = validate_email_events(read_json(workspace.email_events))
    jobs = [validate_job(item) for item in read_json(workspace.jobs)]
    applications = [
        validate_application(item) for item in read_json(workspace.applications)
    ]
    event_index, event = _find_event(events, event_id)
    if event["state"] != "pending":
        raise EventConflict("only pending email events can be confirmed")
    if payload.get("updatedAt") != event["updatedAt"]:
        raise EventConflict("stale email event version")

    application_id = payload.get("applicationId")
    if application_id:
        matches = [
            (index, item)
            for index, item in enumerate(applications)
            if item["id"] == application_id
        ]
        if not matches:
            raise ApplicationNotFound(f"application not found: {application_id}")
        if len(matches) != 1:
            raise ApplicationConflict("application id is not unique")
        application_index, current = matches[0]
        updates = {
            "status": status,
            "interviewStage": event.get("interviewStage"),
            "nextAction": event.get("nextAction"),
            "nextActionAt": event.get("nextActionAt"),
        }
        updated_application = update_application(
            current,
            updates,
            now,
            "email",
            expected_updated_at=payload.get("applicationUpdatedAt"),
        )
        applications[application_index] = updated_application
        updated_event = _confirmed_event(event, application_id, status, now)
        events[event_index] = updated_event
        write_json_bundle_atomic(
            {
                workspace.applications: applications,
                workspace.email_events: events,
            },
            workspace.backups,
        )
        return {"event": updated_event, "application": updated_application}

    company = str(payload.get("company") or "").strip()
    title = str(payload.get("title") or "").strip()
    recruitment_type = str(payload.get("recruitmentType") or "").strip()
    if not company or not title or not recruitment_type:
        raise ValueError(
            "company, title, and recruitmentType are required for a new application"
        )
    new_job = _minimal_email_job(company, title, recruitment_type, now)
    if any(item["id"] == new_job["id"] for item in jobs):
        raise EventConflict("a matching job already exists; choose its application")
    created_application, applied_job = create_application(
        new_job, now, confirmed=True, channel="email"
    )
    updates = {
        "status": status,
        "interviewStage": event.get("interviewStage"),
        "nextAction": event.get("nextAction"),
        "nextActionAt": event.get("nextActionAt"),
    }
    created_application = update_application(
        created_application,
        updates,
        now,
        "email",
        expected_updated_at=created_application["updatedAt"],
    )
    jobs.append(applied_job)
    applications.append(created_application)
    updated_event = _confirmed_event(event, created_application["id"], status, now)
    events[event_index] = updated_event
    write_json_bundle_atomic(
        {
            workspace.jobs: jobs,
            workspace.applications: applications,
            workspace.email_events: events,
        },
        workspace.backups,
    )
    return {
        "event": updated_event,
        "application": created_application,
        "job": applied_job,
    }
