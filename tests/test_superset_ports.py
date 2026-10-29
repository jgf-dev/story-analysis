"""Paradev port reservation and env copy.

Parallel workspaces would otherwise all bind the insight UI to 8765.
"""

from __future__ import annotations

import importlib.util
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PORTALLOC_PATH = ROOT / ".superset" / "portalloc.py"
SETUP = ROOT / ".superset" / "setup.sh"
RUN = ROOT / ".superset" / "run.sh"

spec = importlib.util.spec_from_file_location("portalloc", PORTALLOC_PATH)
assert spec is not None and spec.loader is not None
portalloc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(portalloc)


def _claim(workspace: Path, alloc: Path, start: int, end: int) -> int:
    return portalloc.claim(workspace, alloc, start, end)


def _window(count: int = 4) -> tuple[int, int]:
    """A run of free ports so a busy 8766 on this machine does not matter."""
    start = 18765
    while start < 60000:
        if all(portalloc._port_is_free(port) for port in range(start, start + count)):
            return start, start + count - 1
        start += count
    raise AssertionError("no free port window")


def _hold(workspace: Path, port: int, *, ours: bool) -> subprocess.Popen[bytes]:
    """Bind port until killed. ours=True marks the process as the insight UI."""
    code = (
        "import socket, sys, time\n"
        "sock = socket.socket()\n"
        "sock.bind(('127.0.0.1', int(sys.argv[1])))\n"
        "sock.listen(1)\n"
        "time.sleep(60)\n"
    )
    argv = [sys.executable, "-c", code, str(port)]
    if ours:
        argv.append("insights.ui")
    proc = subprocess.Popen(argv, cwd=workspace)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                return proc
        time.sleep(0.05)
    proc.kill()
    proc.wait(timeout=5)
    raise AssertionError(f"{port} was never bound")


def test_two_workspaces_get_different_ports(tmp_path: Path) -> None:
    alloc = tmp_path / "alloc.json"
    first = tmp_path / "one"
    second = tmp_path / "two"
    first.mkdir()
    second.mkdir()
    start, end = _window()
    assert _claim(first, alloc, start, end) == start
    assert _claim(second, alloc, start, end) == start + 1
    assert _claim(first, alloc, start, end) == start


def test_bound_port_is_skipped(tmp_path: Path) -> None:
    alloc = tmp_path / "alloc.json"
    workspace = tmp_path / "ws"
    workspace.mkdir()
    start, end = _window()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", start))
        sock.listen(1)
        assert _claim(workspace, alloc, start, end) == start + 1


def test_foreign_listener_on_reserved_port_moves_the_workspace(tmp_path: Path) -> None:
    alloc = tmp_path / "alloc.json"
    workspace = tmp_path / "ws"
    workspace.mkdir()
    start, end = _window()
    assert _claim(workspace, alloc, start, end) == start
    holder = _hold(tmp_path, start, ours=False)
    try:
        assert _claim(workspace, alloc, start, end) == start + 1
    finally:
        holder.kill()
        holder.wait(timeout=5)


def test_our_server_keeps_its_port(tmp_path: Path) -> None:
    alloc = tmp_path / "alloc.json"
    workspace = tmp_path / "ws"
    workspace.mkdir()
    start, end = _window()
    assert _claim(workspace, alloc, start, end) == start
    holder = _hold(workspace, start, ours=True)
    try:
        assert _claim(workspace, alloc, start, end) == start
        assert portalloc.status(workspace, alloc) == "running"
    finally:
        holder.kill()
        holder.wait(timeout=5)


