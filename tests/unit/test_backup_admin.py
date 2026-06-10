"""Tests for backup admin routes and helpers."""

import gzip
import shutil
import tempfile
from pathlib import Path

from app.web.route_modules.backup_admin import (
    _backup_kind,
    _check_integrity,
    _collect_diagnostics,
    _list_backup_files,
    BackupFile,
)


def test_backup_kind_db():
    assert _backup_kind("mpcontrol_db_2026-06-10_03-00-00.dump") == "db"
    assert _backup_kind("mpcontrol_db_2026-06-10_03-00-00.sql.gz") == "db"


def test_backup_kind_files():
    assert _backup_kind("mpcontrol_files_2026-06-10_03-00-00.tar.gz") == "files"


def test_backup_kind_full():
    assert _backup_kind("mpcontrol_full_2026-06-10_03-00-00.tar.gz") == "full"


def test_backup_kind_unknown():
    assert _backup_kind("some_other_file.tar.gz") is None


def test_check_integrity_enc_file():
    """Зашифрованные .enc файлы не проверяются через gzip."""
    with tempfile.NamedTemporaryFile(suffix=".enc", delete=False) as f:
        f.write(b"encrypted content here")
        enc_path = Path(f.name)
    try:
        assert _check_integrity(enc_path) is None
    finally:
        enc_path.unlink(missing_ok=True)


def test_check_integrity_dump_file():
    """Custom dump .dump не проверяется через gzip."""
    with tempfile.NamedTemporaryFile(suffix=".dump", delete=False) as f:
        f.write(b"not a real dump")
        dump_path = Path(f.name)
    try:
        assert _check_integrity(dump_path) is None
    finally:
        dump_path.unlink(missing_ok=True)


def test_check_integrity_sql_gz_valid():
    """.sql.gz проходит gzip-проверку."""
    with tempfile.NamedTemporaryFile(suffix=".sql.gz", delete=False) as f:
        with gzip.open(f, "wb") as gz:
            gz.write(b"PostgreSQL database dump content")
        gz_path = Path(f.name)
    try:
        assert _check_integrity(gz_path) is True
    finally:
        gz_path.unlink(missing_ok=True)


def test_check_integrity_sql_gz_invalid():
    """Испорченный .sql.gz не проходит gzip-проверку."""
    with tempfile.NamedTemporaryFile(suffix=".sql.gz", delete=False) as f:
        f.write(b"not gzip content at all")
        bad_path = Path(f.name)
    try:
        assert _check_integrity(bad_path) is False
    finally:
        bad_path.unlink(missing_ok=True)


def test_check_integrity_tar_gz_valid():
    with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as f:
        with gzip.open(f, "wb") as gz:
            gz.write(b"archive content")
        tgz_path = Path(f.name)
    try:
        assert _check_integrity(tgz_path) is True
    finally:
        tgz_path.unlink(missing_ok=True)


def test_check_integrity_unknown_suffix():
    """Неизвестный суффикс возвращает None."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        f.write(b'{"key": "value"}')
        json_path = Path(f.name)
    try:
        assert _check_integrity(json_path) is None
    finally:
        json_path.unlink(missing_ok=True)


def test_collect_diagnostics_script_not_found(tmp_path: Path):
    diag = _collect_diagnostics(
        script_path=tmp_path / "scripts" / "backup_daily.sh",
        backup_dir=tmp_path / "backups",
        daily_dir=tmp_path / "backups" / "daily",
    )
    assert diag["script_exists"] is False
    assert diag["backup_dir_exists"] is False
    assert diag["daily_dir_exists"] is False
    assert diag["daily_file_count"] == 0


def test_collect_diagnostics_all_exists(tmp_path: Path):
    script_path = tmp_path / "scripts" / "backup_daily.sh"
    script_path.parent.mkdir(parents=True)
    script_path.write_text("#!/bin/bash\necho backup")
    daily_dir = tmp_path / "backups" / "daily"
    daily_dir.mkdir(parents=True)
    (daily_dir / "mpcontrol_db_test.dump").write_text("dump")

    diag = _collect_diagnostics(
        script_path=script_path,
        backup_dir=tmp_path / "backups",
        daily_dir=daily_dir,
    )
    assert diag["script_exists"] is True
    assert diag["backup_dir_exists"] is True
    assert diag["daily_dir_exists"] is True
    assert diag["daily_file_count"] == 1


def test_list_backup_files_empty_dir(tmp_path: Path):
    daily_dir = tmp_path / "backups" / "daily"
    daily_dir.mkdir(parents=True)
    files = _list_backup_files(daily_dir)
    assert files == []


def test_list_backup_files_with_data(tmp_path: Path):
    daily_dir = tmp_path / "backups" / "daily"
    daily_dir.mkdir(parents=True)
    (daily_dir / "mpcontrol_db_2026-06-10_03-00-00.dump").write_text("data")
    (daily_dir / "mpcontrol_files_2026-06-10_03-00-00.tar.gz").write_text("data")
    (daily_dir / "mpcontrol_full_2026-06-10_03-00-00.tar.gz").write_text("data")
    # Этот файл не должен войти в список (нет префикса mpcontrol_)
    (daily_dir / "other_file.txt").write_text("data")

    files = _list_backup_files(daily_dir)
    assert len(files) == 3
    kinds = {f.kind for f in files}
    assert kinds == {"db", "files", "full"}


def test_list_backup_files_respects_limit(tmp_path: Path):
    daily_dir = tmp_path / "backups" / "daily"
    daily_dir.mkdir(parents=True)
    for i in range(5):
        (daily_dir / f"mpcontrol_db_{i:02d}.dump").write_text("data")

    files = _list_backup_files(daily_dir, limit=3)
    assert len(files) == 3


def test_backup_file_dataclass():
    path = Path("/some/backups/daily/mpcontrol_db_test.dump")
    bf = BackupFile(
        path=path,
        kind="db",
        created_at=__import__("datetime").datetime(2026, 6, 10, 3, 0, 0),
        size_bytes=1024,
        integrity=None,
    )
    assert bf.kind == "db"
    assert bf.size_bytes == 1024
    assert bf.integrity is None
