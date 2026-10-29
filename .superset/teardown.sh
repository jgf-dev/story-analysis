#!/usr/bin/env bash
# Paradev workspace teardown for story-analysis.
#
# Setup does not leave a long-running process. The Run button does: it
# starts the insight UI on the port reserved for this workspace. Deleting
# the workspace runs this script, which stops that process (only when the
# process is this workspace's insight UI) and releases the port so another
# workspace can claim it.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"

main() {
  cd "$ROOT"
  python3 "$ROOT/.superset/portalloc.py" stop --workspace "$ROOT"
  python3 "$ROOT/.superset/portalloc.py" release --workspace "$ROOT"
  echo "Teardown complete."
}

main "$@"