def test_release_refuses_while_our_server_listens_then_stop_frees_it(tmp_path: Path) -> None:
    alloc = tmp_path / "alloc.json"
    workspace = tmp_path / "ws"
    workspace.mkdir()
    start, end = _window()
    assert _claim(workspace, alloc, start, end) == start
    holder = _hold(workspace, start, ours=True)
    try:
        with pytest.raises(portalloc.PortAllocError):
            portalloc.release(workspace, alloc)
        stored = json.loads(alloc.read_text(encoding="utf-8"))
        assert stored[str(workspace.resolve())] == start
        portalloc.stop(workspace, alloc)
        holder.wait(timeout=5)
        portalloc.release(workspace, alloc)
        assert str(workspace.resolve()) not in json.loads(alloc.read_text(encoding="utf-8"))
        other = tmp_path / "other"
        other.mkdir()
        assert _claim(other, alloc, start, end) == start
    finally:
        if holder.poll() is None:
            holder.kill()
            holder.wait(timeout=5)


def test_concurrent_claims_are_unique(tmp_path: Path) -> None:
    alloc = tmp_path / "alloc.json"
    workspaces = []
    for index in range(6):
        workspace = tmp_path / f"w{index}"
        workspace.mkdir()
        workspaces.append(workspace)
    procs = [
        subprocess.Popen(
            [
                sys.executable,
                str(PORTALLOC_PATH),
                "claim",
                "--workspace",
                str(workspace),
                "--alloc-file",
                str(alloc),
                "--start",
                "8765",
                "--end",
                "8774",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for workspace in workspaces
    ]
    ports = []
    for proc in procs:
        out, err = proc.communicate(timeout=30)
        assert proc.returncode == 0, err
        ports.append(int(out.strip()))
    assert len(set(ports)) == len(ports)


def test_setup_copies_env_files_and_skips_examples(tmp_path: Path) -> None:
    root = tmp_path / "root"
    dest = tmp_path / "worktree"
    root.mkdir()
    dest.mkdir()
    (root / ".env").write_text("PIPER_VOICE=test\n", encoding="utf-8")
    (root / ".env.local").write_text("LOCAL=1\n", encoding="utf-8")
    (root / ".env.example").write_text("SHOULD_NOT_COPY=1\n", encoding="utf-8")
    (dest / ".env.local").write_text("KEEP=1\n", encoding="utf-8")

    env = os.environ.copy()
    env["SUPERSET_ROOT_PATH"] = str(root)
    subprocess.run(
        ["bash", "-c", f'source "{SETUP}"; copy_env_files "{dest}"'],
        check=True,
        env=env,
        cwd=dest,
    )

    assert (dest / ".env").read_text(encoding="utf-8") == "PIPER_VOICE=test\n"
    assert (dest / ".env.local").read_text(encoding="utf-8") == "KEEP=1\n"
    assert not (dest / ".env.example").exists()


def test_setup_skips_copy_when_workspace_is_the_root(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["SUPERSET_ROOT_PATH"] = str(tmp_path)
    completed = subprocess.run(
        ["bash", "-c", f'source "{SETUP}"; copy_env_files "{tmp_path}"'],
        check=True,
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert "root checkout" in completed.stdout


def test_run_exports_dotenv_without_printing_values(tmp_path: Path) -> None:
    envfile = tmp_path / "sample.env"
    envfile.write_text("PIPER_VOICE=voice-from-file\n# comment\n\n", encoding="utf-8")
    completed = subprocess.run(
        [
            "bash",
            "-c",
            f'source "{RUN}"; load_dotenv "{envfile}"; printf "%s" "$PIPER_VOICE"',
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert completed.stdout == "voice-from-file"
    assert "voice-from-file" not in completed.stderr


def test_config_wires_the_three_scripts() -> None:
    config = json.loads((ROOT / ".superset" / "config.json").read_text(encoding="utf-8"))
    assert config["setup"] == ["./.superset/setup.sh"]
    assert config["teardown"] == ["./.superset/teardown.sh"]
    assert config["run"] == ["./.superset/run.sh"]


def test_stop_is_a_no_op_when_nothing_is_running(tmp_path: Path) -> None:
    alloc = tmp_path / "alloc.json"
    workspace = tmp_path / "ws"
    workspace.mkdir()
    portalloc.stop(workspace, alloc)
    assert portalloc.status(workspace, alloc) == "free"
