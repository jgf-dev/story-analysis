"""Small standard-library helpers for safe embedding exports."""

from __future__ import annotations

import os
import secrets
import shutil
import stat
import tempfile
from pathlib import Path


def require_environment(*names: str) -> tuple[str, ...]:
    """Return required environment values without exposing them in errors."""
    missing = [name for name in names if not os.environ.get(name)]
    if missing:
        joined = ", ".join(missing)
        raise ValueError(f"missing required environment variable(s): {joined}")
    return tuple(os.environ[name] for name in names)


def make_staging_directory(destination: str | Path) -> Path:
    """Create a private sibling directory for an export generation."""
    output_dir = Path(destination)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    recover_published_directory(output_dir)
    if output_dir.exists() and not output_dir.is_dir():
        raise NotADirectoryError(f"export destination is not a directory: {output_dir}")
    return Path(
        tempfile.mkdtemp(
            prefix=f".{output_dir.name}.staging-", dir=output_dir.parent
        )
    )


def _default_directory_mode(parent: Path) -> int:
    """Read the mode that a normal directory gets under the current umask."""
    for _ in range(10):
        probe = parent / f".export-mode-{secrets.token_hex(8)}"
        try:
            os.mkdir(probe, 0o777)
        except FileExistsError:
            continue
        try:
            return stat.S_IMODE(probe.stat().st_mode)
        finally:
            probe.rmdir()
    raise FileExistsError(f"could not create a permission probe in {parent}")


def publish_directory(staging: str | Path, destination: str | Path) -> None:
    """Replace an export directory with a completed staged generation."""
    staging_dir = Path(staging)
    output_dir = Path(destination)
    if staging_dir.parent != output_dir.parent:
        raise ValueError("staging and destination must share a parent directory")
    if not staging_dir.is_dir():
        raise FileNotFoundError(f"staging directory does not exist: {staging_dir}")

    if output_dir.exists() and not output_dir.is_dir():
        raise NotADirectoryError(f"export destination is not a directory: {output_dir}")
    mode = (
        stat.S_IMODE(output_dir.stat().st_mode)
        if output_dir.exists()
        else _default_directory_mode(output_dir.parent)
    )
    staging_dir.chmod(mode)

    backup_dir: Path | None = None
    try:
        if output_dir.exists():
            backup_dir = Path(
                tempfile.mkdtemp(
                    prefix=f".{output_dir.name}.backup-", dir=output_dir.parent
                )
            )
            backup_dir.rmdir()
            os.replace(output_dir, backup_dir)
        os.replace(staging_dir, output_dir)
    except BaseException:
        if (
            backup_dir is not None
            and backup_dir.exists()
            and not output_dir.exists()
        ):
            os.replace(backup_dir, output_dir)
        raise

    if backup_dir is not None:
        try:
            backup_dir.chmod(backup_dir.stat().st_mode | 0o700)
        except OSError:
            pass
        shutil.rmtree(backup_dir, ignore_errors=True)


def recover_published_directory(destination: str | Path) -> bool:
    """Restore the newest preserved export if promotion was interrupted."""
    output_dir = Path(destination)
    if output_dir.exists():
        return False
    def backup_order(path: Path) -> tuple[int, str]:
        try:
            modified = path.stat().st_mtime_ns
        except FileNotFoundError:
            modified = 0
        return modified, path.name

    backups = sorted(
        output_dir.parent.glob(f".{output_dir.name}.backup-*"),
        key=backup_order,
        reverse=True,
    )
    for backup_dir in backups:
        try:
            if not backup_dir.is_dir():
                continue
            os.replace(backup_dir, output_dir)
        except FileNotFoundError:
            if output_dir.is_dir():
                return False
            continue
        except OSError:
            if output_dir.is_dir():
                return False
            raise
        return True
    return False


def discard_staging_directory(staging: str | Path) -> None:
    """Remove an unpublished export generation, if it still exists."""
    staging_dir = Path(staging)
    try:
        staging_dir.chmod(0o700)
    except OSError:
        pass
    shutil.rmtree(staging_dir, ignore_errors=True)
