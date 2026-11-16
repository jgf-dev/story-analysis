"""Tests for embedding export staging and configuration helpers."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from embedding import export_utils
from embedding.export_utils import (
    make_staging_directory,
    publish_directory,
    recover_published_directory,
    require_environment,
)


def test_require_environment_names_missing_settings_without_values(monkeypatch):
    monkeypatch.delenv("ES_URL", raising=False)
    monkeypatch.delenv("ES_API_KEY", raising=False)

    with pytest.raises(ValueError, match="ES_URL, ES_API_KEY"):
        require_environment("ES_URL", "ES_API_KEY")


def test_publish_directory_replaces_previous_complete_export(tmp_path):
    output = tmp_path / "chunks"
    output.mkdir()
    (output / "old.parquet").write_text("old", encoding="utf-8")
    staging = make_staging_directory(output)
    (staging / "new.parquet").write_text("new", encoding="utf-8")

    publish_directory(staging, output)

    assert not (output / "old.parquet").exists()
    assert (output / "new.parquet").read_text(encoding="utf-8") == "new"
    assert not staging.exists()


def test_staging_stays_writable_and_publish_preserves_export_permissions(tmp_path):
    output = tmp_path / "chunks"
    output.mkdir(mode=0o550)
    output.chmod(0o550)

    staging = make_staging_directory(output)
    assert staging.stat().st_mode & 0o777 == 0o700
    (staging / "new.parquet").write_text("new", encoding="utf-8")

    publish_directory(staging, output)

    assert output.stat().st_mode & 0o777 == 0o550
    assert (output / "new.parquet").read_text(encoding="utf-8") == "new"


def test_recover_published_directory_restores_interrupted_export(tmp_path):
    output = tmp_path / "chunks"
    backup = tmp_path / ".chunks.backup-interrupted"
    backup.mkdir()
    (backup / "old.parquet").write_text("old", encoding="utf-8")

    assert recover_published_directory(output)

    assert (output / "old.parquet").read_text(encoding="utf-8") == "old"
    assert not backup.exists()
    assert not recover_published_directory(output)


def test_recover_published_directory_handles_backup_removed_during_scan(
    tmp_path, monkeypatch
):
    output = tmp_path / "chunks"
    backup = tmp_path / ".chunks.backup-interrupted"
    backup.mkdir()
    (backup / "old.parquet").write_text("old", encoding="utf-8")
    real_stat = Path.stat
    real_replace = os.replace
    moved = False

    def restore_during_backup_stat(path, *args, **kwargs):
        nonlocal moved
        if path == backup and not moved:
            moved = True
            real_replace(backup, output)
            raise FileNotFoundError("another caller restored the backup")
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", restore_during_backup_stat)

    assert not recover_published_directory(output)
    assert (output / "old.parquet").read_text(encoding="utf-8") == "old"


def test_recover_published_directory_handles_concurrent_restoration(
    tmp_path, monkeypatch
):
    output = tmp_path / "chunks"
    backup = tmp_path / ".chunks.backup-interrupted"
    backup.mkdir()
    (backup / "old.parquet").write_text("old", encoding="utf-8")
    real_replace = os.replace

    def restore_in_another_caller(source, destination):
        real_replace(source, destination)
        raise FileNotFoundError("another caller already restored the backup")

    monkeypatch.setattr(export_utils.os, "replace", restore_in_another_caller)

    assert not recover_published_directory(output)
    assert (output / "old.parquet").read_text(encoding="utf-8") == "old"


def test_first_publish_respects_process_umask(tmp_path):
    output = tmp_path / "chunks"
    output.parent.chmod(0o777)
    staging = make_staging_directory(output)
    (staging / "new.parquet").write_text("new", encoding="utf-8")
    previous_umask = os.umask(0o027)
    try:
        publish_directory(staging, output)
    finally:
        os.umask(previous_umask)

    assert output.stat().st_mode & 0o777 == 0o750


def test_publish_directory_restores_previous_export_if_promotion_fails(
    tmp_path, monkeypatch
):
    output = tmp_path / "chunks"
    output.mkdir()
    (output / "old.parquet").write_text("old", encoding="utf-8")
    staging = make_staging_directory(output)
    (staging / "new.parquet").write_text("new", encoding="utf-8")
    real_replace = os.replace

    def fail_staging_promotion(source, destination):
        if Path(source) == staging and Path(destination) == output:
            raise OSError("simulated promotion failure")
        real_replace(source, destination)

    monkeypatch.setattr(export_utils.os, "replace", fail_staging_promotion)

    with pytest.raises(OSError, match="simulated promotion failure"):
        publish_directory(staging, output)

    assert (output / "old.parquet").read_text(encoding="utf-8") == "old"
    assert (staging / "new.parquet").read_text(encoding="utf-8") == "new"
