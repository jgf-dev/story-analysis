#!/usr/bin/env bash
# Start the insight UI on this workspace's reserved port.
#
# Paradev runs this from the Run button. It is not part of setup, so
# creating a workspace does not occupy the port until someone starts the UI.
# The port was reserved by setup; claim is run again so a manual Run still
# works if setup was skipped, and so a port stolen since setup is replaced.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$ROOT"

# The insight UI reads PIPER_VOICE from the environment. Copying .env into
# the worktree does not load it; export the assignments here. Values are
# not printed.
load_dotenv() {
  local file="${1:-$ROOT/.env}"
  [[ -f "$file" ]] || return 0
  set -a
  # shellcheck disable=SC1090
  source "$file"
  set +a
}

main() {
  local python="$ROOT/.venv/bin/python"
  if [[ ! -x "$python" ]]; then
    echo "Missing $python. Run ./.superset/setup.sh first." >&2
    exit 1
  fi

  local port state
  port="$(python3 "$ROOT/.superset/portalloc.py" claim --workspace "$ROOT")"
  state="$(python3 "$ROOT/.superset/portalloc.py" status --workspace "$ROOT")"
  if [[ "$state" == "running" ]]; then
    echo "Insight UI is already running at http://127.0.0.1:${port}" >&2
    exit 1
  fi

  load_dotenv "$ROOT/.env"
  echo "Insight UI → http://127.0.0.1:${port}"
  # exec keeps this pid, so the file still names the server after the shell
  # is replaced. Teardown uses it only if the process is this workspace's UI.
  echo $$ > "$ROOT/.superset/dev-server.pid"
  exec "$python" -m insights.ui \
    --host 127.0.0.1 \
    --port "$port" \
    --db "${INSIGHT_DB:-data/catalog.sqlite}" \
    --out-dir "${INSIGHT_OUT:-insights_output}"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi

