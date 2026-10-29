"""Reserve one free TCP port per Paradev workspace.

Parallel workspaces each start the insight UI. The app's default is
127.0.0.1:8765, so two Run buttons would collide. Setup claims a port,
records it under ~/.superset/port-allocations.json (the shared file named
in the Paradev port docs), and teardown releases it.

The claim is keyed by the workspace directory. A second claim for the same
directory returns the same port when that port is still free or is held by
this workspace's insight UI.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import signal
import socket
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

DEFAULT_START = 8765
DEFAULT_END = 8864
LABEL = "Insight UI"
LISTEN_STATE = "0A"


class PortAllocError(RuntimeError):
    """The port file could not be updated, or no usable port was left."""


def default_alloc_file() -> Path:
    return Path.home() / ".superset" / "port-allocations.json"


def claim(
    workspace: Path,
    alloc_file: Path,
    start: int = DEFAULT_START,
    end: int = DEFAULT_END,
) -> int:
    """Reserve a port for workspace and refresh its dev-port files."""
    workspace = workspace.resolve()
    _check_range(start, end)
    with _locked(alloc_file) as data:
        port = _select_port(data, workspace, start, end)
        data[str(workspace)] = port
        _persist(alloc_file, data)
    _write_workspace_port(workspace, port)
    return port


def release(workspace: Path, alloc_file: Path) -> None:
    """Drop workspace's reservation. Fails if its insight UI is still up."""
    workspace = workspace.resolve()
    with _locked(alloc_file) as data:
        key = str(workspace)
        port = data.get(key)
        if isinstance(port, int) and _owned_by_workspace(port, workspace):
            raise PortAllocError(
                f"Insight UI is still listening on {port}. "
                "Stop it before releasing the port."
            )
        data.pop(key, None)
        _persist(alloc_file, data)
    _remove_workspace_files(workspace)


def stop(workspace: Path, alloc_file: Path) -> None:
    """Stop this workspace's insight UI, if the recorded process is still it."""
    workspace = workspace.resolve()
    pids: set[int] = set()
    pidfile = _pid_file(workspace)
    recorded = _read_pid(pidfile)
    if recorded is not None and _is_our_server(recorded, workspace):
        pids.add(recorded)
    port = _read_dev_port(workspace)
    if port is None:
        port = _stored_port(workspace, alloc_file)
    if port is not None:
        for pid in _listener_pids(port):
            if _is_our_server(pid, workspace):
                pids.add(pid)
    for pid in pids:
        _terminate(pid)
    if port is not None and _owned_by_workspace(port, workspace):
        raise PortAllocError(f"Insight UI still listening on {port} after stop")
    pidfile.unlink(missing_ok=True)


def status(workspace: Path, alloc_file: Path) -> str:
    """Return ``running`` when this workspace's insight UI holds its port."""
    workspace = workspace.resolve()
    port = _read_dev_port(workspace)
    if port is None:
        port = _stored_port(workspace, alloc_file)
    if port is not None and _owned_by_workspace(port, workspace):
        return "running"
    return "free"


def _check_range(start: int, end: int) -> None:
    if start < 1 or end > 65535 or start > end:
        raise PortAllocError(f"invalid port range {start}-{end}")


def _select_port(data: dict[str, object], workspace: Path, start: int, end: int) -> int:
    key = str(workspace)
    current = data.get(key)
    if isinstance(current, int) and start <= current <= end and _keep(current, workspace):
        return current
    used = {
        value
        for other, value in data.items()
        if other != key and isinstance(value, int)
    }
    for port in range(start, end + 1):
        if port in used or not _port_is_free(port):
            continue
        return port
    raise PortAllocError(
        f"No free TCP port in {start}-{end} for {workspace}. "
        "Close a workspace or widen the range."
    )


def _keep(port: int, workspace: Path) -> bool:
    return _port_is_free(port) or _owned_by_workspace(port, workspace)


