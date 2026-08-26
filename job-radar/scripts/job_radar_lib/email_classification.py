"""Deterministic, explainable recruitment-email classification."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone

from .imap_sync import FetchedMessage


@dataclass(frozen=True)
class EmailCandidate:
    company: str | None
    title: str | None
    employer_job_id: str | None
    proposed_status: str | None
    interview_stage: str | None
    next_action: str | None
    next_action_at: str | None
    classification: str
    confidence: float
    reasons: tuple[str, ...]


STAGE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "rejected",
        (
            r"(?:未通过|不通过|未能通过|不予录用)",
            r"很遗憾.{0,30}(?:未能继续|无法继续|不匹配)",
        ),
    ),
    (
        "closed",
        (
            r"(?:岗位|职位|招聘流程).{0,15}(?:已)?(?:关闭|取消|终止)",
            r"招聘已结束",
        ),
    ),
    ("offer", (r"正式录用通知", r"录用通知(?:书)?", r"\boffer\b")),
    (
        "interview",
        (
            r"面试邀请",
            r"(?:技术|业务|hr|主管|交叉)?(?:一面|二面|三面|终面|群面)",
            r"邀请.{0,30}(?:面试|面谈)",
        ),
    ),
    ("assessment", (r"在线测评", r"测评邀请", r"笔试(?:邀请|通知)?")),
    ("screening", (r"简历已进入筛选", r"进入简历筛选", r"筛选流程")),
    (
        "applied",
        (r"投递成功", r"申请已收到", r"简历已收到", r"收到.{0,10}(?:申请|简历)"),
    ),
)
MARKETING_RULES = (
    r"加入人才库",
    r"人才库",
    r"订阅.{0,15}(?:招聘|校招|职位|资讯)",
    r"(?:校园)?宣讲会",
    r"职位推荐",
)
INTERVIEW_STAGES = (
    "技术一面",
    "技术二面",
    "技术三面",
    "业务一面",
    "业务二面",
    "主管面",
    "交叉面",
    "HR面",
    "hr面",
    "一面",
    "二面",
    "三面",
    "终面",
    "群面",
)


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "")
    lines = [re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in value.split("\n")]
    return "\n".join(line for line in lines if line)


def _first_group(patterns: tuple[str, ...], text: str) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def _extract_fields(text: str) -> tuple[str | None, str | None, str | None]:
    company = _first_group(
        (
            r"(?:公司|企业|招聘单位)\s*[:：]\s*([^\n,，;；]{2,60})",
            r"您的\s*([^\n,，;；]{2,30}?)(?:申请|简历)(?:已收到|已进入|进度)",
        ),
        text,
    )
    title = _first_group(
        (
            r"(?:应聘岗位|应聘职位|岗位名称|职位名称)\s*[:：]\s*([^\n,，;；]{2,80})",
            r"(?:岗位|职位)\s*[:：]\s*([^\n,，;；]{2,80})",
        ),
        text,
    )
    job_id = _first_group(
        (
            r"(?:职位编号|岗位编号|申请编号|job\s*id)\s*[:：#]?\s*([A-Za-z0-9._-]{2,64})",
        ),
        text,
    )
    return company, title, job_id


def _extract_deadline(text: str, now: datetime) -> tuple[str | None, bool]:
    if not re.search(r"(?:截止|之前|前完成|前参加|请于)", text, re.IGNORECASE):
        return None, False
    patterns = (
        re.compile(
            r"(?P<year>20\d{2})年(?P<month>\d{1,2})月(?P<day>\d{1,2})日"
            r"(?:\s*(?P<hour>\d{1,2})[:：](?P<minute>\d{2}))?"
        ),
        re.compile(
            r"(?<!\d)(?P<month>\d{1,2})月(?P<day>\d{1,2})日"
            r"(?:\s*(?P<hour>\d{1,2})[:：](?P<minute>\d{2}))?"
        ),
        re.compile(
            r"(?P<year>20\d{2})-(?P<month>\d{1,2})-(?P<day>\d{1,2})"
            r"(?:[ T](?P<hour>\d{1,2}):(?P<minute>\d{2}))?"
        ),
    )
    for pattern in patterns:
        match = pattern.search(text)
        if not match:
            continue
        values = match.groupdict()
        try:
            deadline = datetime(
                int(values.get("year") or now.year),
                int(values["month"]),
                int(values["day"]),
                int(values.get("hour") or 23),
                int(values.get("minute") or 59),
                tzinfo=now.tzinfo or timezone.utc,
            )
        except ValueError:
            return None, True
        return deadline.isoformat(), False
    return None, bool(re.search(r"(?:20\d{2}年)?\d{1,2}月\d{1,2}日", text))


def _next_action(status: str | None) -> str | None:
    return {
        "applied": "等待招聘反馈",
        "screening": "关注筛选进度",
        "assessment": "完成在线测评",
        "interview": "参加面试",
        "offer": "确认录用安排",
    }.get(status)


def classify_message(message: FetchedMessage, now: datetime) -> EmailCandidate:
    subject = _normalize(message.subject)
    body = _normalize(message.text[:12_000])
    text = f"{subject}\n{body}".strip()
    company, title, job_id = _extract_fields(text)
    reasons: list[str] = []

    if any(re.search(pattern, text, re.IGNORECASE) for pattern in MARKETING_RULES):
        reasons.append("检测到人才库、宣讲会或职位营销信息")
        return EmailCandidate(
            company,
            title,
            job_id,
            None,
            None,
            None,
            None,
            "irrelevant",
            0.0,
            tuple(reasons),
        )

    matches: list[str] = []
    for status, patterns in STAGE_RULES:
        if any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns):
            matches.append(status)
    if len(matches) > 1:
        reasons.append("同一邮件包含互相矛盾的招聘阶段证据")
        return EmailCandidate(
            company,
            title,
            job_id,
            None,
            None,
            None,
            None,
            "conflict",
            0.0,
            tuple(reasons),
        )

    status = matches[0] if matches else None
    if status is None:
        reasons.append("未检测到足以更新求职阶段的明确证据")
        return EmailCandidate(
            company,
            title,
            job_id,
            None,
            None,
            None,
            None,
            "incomplete",
            0.0,
            tuple(reasons),
        )

    reasons.append(f"检测到明确的 {status} 阶段证据")
    interview_stage = None
    if status == "interview":
        interview_stage = next((stage for stage in INTERVIEW_STAGES if stage in text), None)
        if interview_stage:
            interview_stage = interview_stage.replace("hr", "HR")
    deadline, malformed_date = _extract_deadline(text, now)
    if malformed_date:
        reasons.append("检测到日期文本但无法安全解析，未生成截止时间")
    confidence = 0.45
    if company:
        confidence += 0.20
        reasons.append("提取到明确公司")
    if title or job_id:
        confidence += 0.20
        reasons.append("提取到岗位或职位编号")
    if deadline or interview_stage:
        confidence += 0.15
        reasons.append("提取到行动时间或面试阶段")
    return EmailCandidate(
        company=company,
        title=title,
        employer_job_id=job_id,
        proposed_status=status,
        interview_stage=interview_stage,
        next_action=_next_action(status),
        next_action_at=deadline,
        classification="actionable",
        confidence=min(1.0, round(confidence, 2)),
        reasons=tuple(reasons),
    )
