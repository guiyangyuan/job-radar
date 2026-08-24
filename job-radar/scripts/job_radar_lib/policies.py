"""Validated company application policy lookup and refresh merging."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .models import normalize_text, validate_company_policy


@dataclass(frozen=True)
class PolicyMergeResult:
    policies: list[dict]
    added: int
    updated: int
    unchanged: int


def _identity(policy: dict) -> tuple[str, str]:
    return (
        normalize_text(policy.get("company", "")),
        policy.get("recruitmentType", ""),
    )


def _instant(value: str | None) -> datetime:
    if not value:
        return datetime.min
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        return parsed.replace(tzinfo=None) - parsed.utcoffset()
    return parsed


def find_policy(
    policies: list[dict],
    company: str,
    recruitment_type: str,
) -> dict | None:
    target = (normalize_text(company), recruitment_type)
    for raw_policy in policies:
        policy = validate_company_policy(raw_policy)
        if _identity(policy) == target:
            return policy
    return None


def merge_policies(
    existing_policies: list[dict],
    incoming_policies: list[dict],
) -> PolicyMergeResult:
    by_identity = {
        _identity(policy): policy
        for policy in (validate_company_policy(item) for item in existing_policies)
    }
    added = updated = unchanged = 0

    for raw_incoming in incoming_policies:
        incoming = validate_company_policy(raw_incoming)
        key = _identity(incoming)
        current = by_identity.get(key)
        if current is None:
            by_identity[key] = incoming
            added += 1
        elif _instant(incoming.get("lastVerifiedAt")) > _instant(
            current.get("lastVerifiedAt")
        ):
            by_identity[key] = incoming
            updated += 1
        else:
            unchanged += 1

    policies = sorted(
        by_identity.values(),
        key=lambda item: (
            normalize_text(item["company"]),
            item["recruitmentType"],
        ),
    )
    return PolicyMergeResult(policies, added, updated, unchanged)
