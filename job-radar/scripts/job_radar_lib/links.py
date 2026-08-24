"""Job destination resolution and conservative legacy migration."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True)
class JobLink:
    kind: str
    url: str
    label: str
    search_hint: str | None


LABELS = {
    "detail": "查看职位详情",
    "apply": "立即投递",
    "listing": "前往岗位列表",
    "homepage": "前往招聘官网",
}


def _known_link_kind(url: str) -> str | None:
    path = urlsplit(url).path.lower()
    if "/detail/" in path:
        return "detail"
    if any(marker in path for marker in ("/list", "hot-jobs", "/positions")):
        return "listing"
    if path in {"", "/", "/campus", "/jobs", "/careers"}:
        return "homepage"
    return None


def resolve_job_link(job: dict) -> JobLink | None:
    """Return only explicitly classified outbound destinations."""
    kind = job.get("linkType")
    url = job.get("linkUrl")
    if kind and url:
        return JobLink(kind, url, LABELS[kind], job.get("linkSearchHint"))
    return None


def migrate_legacy_link(job: dict) -> dict:
    """Classify known legacy URL shapes without inventing destinations."""
    migrated = dict(job)
    if migrated.get("linkType") and migrated.get("linkUrl"):
        return migrated

    official = migrated.get("officialUrl")
    apply_url = migrated.get("applyUrl")
    kind = None
    destination = None

    if official:
        kind = _known_link_kind(official)
        if kind:
            destination = official

    if not kind and apply_url:
        kind = "apply"
        destination = apply_url

    if not kind and migrated.get("verificationState") == "verified":
        for source in migrated.get("sources", []):
            if not isinstance(source, dict) or source.get("tier") != 1:
                continue
            source_url = source.get("url")
            if not source_url:
                continue
            source_kind = _known_link_kind(source_url)
            if source_kind:
                kind = source_kind
                destination = source_url
                break

    if not kind:
        return migrated

    migrated["linkType"] = kind
    migrated["linkUrl"] = destination
    if kind in {"listing", "homepage"}:
        migrated["linkSearchHint"] = (
            migrated.get("employerJobId") or migrated["title"]
        )
    return migrated
