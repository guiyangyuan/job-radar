"""Canonical workspace paths, atomic JSON writes, and bounded backups."""

from __future__ import annotations

import json
import os
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_PROFILE = {
    "schemaVersion": 1,
    "targetRoles": ["待确认"],
    "roleAliases": [],
    "recruitmentTypes": ["campus", "experienced"],
    "cities": [],
    "remotePreference": "neutral",
    "yearsOfExperience": None,
    "graduationDate": None,
    "education": None,
    "skills": [],
    "preferredIndustries": [],
    "preferredCompanyTypes": [],
    "excludedCompanies": [],
    "excludedKeywords": [],
    "excludedCities": [],
    "strictCityFilter": False,
    "scoreWeights": {
        "role": 30,
        "skills": 30,
        "eligibility": 15,
        "location": 10,
        "preference": 10,
        "freshness": 5,
    },
    "confirmed": False,
}
DEFAULT_SETTINGS = {
    "schemaVersion": 1,
    "sourceTiersEnabled": [1, 2, 3, 4],
    "backupRetention": 20,
}


class WorkspaceConflict(RuntimeError):
    """Raised when a workspace changed after it was read."""


@dataclass(frozen=True)
class Workspace:
    root: Path
    profile: Path
    jobs: Path
    applications: Path
    company_policies: Path
    settings: Path
    backups: Path
    exports: Path


def _workspace_paths(root: Path) -> Workspace:
    resolved = root.expanduser().resolve()
    return Workspace(
        root=resolved,
        profile=resolved / "profile.json",
        jobs=resolved / "jobs.json",
        applications=resolved / "applications.json",
        company_policies=resolved / "company-policies.json",
        settings=resolved / "settings.json",
        backups=resolved / "backups",
        exports=resolved / "exports",
    )


def initialize_workspace(root: Path) -> Workspace:
    workspace = _workspace_paths(Path(root))
    workspace.root.mkdir(parents=True, exist_ok=True)
    workspace.backups.mkdir(exist_ok=True)
    workspace.exports.mkdir(exist_ok=True)
    initial_values = (
        (workspace.profile, DEFAULT_PROFILE),
        (workspace.jobs, []),
        (workspace.applications, []),
        (workspace.company_policies, []),
        (workspace.settings, DEFAULT_SETTINGS),
    )
    for path, value in initial_values:
        if not path.exists():
            write_json_atomic(path, value, workspace.backups)
    return workspace


def load_workspace(root: Path) -> Workspace:
    workspace = _workspace_paths(Path(root))
    if not workspace.root.is_dir():
        raise FileNotFoundError(f"workspace does not exist: {workspace.root}")
    workspace.backups.mkdir(exist_ok=True)
    workspace.exports.mkdir(exist_ok=True)
    if not workspace.company_policies.exists():
        write_json_atomic(workspace.company_policies, [], workspace.backups)
    for path in (
        workspace.profile,
        workspace.jobs,
        workspace.applications,
        workspace.settings,
    ):
        if not path.is_file():
            raise FileNotFoundError(f"workspace file does not exist: {path}")
    return workspace


def read_json(path: Path) -> Any:
    with Path(path).open("r", encoding="utf-8") as stream:
        return json.load(stream)


def _backup_name(target: Path) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{target.stem}-{timestamp}.json"


def _trim_backups(backups: Path, stem: str, retention: int) -> None:
    candidates = sorted(backups.glob(f"{stem}-*.json"), reverse=True)
    for old in candidates[retention:]:
        old.unlink()


def write_json_atomic(
    target: Path,
    value: Any,
    backups: Path,
    retention: int = 20,
) -> None:
    target = Path(target)
    backups = Path(backups)
    target.parent.mkdir(parents=True, exist_ok=True)
    backups.mkdir(parents=True, exist_ok=True)

    if target.exists():
        read_json(target)
        shutil.copy2(target, backups / _backup_name(target))

    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()

    _trim_backups(backups, target.stem, max(1, retention))
