#!/usr/bin/env bash
# Paradev workspace setup for story-analysis.
#
# Installs the locked Python environment, copies gitignored env files from
# the root checkout ($SUPERSET_ROOT_PATH), and reserves a free insight-UI
# port so parallel workspaces do not all bind 127.0.0.1:8765.
#
# data/, *.sqlite, and .venv are not copied. The catalogue is large and
# internal; the virtualenv is recreated by uv so its paths match this
# worktree.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"

copy_env_files() {
  local dest="${1:-$ROOT}"
  local root="${SUPERSET_ROOT_PATH:-}"
  if [[ -z "$root" ]]; then
    echo "SUPERSET_ROOT_PATH is unset; skipping env copy."
    return 0
  fi
  if [[ ! -d "$root" ]]; then
    echo "SUPERSET_ROOT_PATH is not a directory: $root" >&2
    return 1
  fi
  root="$(cd "$root" && pwd -P)"
  dest="$(cd "$dest" && pwd -P)"
  if [[ "$root" == "$dest" ]]; then
    echo "Workspace is the root checkout; env files stay where they are."
    return 0
  fi

  local copied=0
  local src name
  shopt -s nullglob
  for src in "$root"/.env "$root"/.env.*; do
    [[ -f "$src" ]] || continue
    name="$(basename "$src")"
    case "$name" in
      *.example|*.sample|*.template) continue ;;
    esac
    if [[ -e "$dest/$name" ]]; then
      echo "Keeping existing $name"
      continue
    fi
    cp -p "$src" "$dest/$name"
    echo "Copied $name from $root"
    copied=$((copied + 1))
  done
  shopt -u nullglob
  if [[ "$copied" -eq 0 ]]; then
    echo "No env files to copy from $root"
  fi
}

install_dependencies() {
  if ! command -v uv >/dev/null 2>&1; then
    echo "uv is not on PATH. Install it from https://docs.astral.sh/uv/ and re-run setup." >&2
    return 1
  fi
  echo "Installing dependencies with uv sync --frozen --all-groups"
  uv sync --frozen --all-groups
}

reserve_port() {
  local port
  port="$(python3 "$ROOT/.superset/portalloc.py" claim --workspace "$ROOT")"
  echo "Reserved insight UI port ${port} (http://127.0.0.1:${port})"
}

main() {
  cd "$ROOT"
  copy_env_files "$ROOT"
  install_dependencies
  reserve_port
  echo "Setup complete."
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
