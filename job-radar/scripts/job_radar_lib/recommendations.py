"""Derived company-grouped recommendations and quota warnings."""

from __future__ import annotations

from copy import deepcopy
from numbers import Real

from .links import resolve_job_link
from .models import normalize_text
from .policies import find_policy


ACTIONABLE_POOL_STATUSES = {"discovered", "saved", "preparing"}
ACTIVE_APPLICATION_STATUSES = {
    "applied",
    "screening",
    "assessment",
    "interview",
    "offer",
}
LINK_PRIORITY = {"detail": 4, "apply": 3, "listing": 2, "homepage": 1, None: 0}


def _serialized_link(job: dict) -> dict | None:
    resolved = resolve_job_link(job)
    if resolved is None:
        return None
    return {
        "kind": resolved.kind,
        "url": resolved.url,
        "label": resolved.label,
        "searchHint": resolved.search_hint,
    }


def _score(value: object) -> float:
    if isinstance(value, Real) and not isinstance(value, bool):
        return float(value)
    return float("-inf")


def _job_sort_key(job: dict) -> tuple[float, int, str]:
    return (
        _score(job.get("score")),
        LINK_PRIORITY.get(job.get("linkType"), 0),
        job.get("publishedAt") or "",
    )


def _policy_label(policy: dict | None) -> str:
    if not policy or policy.get("verificationState") != "verified":
        return "规则未核实"
    limit = policy.get("maxApplications")
    if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
        return "规则未核实"
    if limit == 1:
        return "限投 1 个"
    return f"最多投递 {limit} 个"


def build_company_groups(
    jobs: list[dict],
    applications: list[dict],
    policies: list[dict],
) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for source_job in jobs:
        enriched = deepcopy(source_job)
        enriched["resolvedLink"] = _serialized_link(enriched)
        key = normalize_text(enriched.get("company", ""))
        grouped.setdefault(key, []).append(enriched)

    company_groups = []
    for company_key, company_jobs in grouped.items():
        actionable = sorted(
            (
                item
                for item in company_jobs
                if item.get("poolStatus") in ACTIONABLE_POOL_STATUSES
            ),
            key=_job_sort_key,
            reverse=True,
        )
        non_actionable = sorted(
            (
                item
                for item in company_jobs
                if item.get("poolStatus") not in ACTIONABLE_POOL_STATUSES
            ),
            key=_job_sort_key,
            reverse=True,
        )
        primary = actionable[0] if actionable else None
        policy_job = primary or company_jobs[0]
        recruitment_type = policy_job.get("recruitmentType")
        policy = find_policy(
            policies,
            policy_job.get("company", ""),
            recruitment_type,
        )
        active_count = sum(
            1
            for application in applications
            if normalize_text(application.get("company", "")) == company_key
            and application.get("recruitmentType") == recruitment_type
            and application.get("status") in ACTIVE_APPLICATION_STATUSES
        )
        limit = policy.get("maxApplications") if policy else None
        quota_conflict = (
            isinstance(limit, int)
            and not isinstance(limit, bool)
            and limit > 0
            and active_count >= limit
        )
        company_groups.append(
            {
                "company": policy_job.get("company", ""),
                "totalJobs": len(company_jobs),
                "policy": policy,
                "policyLabel": _policy_label(policy),
                "activeApplicationCount": active_count,
                "quotaConflict": quota_conflict,
                "primary": primary,
                "alternatives": actionable[1:3],
                "remaining": [*actionable[3:], *non_actionable],
            }
        )

    company_groups.sort(
        key=lambda group: (
            group["primary"] is not None,
            _score(group["primary"].get("score")) if group["primary"] else float("-inf"),
            (group["primary"].get("publishedAt") or "") if group["primary"] else "",
        ),
        reverse=True,
    )
    return company_groups
