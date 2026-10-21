#!/usr/bin/env bash
#
# Wrapper for the full-corpus ingestion run.
#
# Why this exists: `python -m insights.corpus_prep ... | tee log` reports the
# exit status of `tee`, not of Python. A run that failed every row therefore
# looks successful in a pipeline. `set -o pipefail` makes the pipeline return
# the first non-zero status, so a failed ingest cannot be mistaken for a good
# one. The script additionally refuses to report success unless rows were
# actually processed.
#
# Usage:
#   scripts/ingest.sh --csv data/stories_clean.csv --db data/catalog.sqlite
#   scripts/ingest.sh --csv ... --db ... --workers 4 --limit 5000
#
# All arguments are passed straight through to insights.corpus_prep.

set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PYTHON="${PYTHON:-$REPO_ROOT/.venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
    PYTHON="$(command -v python3)"
fi

LOG_DIR="${LOG_DIR:-$REPO_ROOT/data/logs}"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/ingest-$(date +%Y%m%d-%H%M%S).log"

echo "[ingest.sh] python : $PYTHON"
echo "[ingest.sh] log    : $LOG_FILE"
echo "[ingest.sh] args   : $*"

# `tee` keeps console output while preserving a full log. pipefail (set above)
# is what makes the status captured below reflect Python rather than tee.
set +e
"$PYTHON" -m insights.corpus_prep "$@" 2>&1 | tee "$LOG_FILE"
status="${PIPESTATUS[0]}"
set -e

if [[ "$status" -ne 0 ]]; then
    echo "[ingest.sh] FAILED (exit $status) — see $LOG_FILE" >&2
    exit "$status"
fi

# Belt and braces: a zero exit with zero processed rows is not a success.
RESULT_FILE=""
expect_db=""
for arg in "$@"; do
    if [[ -n "$expect_db" ]]; then
        RESULT_FILE="$arg.ingest_result.json"
        break
    fi
    if [[ "$arg" == "--db" ]]; then
        expect_db="1"
    fi
done

if [[ -n "$RESULT_FILE" && -f "$RESULT_FILE" ]]; then
    read -r processed errors < <("$PYTHON" - "$RESULT_FILE" <<'PY'
import json, sys
r = json.load(open(sys.argv[1]))
print(r["processed"], r["total_errors"])
PY
)
    echo "[ingest.sh] processed=$processed total_errors=$errors"
    if [[ "$processed" -eq 0 ]]; then
        echo "[ingest.sh] FAILED: the run exited 0 but processed no rows" >&2
        exit 1
    fi
fi

echo "[ingest.sh] OK — log at $LOG_FILE"
