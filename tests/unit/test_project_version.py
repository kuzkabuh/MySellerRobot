"""version: 1.0.0
description: Tests that project version is consistent across config files.
updated: 2026-06-10
"""

from pathlib import Path

import pytest

EXPECTED_VERSION = "1.15.1"


def _read_version_from_pyproject() -> str:
    path = Path("pyproject.toml")
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("version ="):
            return line.split("=", 1)[1].strip().strip('"')
    pytest.fail("version not found in pyproject.toml")


def _read_version_from_file() -> str:
    path = Path("VERSION")
    return path.read_text(encoding="utf-8").strip()


def test_version_pyproject() -> None:
    assert _read_version_from_pyproject() == EXPECTED_VERSION


def test_version_file() -> None:
    assert _read_version_from_file() == EXPECTED_VERSION


def test_versions_consistent() -> None:
    assert _read_version_from_pyproject() == _read_version_from_file()
