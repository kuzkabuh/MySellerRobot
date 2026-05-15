"""version: 1.1.0
description: DTOs for deployment status, version metadata, update checks, and backup metadata.
updated: 2026-05-15
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class CurrentVersion:
    """Current application version from the production worktree."""

    version: str
    branch: str
    commit: str
    last_commit_message: str
    updated_at: str
    source: str


@dataclass(slots=True)
class UpdateCheckResult:
    """Result of comparing the local commit with the remote branch."""

    branch: str
    current_commit: str
    remote_commit: str
    has_updates: bool
    checked_at: datetime


@dataclass(slots=True)
class DeploymentStatus:
    """Structured status written by deploy/update.sh."""

    status: str
    started_at: str | None
    finished_at: str | None
    previous_commit: str | None
    new_commit: str | None
    remote_commit: str | None
    branch: str | None
    migrations_applied: bool
    backup_created: bool
    healthcheck_passed: bool
    backup_metadata_path: str | None
    message: str

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "DeploymentStatus":
        return cls(
            status=str(data.get("status") or "unknown"),
            started_at=data.get("started_at"),
            finished_at=data.get("finished_at"),
            previous_commit=data.get("previous_commit"),
            new_commit=data.get("new_commit"),
            remote_commit=data.get("remote_commit"),
            branch=data.get("branch"),
            migrations_applied=bool(data.get("migrations_applied")),
            backup_created=bool(data.get("backup_created")),
            healthcheck_passed=bool(data.get("healthcheck_passed")),
            backup_metadata_path=data.get("backup_metadata_path"),
            message=str(data.get("message") or ""),
        )


@dataclass(slots=True)
class BackupInfo:
    """Single deploy backup metadata item."""

    created_at: str
    git_commit: str
    git_branch: str
    app_version: str
    db_backup_path: str
    env_backup_path: str | None
    metadata_path: Path
    size_bytes: int
