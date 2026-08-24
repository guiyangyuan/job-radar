"""Schema validation and canonical text normalization."""

from __future__ import annotations

import re
import unicodedata
from copy import deepcopy
from datetime import date, datetime
from numbers import Real
from urllib.parse import urlparse


SCHEMA_VERSION = 1
RECRUITMENT_TYPES = {"campus", "experienced", "internship"}
LINK_TYPES = {"detail", "apply", "listing", "homepage"}
POLICY_VERIFICATION_STATES = {"verified", "unknown", "needs_verification"}
POOL_STATUSES = {
    "discovered",
    "saved",
    "preparing",
    "applied",
    "ignored",
    "expired",
    "archived",
}
APPLICATION_STATUSES = {
    "applied",
    "screening",
    "assessment",
    "interview",
    "offer",
    "rejected",
    "withdrawn",
    "closed",
    "archived",
}
WEIGHT_KEYS = {
    "role",
    "skills",
    "eligibility",
    "location",
    "preference",
    "freshness",
}
PROFILE_KEYS = {
    "schemaVersion",
    "targetRoles",
    "roleAliases",
    "recruitmentTypes",
    "cities",
    "remotePreference",
    "yearsOfExperience",
    "graduationDate",
    "education",
    "skills",
    "preferredIndustries",
    "preferredCompanyTypes",
    "excludedCompanies",
    "excludedKeywords",
    "excludedCities",
    "strictCityFilter",
    "scoreWeights",
    "confirmed",
}
COMPANY_POLICY_KEYS = {
    "schemaVersion",
    "company",
    "recruitmentType",
    "maxApplications",
    "canChangeSubmittedRole",
    "ruleSummary",
    "officialUrl",
    "lastVerifiedAt",
    "verificationState",
}
JOB_KEYS = {
    "schemaVersion",
    "id",
    "employerJobId",
    "company",
    "title",
    "recruitmentType",
    "cities",
    "experienceMin",
    "experienceMax",
    "education",
    "graduationWindow",
    "skills",
    "industry",
    "companyType",
    "descriptionSummary",
    "publishedAt",
    "deadlineAt",
    "officialUrl",
    "applyUrl",
    "linkType",
    "linkUrl",
    "linkSearchHint",
    "sources",
    "sourceTier",
    "sourceConfidence",
    "firstDiscoveredAt",
    "lastVerifiedAt",
    "verificationState",
    "poolStatus",
    "score",
    "scoreBreakdown",
    "recommendationReasons",
    "gaps",
    "riskFlags",
}
APPLICATION_KEYS = {
    "schemaVersion",
    "id",
    "jobId",
    "company",
    "title",
    "officialUrl",
    "applyUrl",
    "recruitmentType",
    "cities",
    "appliedAt",
    "status",
    "interviewStage",
    "nextAction",
    "nextActionAt",
    "notes",
    "evidenceLinks",
    "updatedAt",
    "history",
}
SOURCE_KEYS = {"name", "url", "tier"}
HISTORY_EVENT_KEYS = {"timestamp", "channel", "changes"}
CHANGE_KEYS = {"old", "new"}
APPLICATION_MUTABLE_KEYS = {
    "status",
    "interviewStage",
    "nextAction",
    "nextActionAt",
    "notes",
    "evidenceLinks",
}
UPDATE_CHANNELS = {"conversation", "dashboard", "email", "screenshot", "portal"}


class ValidationError(ValueError):
    """Raised when a Job Radar record violates its public schema."""


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(value)).strip().lower()
    return re.sub(r"\s+", " ", normalized)


