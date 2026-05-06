#!/usr/bin/env bash
# Canonical exerciser of the blueprint via NVIDIA NeMo Agent Toolkit.
#
#   ./examples/nat_run.sh "Telehealth FAQ: how do I prepare?"
#
# Optional env:
#   WORKFLOW         path to workflow.yml (default: src/workflow.yml)
#   SSDB_RAG_URL     override for the retriever's uri (default: from workflow.yml)
#   NAT              path to the `nat` binary (default: `nat` on $PATH)
#   NVIDIA_API_KEY   passed through to the toolkit for the LLM NIM call
#
# Requires:
#   pip install nvidia-nat~=1.0
#   pip install nat-retriever-ssdb              # https://pypi.org/project/nat-retriever-ssdb/
#                                              # (use `-e ../nat-retriever-ssdb` when
#                                              #  developing the plug-in alongside)
#   the SSDB stack reachable at $SSDB_RAG_URL (default: http://ssdb-sql-rag:8080)
#   an LLM the toolkit can talk to (NIMs or your own llms: block in workflow.yml)
#
# References:
#   https://docs.nvidia.com/nemo/agent-toolkit/latest/get-started/quick-start.html
set -euo pipefail

ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )"/.. && pwd )"
WORKFLOW="${WORKFLOW:-$ROOT/src/workflow.yml}"
NAT="${NAT:-nat}"

if [[ $# -lt 1 ]]; then
  echo "usage: $0 \"<question>\" [extra nat run args...]" >&2
  exit 2
fi

if ! command -v "$NAT" >/dev/null 2>&1; then
  cat >&2 <<'EOF'
!! `nat` not found. Install the NeMo Agent Toolkit and the SSDB plug-in:

     pip install nvidia-nat~=1.0
     pip install nat-retriever-ssdb

   (For plug-in development, replace the second line with
    `pip install -e ../nat-retriever-ssdb`.)

   Then re-run.

EOF
  exit 3
fi

QUESTION="$1"; shift || true

EXTRA=()
if [[ -n "${SSDB_RAG_URL:-}" ]]; then
  EXTRA+=( --override "retrievers.default_kb.uri=$SSDB_RAG_URL" )
fi

echo "[nat_run] workflow : $WORKFLOW"
echo "[nat_run] retriever: ${SSDB_RAG_URL:-(from workflow.yml)}"
echo "[nat_run] question : $QUESTION"
echo "---"

"$NAT" run \
    --config_file="$WORKFLOW" \
    --input "$QUESTION" \
    "${EXTRA[@]}" \
    "$@"
