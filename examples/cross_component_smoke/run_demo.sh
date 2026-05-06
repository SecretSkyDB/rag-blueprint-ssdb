#!/usr/bin/env bash
# End-to-end smoke test: nat-retriever-ssdb (PyPI) -> SSDB bridge.
#
#   ./run_demo.sh                # default: mock bridge on :8765 (no Docker required)
#   ./run_demo.sh real           # use the real ssdb-sql-rag service on :8080
#   SSDB_BRIDGE_URL=http://host:port ./run_demo.sh   # pin a specific bridge
#
# Optional env:
#   LOCAL_PLUGIN=/path/to/nat-retriever-ssdb   # editable install instead of PyPI
#                                              # (useful when developing the plug-in)
#   MOCK_PORT=8765                              # change the mock port
#
# What it does:
#   1. Creates a venv if needed and installs nat-retriever-ssdb from PyPI
#      (plus flask, httpx, pyyaml).
#   2. Starts the in-process mock bridge on :$MOCK_PORT (or attaches to a
#      real one if SSDB_BRIDGE_URL is set or `real` is passed).
#   3. Ingests data/healthcare_synthetic/*.{md,txt} via POST /api/v1/ingest.
#   4. Runs ask_one.py for two known-answer queries, printing top-k passages
#      with citations and scores.
#   5. Stops the mock bridge on exit.
set -euo pipefail

HERE="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
ROOT="$( cd "$HERE/../.." && pwd )"
VENV="$HERE/.venv-demo"
MOCK_PORT="${MOCK_PORT:-8765}"

# ---------- mode selection (default: mock) -----------------------------------
MODE="${1:-mock}"
case "$MODE" in
  mock|real) ;;
  *) echo "!! usage: $0 [mock|real]" >&2; exit 2 ;;
esac

# Default bridge URL depends on mode. The canonical service (ssdb-sql-rag)
# listens on :8080.
if [[ -z "${SSDB_BRIDGE_URL:-}" ]]; then
  if [[ "$MODE" == "real" ]]; then
    SSDB_BRIDGE_URL="http://127.0.0.1:8080"
  else
    SSDB_BRIDGE_URL="http://127.0.0.1:$MOCK_PORT"
  fi
fi
BRIDGE="$SSDB_BRIDGE_URL"

cd "$HERE"

# ---------- 1. venv + deps ---------------------------------------------------
if [[ ! -d "$VENV" ]]; then
  python3 -m venv "$VENV"
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"
python3 -m pip install -q --upgrade pip
if [[ -n "${LOCAL_PLUGIN:-}" ]]; then
  echo "[demo] installing nat-retriever-ssdb editable from $LOCAL_PLUGIN"
  python3 -m pip install -q -e "$LOCAL_PLUGIN" flask httpx pyyaml
else
  python3 -m pip install -q nat-retriever-ssdb flask httpx pyyaml
fi

# ---------- 2. mock-bridge mode: start the in-process Flask mock -------------
MOCK_PID=""
cleanup() {
  if [[ -n "$MOCK_PID" ]] && kill -0 "$MOCK_PID" 2>/dev/null; then
    kill "$MOCK_PID" 2>/dev/null || true
    wait "$MOCK_PID" 2>/dev/null || true
    echo "[demo] mock bridge stopped (pid=$MOCK_PID)"
  fi
}
trap cleanup EXIT

if [[ "$MODE" == "mock" && "$BRIDGE" == "http://127.0.0.1:$MOCK_PORT" ]]; then
  echo "[demo] starting mock SSDB bridge on :$MOCK_PORT"
  MOCK_HOST=127.0.0.1 MOCK_PORT="$MOCK_PORT" \
    python3 mock_ssdb_bridge.py >"$HERE/mock_bridge.log" 2>&1 &
  MOCK_PID=$!
  for _ in $(seq 1 30); do
    if curl -fsS "$BRIDGE/api/v1/health" >/dev/null 2>&1; then break; fi
    sleep 0.2
  done
  curl -fsS "$BRIDGE/api/v1/health" >/dev/null
  echo "[demo] mock bridge ready (pid=$MOCK_PID)"
else
  echo "[demo] using $MODE bridge: $BRIDGE"
  if ! curl -fsS "$BRIDGE/api/v1/health" >/dev/null 2>&1 \
     && ! curl -fsS "$BRIDGE/api/health"     >/dev/null 2>&1; then
    cat <<EOF >&2
!! bridge $BRIDGE is not reachable on /api/v1/health or /api/health.

   real-bridge mode expects the ssdb-sql-rag service running on :8080.
   See ../../docs/RUNBOOK_NVIDIA.md (Tier A) for how to bring it up
   via deploy/compose/ssdb-overlay.yaml.
EOF
    exit 3
  fi
fi

# ---------- 3. ingest + ask --------------------------------------------------
python3 ingest_corpus.py --bridge "$BRIDGE" --corpus "$ROOT/data/healthcare_synthetic"
python3 ask_one.py       --bridge "$BRIDGE"

echo "[demo] done."
