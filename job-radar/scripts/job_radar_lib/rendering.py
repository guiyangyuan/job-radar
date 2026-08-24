"""Self-contained dashboard rendering and privacy-safe static exports."""

from __future__ import annotations

import json
import os
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from .models import (
    validate_application,
    validate_company_policy,
    validate_job,
    validate_profile,
)
from .recommendations import build_company_groups
from .storage import Workspace, read_json


TEMPLATE = Path(__file__).resolve().parents[2] / "assets" / "dashboard-template.html"


def _validated_data(data: dict) -> dict:
    profile = validate_profile(data["profile"])
    jobs = [validate_job(item) for item in data.get("jobs", [])]
    applications = [
        validate_application(item) for item in data.get("applications", [])
    ]
    company_policies = [
        validate_company_policy(item) for item in data.get("companyPolicies", [])
    ]
    return {
        "profile": profile,
        "jobs": jobs,
        "applications": applications,
        "companyPolicies": company_policies,
        "companyGroups": build_company_groups(
            jobs,
            applications,
            company_policies,
        ),
        "generatedAt": data.get("generatedAt")
        or datetime.now(timezone.utc).isoformat(),
    }


def _apply_privacy_mode(data: dict) -> dict:
    private = deepcopy(data)
    for application in private["applications"]:
        application["notes"] = ""
        application["evidenceLinks"] = []
        redacted_history = []
        for event in application.get("history", []):
            clean_event = deepcopy(event)
            changes = clean_event.get("changes", {})
            clean_event["changes"] = {
                key: value
                for key, value in changes.items()
                if key not in {"notes", "evidenceLinks"}
            }
            if clean_event["changes"]:
                redacted_history.append(clean_event)
        application["history"] = redacted_history
    return private


def _escape_json_for_html(value: dict) -> str:
    serialized = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return (
        serialized.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def render_dashboard(data: dict, *, editable: bool, privacy: bool) -> str:
    canonical = _validated_data(data)
    if privacy:
        canonical = _apply_privacy_mode(canonical)
    template = TEMPLATE.read_text(encoding="utf-8")
    edit_marker = (
        '<template data-action="application-status"></template>' if editable else ""
    )
    return (
        template.replace("__INITIAL_DATA__", _escape_json_for_html(canonical))
        .replace("__EDITABLE__", "true" if editable else "false")
        .replace("__MODE_LABEL__", "本地可编辑" if editable else "只读快照")
        .replace("__EDIT_CONTROLS_MARKER__", edit_marker)
    )


def write_export(
    workspace: Workspace,
    output: Path | None = None,
    *,
    privacy: bool,
) -> Path:
    target = Path(output) if output else workspace.exports / "dashboard.html"
    target = target.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "profile": read_json(workspace.profile),
        "jobs": read_json(workspace.jobs),
        "applications": read_json(workspace.applications),
        "companyPolicies": read_json(workspace.company_policies),
        "generatedAt": datetime.now(timezone.utc).isoformat(),
    }
    html = render_dashboard(data, editable=False, privacy=privacy)
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            stream.write(html)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return target