def _reject_unknown(value: dict, allowed: set[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValidationError(f"unknown {label} fields: {', '.join(unknown)}")


def _require_text(value: dict, key: str) -> str:
    text = str(value.get(key, "")).strip()
    if not text:
        raise ValidationError(f"{key} is required")
    return text


def _validate_iso(value: str | None, key: str) -> None:
    if value is None:
        return
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValidationError(f"{key} must be ISO-8601") from exc


def _validate_date(value: str | None, key: str) -> None:
    if value is None:
        return
    try:
        date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{key} must be an ISO date") from exc


def _validate_url(value: str | None, key: str) -> None:
    if value is None:
        return
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValidationError(f"{key} must be an HTTP(S) URL")


def _validate_list(value: dict, key: str) -> None:
    if not isinstance(value.get(key, []), list):
        raise ValidationError(f"{key} must be a list")


def _validate_optional_number(value: dict, key: str) -> None:
    number = value.get(key)
    if number is not None and (isinstance(number, bool) or not isinstance(number, Real)):
        raise ValidationError(f"{key} must be numeric or null")


def validate_profile(value: dict) -> dict:
    if not isinstance(value, dict):
        raise ValidationError("profile must be an object")
    result = deepcopy(value)
    _reject_unknown(result, PROFILE_KEYS, "profile")
    if result.get("schemaVersion") != SCHEMA_VERSION:
        raise ValidationError("unsupported schemaVersion")
    if not isinstance(result.get("targetRoles"), list) or not result["targetRoles"]:
        raise ValidationError("targetRoles is required")
    for key in (
        "roleAliases",
        "recruitmentTypes",
        "cities",
        "skills",
        "preferredIndustries",
        "preferredCompanyTypes",
        "excludedCompanies",
        "excludedKeywords",
        "excludedCities",
    ):
        _validate_list(result, key)
    types = set(result.get("recruitmentTypes", []))
    if not types or not types <= RECRUITMENT_TYPES:
        raise ValidationError("recruitmentTypes contains an unsupported value")
    _validate_optional_number(result, "yearsOfExperience")
    _validate_date(result.get("graduationDate"), "graduationDate")
    if not isinstance(result.get("strictCityFilter", False), bool):
        raise ValidationError("strictCityFilter must be boolean")
    if not isinstance(result.get("confirmed", False), bool):
        raise ValidationError("confirmed must be boolean")
    weights = result.get("scoreWeights", {})
    if not isinstance(weights, dict) or set(weights) != WEIGHT_KEYS:
        raise ValidationError("scoreWeights must contain all dimensions and sum to 100")
    if any(isinstance(weight, bool) or not isinstance(weight, Real) for weight in weights.values()):
        raise ValidationError("scoreWeights must be numeric")
    if sum(weights.values()) != 100:
        raise ValidationError("scoreWeights must contain all dimensions and sum to 100")
    return result


def validate_job(value: dict) -> dict:
    if not isinstance(value, dict):
        raise ValidationError("job must be an object")
    result = deepcopy(value)
    _reject_unknown(result, JOB_KEYS, "job")
    if result.get("schemaVersion") != SCHEMA_VERSION:
        raise ValidationError("unsupported schemaVersion")
    _require_text(result, "company")
    _require_text(result, "title")
    if result.get("recruitmentType") not in RECRUITMENT_TYPES:
        raise ValidationError("recruitmentType is required and must be supported")
    if result.get("poolStatus", "discovered") not in POOL_STATUSES:
        raise ValidationError("poolStatus is unsupported")
    for key in ("cities", "skills", "sources", "recommendationReasons", "gaps", "riskFlags"):
        _validate_list(result, key)
    for source in result.get("sources", []):
        if not isinstance(source, dict):
            raise ValidationError("each source must be an object")
        _reject_unknown(source, SOURCE_KEYS, "source")
        _require_text(source, "name")
        _validate_url(source.get("url"), "source url")
        tier = source.get("tier")
        if isinstance(tier, bool) or not isinstance(tier, int) or tier not in {1, 2, 3, 4}:
            raise ValidationError("source tier must be an integer from 1 to 4")
    window = result.get("graduationWindow")
    if window is not None:
        if not isinstance(window, list) or len(window) != 2:
            raise ValidationError("graduationWindow must contain start and end dates")
        _validate_date(window[0], "graduationWindow start")
        _validate_date(window[1], "graduationWindow end")
    _validate_optional_number(result, "experienceMin")
    _validate_optional_number(result, "experienceMax")
    _validate_optional_number(result, "score")
    _validate_url(result.get("officialUrl"), "officialUrl")
    _validate_url(result.get("applyUrl"), "applyUrl")
    link_type = result.get("linkType")
    if link_type is not None and link_type not in LINK_TYPES:
        raise ValidationError("linkType is unsupported")
    _validate_url(result.get("linkUrl"), "linkUrl")
    hint = result.get("linkSearchHint")
    if hint is not None and (not isinstance(hint, str) or not hint.strip()):
        raise ValidationError("linkSearchHint must be non-empty text or null")
    for key in ("publishedAt", "deadlineAt", "firstDiscoveredAt", "lastVerifiedAt"):
        _validate_iso(result.get(key), key)
    if not isinstance(result.get("scoreBreakdown", {}), dict):
        raise ValidationError("scoreBreakdown must be an object")
    return result


def validate_company_policy(value: dict) -> dict:
    if not isinstance(value, dict):
        raise ValidationError("company policy must be an object")
    result = deepcopy(value)
    _reject_unknown(result, COMPANY_POLICY_KEYS, "company policy")
    if result.get("schemaVersion") != SCHEMA_VERSION:
        raise ValidationError("unsupported schemaVersion")
    _require_text(result, "company")
    if result.get("recruitmentType") not in RECRUITMENT_TYPES:
        raise ValidationError("recruitmentType is required and must be supported")

    limit = result.get("maxApplications")
    if limit is not None and (
        isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0
    ):
        raise ValidationError("maxApplications must be a positive integer or null")

    can_change = result.get("canChangeSubmittedRole")
    if can_change is not None and not isinstance(can_change, bool):
        raise ValidationError("canChangeSubmittedRole must be boolean or null")

    summary = result.get("ruleSummary")
    if summary is not None and (not isinstance(summary, str) or not summary.strip()):
        raise ValidationError("ruleSummary must be non-empty text or null")

    _validate_url(result.get("officialUrl"), "officialUrl")
    _validate_iso(result.get("lastVerifiedAt"), "lastVerifiedAt")
    state = result.get("verificationState")
    if state not in POLICY_VERIFICATION_STATES:
        raise ValidationError("verificationState is unsupported")
    if state == "verified":
        if not result.get("officialUrl"):
            raise ValidationError("officialUrl is required for a verified policy")
        if not isinstance(summary, str) or not summary.strip():
            raise ValidationError("ruleSummary is required for a verified policy")
    return result


def validate_application(value: dict) -> dict:
    if not isinstance(value, dict):
        raise ValidationError("application must be an object")
    result = deepcopy(value)
    _reject_unknown(result, APPLICATION_KEYS, "application")
    if result.get("schemaVersion") != SCHEMA_VERSION:
        raise ValidationError("unsupported schemaVersion")
    for key in ("id", "jobId", "company", "title"):
        _require_text(result, key)
    if result.get("status") not in APPLICATION_STATUSES:
        raise ValidationError("status is unsupported")
    for key in ("cities", "evidenceLinks", "history"):
        _validate_list(result, key)
    for event in result.get("history", []):
        if not isinstance(event, dict):
            raise ValidationError("each history event must be an object")
        _reject_unknown(event, HISTORY_EVENT_KEYS, "history event")
        _validate_iso(event.get("timestamp"), "history timestamp")
        if event.get("channel") not in UPDATE_CHANNELS:
            raise ValidationError("history channel is unsupported")
        changes = event.get("changes")
        if not isinstance(changes, dict) or not changes:
            raise ValidationError("history changes must be a non-empty object")
        unknown_changes = sorted(set(changes) - APPLICATION_MUTABLE_KEYS)
        if unknown_changes:
            raise ValidationError(
                f"unknown history change fields: {', '.join(unknown_changes)}"
            )
        for field, change in changes.items():
            if not isinstance(change, dict):
                raise ValidationError(f"history change for {field} must be an object")
            _reject_unknown(change, CHANGE_KEYS, "history change")
            if set(change) != CHANGE_KEYS:
                raise ValidationError("history change must contain old and new")
    _validate_url(result.get("officialUrl"), "officialUrl")
    _validate_url(result.get("applyUrl"), "applyUrl")
    for index, link in enumerate(result.get("evidenceLinks", [])):
        _validate_url(link, f"evidenceLinks[{index}]")
    for key in ("appliedAt", "nextActionAt", "updatedAt"):
        _validate_iso(result.get(key), key)
    return result
