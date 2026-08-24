"""Deterministic job identity, source precedence, and refresh merging."""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .models import normalize_text, validate_job


TRACKING_QUERY_KEYS = {"ref", "source", "spread"}
USER_OWNED_FIELDS = {
    "id",
    "poolStatus",
    "firstDiscoveredAt",
    "score",
    "scoreBreakdown",
    "recommendationReasons",
    "gaps",
    "riskFlags",
}


@dataclass(frozen=True)
class MergeResult:
    jobs: list[dict]
    added: int
    updated: int
    unchanged: int


def canonical_url(value: str | None) -> str | None:
    """Remove tracking noise while preserving query parameters with job meaning."""

    if not value:
        return None
    parts = urlsplit(value.strip())
    scheme = parts.scheme.lower()
    host = parts.netloc.lower()
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if path != "/":
        path = path.rstrip("/")
    query = []
    for key, item in parse_qsl(parts.query, keep_blank_values=True):
        lowered = key.lower()
        if lowered.startswith("utm_") or lowered in TRACKING_QUERY_KEYS:
            continue
        query.append((key, item))
    query.sort()
    return urlunsplit((scheme, host, path, urlencode(query), ""))


def _normalized_values(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted({normalize_text(value) for value in values if str(value).strip()}))


def _composite_identity(job: dict) -> tuple:
    return (
        "composite",
        normalize_text(job.get("company", "")),
        normalize_text(job.get("title", "")),
        _normalized_values(job.get("cities", [])),
        normalize_text(job.get("recruitmentType", "")),
    )


def _identity_keys(job: dict) -> list[tuple]:
    keys: list[tuple] = []
    official_url = canonical_url(job.get("officialUrl"))
    if official_url and job.get("linkType") in {"detail", "apply"}:
        keys.append(("url", official_url))
    employer_job_id = normalize_text(job.get("employerJobId") or "")
    if employer_job_id:
        keys.append(
            (
                "employer",
                normalize_text(job.get("company", "")),
                employer_job_id,
            )
        )
    keys.append(_composite_identity(job))
    return keys


def stable_job_id(job: dict) -> str:
    """Build a stable, non-personal identifier from material vacancy fields."""

    payload = json.dumps(
        _composite_identity(job), ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return f"job_{hashlib.sha256(payload).hexdigest()[:16]}"


def _meaningful(value: object) -> bool:
    return value is not None and value != "" and value != [] and value != {}


def _instant(value: str | None) -> datetime:
    if not value:
        return datetime.min
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        return parsed.replace(tzinfo=None) - parsed.utcoffset()
    return parsed


def _merge_sources(existing: list, incoming: list) -> list:
    merged: dict[tuple[str, str], dict] = {}
    for source in [*existing, *incoming]:
        if not isinstance(source, dict):
            continue
        name = str(source.get("name", "")).strip()
        url = canonical_url(source.get("url")) or ""
        key = (normalize_text(name), url)
        candidate = deepcopy(source)
        if url:
            candidate["url"] = url
        previous = merged.get(key)
        if previous is None or candidate.get("tier", 99) < previous.get("tier", 99):
            merged[key] = candidate
    return sorted(
        merged.values(),
        key=lambda source: (
            source.get("tier", 99),
            normalize_text(source.get("name", "")),
            source.get("url", ""),
        ),
    )


def _merge_record(existing: dict, incoming: dict) -> dict:
    result = deepcopy(existing)
    existing_tier = existing.get("sourceTier", 99)
    incoming_tier = incoming.get("sourceTier", 99)
    incoming_is_preferred = incoming_tier < existing_tier or (
        incoming_tier == existing_tier
        and _instant(incoming.get("lastVerifiedAt"))
        > _instant(existing.get("lastVerifiedAt"))
    )

    for key, value in incoming.items():
        if key in USER_OWNED_FIELDS or key == "sources":
            continue
        if not _meaningful(value):
            continue
        if not _meaningful(result.get(key)) or incoming_is_preferred:
            result[key] = deepcopy(value)

    result["sources"] = _merge_sources(
        existing.get("sources", []), incoming.get("sources", [])
    )
    result["sourceTier"] = min(existing_tier, incoming_tier)
    if _instant(incoming.get("lastVerifiedAt")) > _instant(
        existing.get("lastVerifiedAt")
    ):
        result["lastVerifiedAt"] = incoming["lastVerifiedAt"]
    return result


def merge_jobs(existing_jobs: list[dict], incoming_jobs: list[dict]) -> MergeResult:
    """Merge a refresh into the canonical pool without losing user state."""

    jobs = [validate_job(job) for job in existing_jobs]
    identities: dict[tuple, int] = {}
    for index, job in enumerate(jobs):
        for key in _identity_keys(job):
            identities.setdefault(key, index)

    added = updated = unchanged = 0
    for raw_incoming in incoming_jobs:
        incoming = validate_job(raw_incoming)
        match = next(
            (identities[key] for key in _identity_keys(incoming) if key in identities),
            None,
        )
        if match is None:
            new_job = deepcopy(incoming)
            new_job["id"] = stable_job_id(new_job)
            jobs.append(new_job)
            new_index = len(jobs) - 1
            for key in _identity_keys(new_job):
                identities[key] = new_index
            added += 1
            continue

        before = jobs[match]
        after = _merge_record(before, incoming)
        jobs[match] = after
        for key in _identity_keys(after):
            identities[key] = match
        if after == before:
            unchanged += 1
        else:
            updated += 1

    jobs.sort(key=lambda item: (item.get("firstDiscoveredAt", ""), item["id"]))
    return MergeResult(jobs=jobs, added=added, updated=updated, unchanged=unchanged)
