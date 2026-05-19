"""Regression tests for logging extra fields used by worker notification paths."""

import ast
import logging
from pathlib import Path


def test_logging_extra_does_not_use_reserved_log_record_fields() -> None:
    reserved = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__)
    conflicts: list[str] = []

    for path in Path("app").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if keyword.arg != "extra" or not isinstance(keyword.value, ast.Dict):
                    continue
                for key in keyword.value.keys:
                    if (
                        isinstance(key, ast.Constant)
                        and isinstance(key.value, str)
                        and key.value in reserved
                    ):
                        conflicts.append(f"{path}:{node.lineno}:{key.value}")

    assert conflicts == []
