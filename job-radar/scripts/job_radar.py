#!/usr/bin/env python3
"""Job Radar command-line interface."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from job_radar_lib.applications import (
    ApplicationConflict,
    ApplicationNotFound,
    create_application,
    find_application,
    update_application,
)
from job_radar_lib.links import migrate_legacy_link
from job_radar_lib.merge import merge_jobs
from job_radar_lib.models import (
    APPLICATION_STATUSES,
    ValidationError,
    validate_application,
    validate_company_policy,
    validate_job,
    validate_profile,
)
from job_radar_lib.policies import merge_policies
from job_radar_lib.rendering import write_export
from job_radar_lib.scoring import score_job
from job_radar_lib.server import serve
from job_radar_lib.storage import (
    WorkspaceConflict,
    initialize_workspace,
    load_workspace,
    read_json,
    write_json_atomic,
)


def _print_json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def _now(value: str | None = None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _workspace(value: str):
    return load_workspace(Path(value))


def _read_canonical(workspace):
    profile = validate_profile(read_json(workspace.profile))
    jobs = [validate_job(item) for item in read_json(workspace.jobs)]
    applications = [
        validate_application(item) for item in read_json(workspace.applications)
    ]
    company_policies = [
        validate_company_policy(item) for item in read_json(workspace.company_policies)
    ]
    settings = read_json(workspace.settings)
    if not isinstance(settings, dict) or settings.get("schemaVersion") != 1:
        raise ValidationError("settings.json has an unsupported schemaVersion")
    if set(settings) != {"schemaVersion", "sourceTiersEnabled", "backupRetention"}:
        raise ValidationError("settings.json contains unknown or missing fields")
    if not isinstance(settings["sourceTiersEnabled"], list):
        raise ValidationError("sourceTiersEnabled must be a list")
    if not isinstance(settings["backupRetention"], int) or settings["backupRetention"] < 1:
        raise ValidationError("backupRetention must be a positive integer")
    job_ids = [item.get("id") for item in jobs]
    application_ids = [item.get("id") for item in applications]
    if len(job_ids) != len(set(job_ids)):
        raise ValidationError("jobs.json contains duplicate ids")
    if len(application_ids) != len(set(application_ids)):
        raise ValidationError("applications.json contains duplicate ids")
    return profile, jobs, applications, company_policies, settings


def command_init(args) -> int:
    workspace = initialize_workspace(Path(args.workspace))
    print(f"initialized: {workspace.root}")
    return 0


def command_validate(args) -> int:
    workspace = _workspace(args.workspace)
    profile, jobs, applications, company_policies, _settings = _read_canonical(workspace)
    _print_json(
        {
            "valid": True,
            "profileConfirmed": profile["confirmed"],
            "jobs": len(jobs),
            "applications": len(applications),
            "companyPolicies": len(company_policies),
        }
    )
    return 0


def command_merge_jobs(args) -> int:
    workspace = _workspace(args.workspace)
    _profile, existing, _applications, _policies, _settings = _read_canonical(workspace)
    incoming_value = read_json(Path(args.input))
    incoming = incoming_value.get("jobs") if isinstance(incoming_value, dict) else incoming_value
    if not isinstance(incoming, list):
        raise ValidationError("job input must be a JSON array or an object with jobs")
    result = merge_jobs(existing, incoming)
    write_json_atomic(workspace.jobs, result.jobs, workspace.backups)
    _print_json(
        {
            "added": result.added,
            "updated": result.updated,
            "unchanged": result.unchanged,
            "total": len(result.jobs),
        }
    )
    return 0


def command_migrate_links(args) -> int:
    workspace = _workspace(args.workspace)
    _profile, jobs, _applications, _policies, _settings = _read_canonical(workspace)
    migrated_jobs = []
    migrated_count = 0
    for job in jobs:
        migrated = validate_job(migrate_legacy_link(job))
        migrated_jobs.append(migrated)
        if migrated != job:
            migrated_count += 1
    if migrated_count:
        write_json_atomic(workspace.jobs, migrated_jobs, workspace.backups)
    _print_json(
        {
            "migrated": migrated_count,
            "unchanged": len(jobs) - migrated_count,
            "total": len(jobs),
        }
    )
    return 0


def command_merge_policies(args) -> int:
    workspace = _workspace(args.workspace)
    _profile, _jobs, _applications, existing, _settings = _read_canonical(workspace)
    incoming_value = read_json(Path(args.input))
    incoming = (
        incoming_value.get("policies")
        if isinstance(incoming_value, dict)
        else incoming_value
    )
    if not isinstance(incoming, list):
        raise ValidationError(
            "policy input must be a JSON array or an object with policies"
        )
    result = merge_policies(existing, incoming)
    write_json_atomic(
        workspace.company_policies,
        result.policies,
        workspace.backups,
    )
    _print_json(
        {
            "added": result.added,
            "updated": result.updated,
            "unchanged": result.unchanged,
            "total": len(result.policies),
        }
    )
    return 0


def command_score(args) -> int:
    workspace = _workspace(args.workspace)
    profile, jobs, _applications, _policies, _settings = _read_canonical(workspace)
    if not profile["confirmed"]:
        raise ValidationError("profile must be confirmed before scoring jobs")
    now = _now(args.now)
    scored = []
    filtered = Counter()
    for job in jobs:
        result = score_job(profile, job, now)
        updated = dict(job)
        updated["score"] = result.score
        updated["scoreBreakdown"] = result.breakdown
        updated["recommendationReasons"] = result.reasons
        updated["gaps"] = result.gaps
        risks = [
            value
            for value in updated.get("riskFlags", [])
            if not str(value).startswith("filtered:")
        ]
        if result.filtered_reason:
            filtered[result.filtered_reason] += 1
            risks.append("filtered:" + result.filtered_reason)
            if result.filtered_reason == "deadline_passed":
                updated["poolStatus"] = "expired"
        updated["riskFlags"] = risks
        scored.append(validate_job(updated))
    write_json_atomic(workspace.jobs, scored, workspace.backups)
    _print_json({"scored": len(scored), "filtered": dict(filtered)})
    return 0


def _find_job(jobs: list[dict], job_id: str) -> tuple[int, dict]:
    for index, job in enumerate(jobs):
        if job.get("id") == job_id:
            return index, job
    raise ApplicationNotFound(f"job not found: {job_id}")


def command_apply(args) -> int:
    if not args.confirmed:
        raise ValueError("explicit confirmation is required before recording an application")
    workspace = _workspace(args.workspace)
    _profile, jobs, applications, _policies, _settings = _read_canonical(workspace)
    job_index, job = _find_job(jobs, args.job_id)
    if any(
        item.get("jobId") == args.job_id and item.get("status") != "archived"
        for item in applications
    ):
        raise ApplicationConflict("an active application already exists for this job")
    created, updated_job = create_application(
        job, _now(), confirmed=True, channel="conversation"
    )
    updated_jobs = list(jobs)
    updated_applications = list(applications)
    updated_jobs[job_index] = updated_job
    updated_applications.append(created)
    write_json_atomic(workspace.jobs, updated_jobs, workspace.backups)
    write_json_atomic(
        workspace.applications, updated_applications, workspace.backups
    )
    _print_json({"applicationId": created["id"], "jobId": created["jobId"]})
    return 0


def command_update(args) -> int:
    workspace = _workspace(args.workspace)
    _profile, _jobs, applications, _policies, _settings = _read_canonical(workspace)
    current = find_application(applications, args.application_id)
    updates = {}
    for argument, key in (
        (args.status, "status"),
        (args.interview_stage, "interviewStage"),
        (args.next_action, "nextAction"),
        (args.next_action_at, "nextActionAt"),
        (args.notes, "notes"),
    ):
        if argument is not None:
            updates[key] = argument
    if args.evidence_link is not None:
        updates["evidenceLinks"] = args.evidence_link
    if not updates:
        raise ValueError("at least one application update field is required")
    updated = update_application(
        current,
        updates,
        _now(),
        args.channel,
        expected_updated_at=args.expected_updated_at,
    )
    index = next(
        index for index, item in enumerate(applications) if item["id"] == args.application_id
    )
    applications[index] = updated
    write_json_atomic(workspace.applications, applications, workspace.backups)
    _print_json({"applicationId": updated["id"], "updatedAt": updated["updatedAt"]})
    return 0


def command_export(args) -> int:
    workspace = _workspace(args.workspace)
    _read_canonical(workspace)
    output = write_export(
        workspace,
        Path(args.output) if args.output else None,
        privacy=args.privacy,
    )
    print(output)
    return 0


def _summary(jobs: list[dict], applications: list[dict]) -> dict:
    return {
        "totals": {"jobs": len(jobs), "applications": len(applications)},
        "jobs": dict(sorted(Counter(job.get("poolStatus", "unknown") for job in jobs).items())),
        "applications": dict(
            sorted(Counter(item.get("status", "unknown") for item in applications).items())
        ),
    }


def command_summary(args) -> int:
    workspace = _workspace(args.workspace)
    _profile, jobs, applications, _policies, _settings = _read_canonical(workspace)
    summary = _summary(jobs, applications)
    if args.json:
        _print_json(summary)
    else:
        print(
            f"岗位 {summary['totals']['jobs']} 个，投递 {summary['totals']['applications']} 个"
        )
        for status, count in summary["applications"].items():
            print(f"- {status}: {count}")
    return 0


def command_serve(args) -> int:
    workspace = _workspace(args.workspace)
    _read_canonical(workspace)
    serve(workspace, port=args.port, open_browser=not args.no_open)
    return 0


def _workspace_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--workspace", required=True, help="Job Radar 数据目录")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="job-radar",
        description="发现、筛选并跟踪中国大陆校招、社招与实习岗位。",
    )
    parser.add_argument("--version", action="version", version="Job Radar 0.1.0-rc.1")
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init", help="初始化本地数据目录")
    _workspace_argument(init)
    init.set_defaults(handler=command_init)

    validate = commands.add_parser("validate", help="校验全部数据文件")
    _workspace_argument(validate)
    validate.set_defaults(handler=command_validate)

    merge = commands.add_parser("merge-jobs", help="合并标准化岗位 JSON")
    _workspace_argument(merge)
    merge.add_argument("--input", required=True, help="岗位 JSON 文件")
    merge.set_defaults(handler=command_merge_jobs)

    migrate_links = commands.add_parser("migrate-links", help="保守迁移旧岗位链接")
    _workspace_argument(migrate_links)
    migrate_links.set_defaults(handler=command_migrate_links)

    merge_policy = commands.add_parser(
        "merge-policies", help="合并已核实的公司投递规则"
    )
    _workspace_argument(merge_policy)
    merge_policy.add_argument("--input", required=True, help="公司投递规则 JSON 文件")
    merge_policy.set_defaults(handler=command_merge_policies)

    score = commands.add_parser("score", help="执行硬过滤与可解释评分")
    _workspace_argument(score)
    score.add_argument("--now", help="用于可复现评分的 ISO-8601 时间")
    score.set_defaults(handler=command_score)

    apply = commands.add_parser("apply", help="确认实际投递并创建记录")
    _workspace_argument(apply)
    apply.add_argument("--job-id", required=True)
    apply.add_argument("--confirmed", action="store_true")
    apply.set_defaults(handler=command_apply)

    update = commands.add_parser("update", help="更新投递状态并记录历史")
    _workspace_argument(update)
    update.add_argument("--application-id", required=True)
    update.add_argument("--status", choices=sorted(APPLICATION_STATUSES))
    update.add_argument("--interview-stage")
    update.add_argument("--next-action")
    update.add_argument("--next-action-at")
    update.add_argument("--notes")
    update.add_argument("--evidence-link", action="append")
    update.add_argument("--expected-updated-at")
    update.add_argument(
        "--channel",
        choices=["conversation", "dashboard", "email", "screenshot", "portal"],
        default="conversation",
    )
    update.set_defaults(handler=command_update)

    export = commands.add_parser("export", help="导出自包含只读 HTML")
    _workspace_argument(export)
    export.add_argument("--output")
    export.add_argument("--privacy", action="store_true")
    export.set_defaults(handler=command_export)

    summary = commands.add_parser("summary", help="汇总岗位与投递状态")
    _workspace_argument(summary)
    summary.add_argument("--json", action="store_true")
    summary.set_defaults(handler=command_summary)

    serve_command = commands.add_parser("serve", help="启动本机可编辑工作台")
    _workspace_argument(serve_command)
    serve_command.add_argument("--port", type=int, default=0)
    serve_command.add_argument("--no-open", action="store_true")
    serve_command.set_defaults(handler=command_serve)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except (ApplicationConflict, WorkspaceConflict) as exc:
        print(f"conflict: {exc}", file=sys.stderr)
        return 3
    except (
        ValidationError,
        FileNotFoundError,
        ApplicationNotFound,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
