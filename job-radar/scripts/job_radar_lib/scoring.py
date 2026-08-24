"""Hard filters and deterministic, explainable job-match scoring."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timezone

from .models import normalize_text, validate_job, validate_profile


REMOTE_LABELS = {"remote", "远程", "居家", "全国远程"}


@dataclass(frozen=True)
class ScoreResult:
    score: int
    breakdown: dict[str, int]
    reasons: list[str]
    gaps: list[str]
    filtered_reason: str | None


def _as_datetime(value: str | datetime) -> datetime:
    parsed = (
        value
        if isinstance(value, datetime)
        else datetime.fromisoformat(value.replace("Z", "+00:00"))
    )
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _contains(haystack: str, needle: str) -> bool:
    normalized_haystack = normalize_text(haystack).replace(" ", "")
    normalized_needle = normalize_text(needle).replace(" ", "")
    return bool(normalized_needle and normalized_needle in normalized_haystack)


def _city_values(values: list[str]) -> set[str]:
    return {normalize_text(value) for value in values if str(value).strip()}


def _is_remote(job: dict) -> bool:
    cities = _city_values(job.get("cities", []))
    return bool(cities & {normalize_text(value) for value in REMOTE_LABELS})


def hard_filter(profile: dict, job: dict, now: datetime) -> str | None:
    """Return a stable rejection code, or ``None`` when a job is eligible."""

    profile = validate_profile(profile)
    job = validate_job(job)
    now_utc = _as_datetime(now)

    deadline = job.get("deadlineAt")
    if deadline and _as_datetime(deadline) < now_utc:
        return "deadline_passed"

    company = job.get("company", "")
    if any(
        _contains(company, excluded) or _contains(excluded, company)
        for excluded in profile.get("excludedCompanies", [])
    ):
        return "excluded_company"

    evidence = " ".join(
        [
            job.get("company", ""),
            job.get("title", ""),
            job.get("descriptionSummary", "") or "",
            job.get("industry", "") or "",
            job.get("companyType", "") or "",
            *job.get("skills", []),
        ]
    )
    if any(_contains(evidence, keyword) for keyword in profile.get("excludedKeywords", [])):
        return "excluded_keyword"

    job_cities = _city_values(job.get("cities", []))
    excluded_cities = _city_values(profile.get("excludedCities", []))
    if job_cities & excluded_cities:
        return "excluded_city"

    if job.get("recruitmentType") not in profile.get("recruitmentTypes", []):
        return "recruitment_type_mismatch"

    desired_cities = _city_values(profile.get("cities", []))
    if (
        profile.get("strictCityFilter")
        and desired_cities
        and not job_cities & desired_cities
        and not _is_remote(job)
    ):
        return "city_mismatch"

    years = profile.get("yearsOfExperience")
    minimum = job.get("experienceMin")
    maximum = job.get("experienceMax")
    if years is not None and (
        (minimum is not None and years < minimum)
        or (maximum is not None and years > maximum)
    ):
        return "experience_mismatch"

    graduation_date = profile.get("graduationDate")
    graduation_window = job.get("graduationWindow")
    if (
        job.get("recruitmentType") == "campus"
        and graduation_date
        and graduation_window
    ):
        graduation = date.fromisoformat(graduation_date)
        if not (
            date.fromisoformat(graduation_window[0])
            <= graduation
            <= date.fromisoformat(graduation_window[1])
        ):
            return "graduation_window_mismatch"
    return None


def _role_ratio(profile: dict, job: dict) -> tuple[float, str | None]:
    title = normalize_text(job.get("title", ""))
    title_compact = re.sub(r"[^a-z0-9+#\u4e00-\u9fff]", "", title)
    best_ratio = 0.0
    best_label = None
    for label in [*profile.get("targetRoles", []), *profile.get("roleAliases", [])]:
        normalized = normalize_text(label)
        compact = re.sub(r"[^a-z0-9+#\u4e00-\u9fff]", "", normalized)
        if not compact:
            continue
        if compact == title_compact or compact in title_compact:
            ratio = 1.0
        else:
            left = set(compact)
            right = set(title_compact)
            ratio = (2 * len(left & right) / (len(left) + len(right))) if right else 0.0
        if ratio > best_ratio:
            best_ratio = ratio
            best_label = str(label)
    return best_ratio, best_label


def _score_role(profile: dict, job: dict, weight: int) -> tuple[int, list[str], list[str]]:
    ratio, label = _role_ratio(profile, job)
    points = round(weight * ratio)
    if ratio == 1:
        return points, [f"岗位名称匹配目标：{label}"], []
    if ratio > 0:
        return points, [f"岗位名称与目标部分匹配：{label}"], ["岗位方向需要进一步确认"]
    return 0, [], ["岗位名称与目标方向不匹配"]


def _score_skills(profile: dict, job: dict, weight: int) -> tuple[int, list[str], list[str]]:
    required = {
        normalize_text(value): str(value)
        for value in job.get("skills", [])
        if str(value).strip()
    }
    if not required:
        return 0, [], ["技能要求缺失"]
    owned = {normalize_text(value) for value in profile.get("skills", [])}
    matched_keys = sorted(set(required) & owned)
    missing_keys = sorted(set(required) - owned)
    points = round(weight * len(matched_keys) / len(required))
    reasons = []
    gaps = []
    if matched_keys:
        reasons.append("已匹配技能：" + "、".join(required[key] for key in matched_keys))
    if missing_keys:
        gaps.append("待补充技能：" + "、".join(required[key] for key in missing_keys))
    return points, reasons, gaps


def _score_eligibility(profile: dict, job: dict, weight: int) -> tuple[int, list[str], list[str]]:
    if job.get("recruitmentType") == "campus":
        window = job.get("graduationWindow")
        graduation = profile.get("graduationDate")
        if not window or not graduation:
            return round(weight * 0.5), [], ["毕业时间要求缺失"]
        return weight, [f"毕业时间符合 {window[0]} 至 {window[1]} 的范围"], []

    minimum = job.get("experienceMin")
    maximum = job.get("experienceMax")
    years = profile.get("yearsOfExperience")
    if years is None or (minimum is None and maximum is None):
        return round(weight * 0.5), [], ["经验要求缺失"]
    return weight, [f"工作经验符合岗位要求：{years:g} 年"], []


def _score_location(profile: dict, job: dict, weight: int) -> tuple[int, list[str], list[str]]:
    desired = _city_values(profile.get("cities", []))
    offered = _city_values(job.get("cities", []))
    overlap = sorted(desired & offered)
    if overlap:
        return weight, ["工作地点匹配：" + "、".join(overlap)], []
    if _is_remote(job) and profile.get("remotePreference") == "neutral":
        return round(weight * 0.5), ["岗位支持远程，当前偏好为中立"], []
    if _is_remote(job) and profile.get("remotePreference") in {
        "remote",
        "prefer_remote",
        "remote_only",
    }:
        return weight, ["远程方式符合偏好"], []
    if not desired:
        return round(weight * 0.5), [], ["未设置目标城市"]
    return 0, [], ["工作地点与目标城市不匹配"]


def _preference_match(actual: str | None, desired: list[str]) -> tuple[float, str | None]:
    if not desired:
        return 0.5, None
    if actual and normalize_text(actual) in {normalize_text(value) for value in desired}:
        return 1.0, actual
    return 0.0, None


def _score_preference(profile: dict, job: dict, weight: int) -> tuple[int, list[str], list[str]]:
    industry_ratio, industry = _preference_match(
        job.get("industry"), profile.get("preferredIndustries", [])
    )
    company_ratio, company_type = _preference_match(
        job.get("companyType"), profile.get("preferredCompanyTypes", [])
    )
    points = round(weight * (industry_ratio + company_ratio) / 2)
    matched = [value for value in (industry, company_type) if value]
    reasons = ["偏好匹配：" + "、".join(matched)] if matched else []
    gaps = []
    if profile.get("preferredIndustries") and not industry:
        gaps.append("行业偏好不匹配")
    if profile.get("preferredCompanyTypes") and not company_type:
        gaps.append("企业类型偏好不匹配")
    if not profile.get("preferredIndustries") and not profile.get("preferredCompanyTypes"):
        gaps.append("未设置行业或企业类型偏好")
    return points, reasons, gaps


def _score_freshness(job: dict, now: datetime, weight: int) -> tuple[int, list[str], list[str]]:
    published = job.get("publishedAt")
    if not published:
        return 0, [], ["发布时间缺失"]
    age_days = max(0.0, (_as_datetime(now) - _as_datetime(published)).total_seconds() / 86400)
    if age_days <= 7:
        ratio = 1.0
    elif age_days >= 60:
        ratio = 0.0
    else:
        ratio = (60 - age_days) / 53
    points = round(weight * ratio)
    reasons = [f"岗位发布于 {round(age_days)} 天内"] if points else []
    gaps = ["岗位发布时间较早"] if points < weight else []
    return points, reasons, gaps


def score_job(profile: dict, job: dict, now: datetime) -> ScoreResult:
    """Score one validated job using the profile's six configured weights."""

    profile = validate_profile(profile)
    job = validate_job(job)
    filtered_reason = hard_filter(profile, job, now)
    dimensions = ("role", "skills", "eligibility", "location", "preference", "freshness")
    if filtered_reason:
        return ScoreResult(
            score=0,
            breakdown={name: 0 for name in dimensions},
            reasons=[],
            gaps=[f"岗位已被硬条件过滤：{filtered_reason}"],
            filtered_reason=filtered_reason,
        )

    weights = profile["scoreWeights"]
    scorers = {
        "role": lambda: _score_role(profile, job, weights["role"]),
        "skills": lambda: _score_skills(profile, job, weights["skills"]),
        "eligibility": lambda: _score_eligibility(profile, job, weights["eligibility"]),
        "location": lambda: _score_location(profile, job, weights["location"]),
        "preference": lambda: _score_preference(profile, job, weights["preference"]),
        "freshness": lambda: _score_freshness(job, now, weights["freshness"]),
    }
    breakdown: dict[str, int] = {}
    reasons: list[str] = []
    gaps: list[str] = []
    for dimension in dimensions:
        points, dimension_reasons, dimension_gaps = scorers[dimension]()
        breakdown[dimension] = max(0, min(weights[dimension], points))
        reasons.extend(dimension_reasons)
        gaps.extend(dimension_gaps)
    return ScoreResult(
        score=max(0, min(100, sum(breakdown.values()))),
        breakdown=breakdown,
        reasons=reasons,
        gaps=gaps,
        filtered_reason=None,
    )