def _port_is_free(port: int) -> bool:
    """True when nothing is accepting TCP on 127.0.0.1:port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _owned_by_workspace(port: int, workspace: Path) -> bool:
    return any(_is_our_server(pid, workspace) for pid in _listener_pids(port))


def _is_our_server(pid: int, workspace: Path) -> bool:
    """True when pid is the insight UI started in this workspace."""
    if pid <= 1 or pid == os.getpid():
        return False
    proc = Path("/proc") / str(pid)
    try:
        cwd = Path(os.readlink(proc / "cwd")).resolve()
        cmdline = (proc / "cmdline").read_bytes().replace(b"\x00", b" ")
    except OSError:
        return False
    if cwd != workspace.resolve():
        return False
    text = cmdline.decode("utf-8", "replace")
    return "insights.ui" in text or "insights/ui.py" in text


def _listener_pids(port: int) -> list[int]:
    inodes = _listen_inodes(port)
    if not inodes:
        return []
    targets = {f"socket:[{inode}]" for inode in inodes}
    found: list[int] = []
    proc = Path("/proc")
    if not proc.is_dir():
        return []
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        fd_dir = entry / "fd"
        try:
            fds = list(fd_dir.iterdir())
        except OSError:
            continue
        for fd in fds:
            try:
                target = os.readlink(fd)
            except OSError:
                continue
            if target in targets:
                found.append(int(entry.name))
                break
    return found


def _listen_inodes(port: int) -> set[str]:
    hex_port = f"{port:04X}"
    inodes: set[str] = set()
    for net in (Path("/proc/net/tcp"), Path("/proc/net/tcp6")):
        try:
            lines = net.read_text(encoding="utf-8").splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            parts = line.split()
            if len(parts) < 10 or parts[3] != LISTEN_STATE:
                continue
            if parts[1].rsplit(":", 1)[-1].upper() != hex_port:
                continue
            inodes.add(parts[9])
    return inodes


def _terminate(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.1)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return


@contextmanager
def _locked(alloc_file: Path) -> Iterator[dict[str, object]]:
    alloc_file.parent.mkdir(parents=True, exist_ok=True)
    lock_path = alloc_file.with_name(alloc_file.name + ".lock")
    with lock_path.open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield _read_alloc(alloc_file)
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _read_alloc(alloc_file: Path) -> dict[str, object]:
    try:
        raw = alloc_file.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PortAllocError(f"{alloc_file} is not valid JSON") from exc
    if not isinstance(data, dict):
        raise PortAllocError(f"{alloc_file} must be a JSON object")
    return data


def _persist(alloc_file: Path, data: dict[str, object]) -> None:
    payload = json.dumps(data, indent=2) + "\n"
    tmp = alloc_file.with_name(f"{alloc_file.name}.tmp.{os.getpid()}")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, alloc_file)


def _write_workspace_port(workspace: Path, port: int) -> None:
    superset = workspace / ".superset"
    superset.mkdir(parents=True, exist_ok=True)
    _atomic_write(superset / "dev-port", f"{port}\n")
    mapping = {"ports": [{"port": port, "label": LABEL}]}
    _atomic_write(superset / "ports.json", json.dumps(mapping, indent=2) + "\n")


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _remove_workspace_files(workspace: Path) -> None:
    for name in ("dev-port", "ports.json", "dev-server.pid"):
        (workspace / ".superset" / name).unlink(missing_ok=True)


def _pid_file(workspace: Path) -> Path:
    return workspace / ".superset" / "dev-server.pid"


def _read_pid(path: Path) -> int | None:
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not raw.isdigit():
        return None
    return int(raw)


def _read_dev_port(workspace: Path) -> int | None:
    path = workspace / ".superset" / "dev-port"
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not raw.isdigit():
        return None
    return int(raw)


def _stored_port(workspace: Path, alloc_file: Path) -> int | None:
    with _locked(alloc_file) as data:
        port = data.get(str(workspace))
    if isinstance(port, int):
        return port
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("claim", "release", "stop", "status"))
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--alloc-file", type=Path, default=default_alloc_file())
    parser.add_argument("--start", type=int, default=DEFAULT_START)
    parser.add_argument("--end", type=int, default=DEFAULT_END)
    args = parser.parse_args(argv)
    try:
        if args.action == "claim":
            print(claim(args.workspace, args.alloc_file, args.start, args.end))
        elif args.action == "release":
            release(args.workspace, args.alloc_file)
        elif args.action == "stop":
            stop(args.workspace, args.alloc_file)
        else:
            print(status(args.workspace, args.alloc_file))
    except PortAllocError as exc:
        print(f"portalloc: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
