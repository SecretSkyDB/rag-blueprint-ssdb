# Cross-component smoke test

A 60-second walkthrough that wires `nat-retriever-ssdb` × this blueprint ×
an SSDB bridge together on a single laptop. **No NIM key, no Docker, no GPU.**

```
┌────────────────────────────┐    POST /api/v1/{ingest,retrieve}   ┌────────────────────────────────┐
│ ask_one.py / ingest_corpus │  ─────────────────────────────────► │ Bridge (one of):               │
│  ↓                         │                                     │  • mock_ssdb_bridge.py (here)  │
│ SSDBRetriever (PyPI)       │  ◄──────── top-k JSON ───────────── │  • ssdb-sql-rag (real, :8080)  │
└────────────────────────────┘                                     └────────────────────────────────┘
```

The same `_type: ssdb_retriever` block declared in
[`../../src/workflow.yml`](../../src/workflow.yml) is used by `ask_one.py`
(just instantiated directly, so we don't need the toolkit + an LLM NIM in
the loop). What's exercised:

* **Plug-in** —
  [`nat-retriever-ssdb`](https://pypi.org/project/nat-retriever-ssdb/)'s
  `SSDBRetriever`, calling `POST /api/v1/retrieve`.
* **Blueprint** — the `_type: ssdb_retriever` block from
  [`../../src/workflow.yml`](../../src/workflow.yml), loaded at runtime to
  prove the YAML and the plug-in agree on the schema.
* **Bridge contract** — `/api/v1/{health,ingest,retrieve}` against either
  the mock or the real `ssdb-sql-rag`; the two are byte-compatible.

## Run it

```bash
cd examples/cross_component_smoke
./run_demo.sh                 # default: mock bridge on :8765
```

What happens:

1. Creates `.venv-demo/` if missing and installs `nat-retriever-ssdb` (from
   PyPI) plus `flask`, `httpx`, `pyyaml`.
2. Starts the mock bridge on `:8765` (or attaches to a real one if
   `SSDB_BRIDGE_URL` is exported and reachable).
3. Ingests `../../data/healthcare_synthetic/*.{md,txt}` via
   `POST /api/v1/ingest`.
4. Runs `ask_one.py` for two queries via `POST /api/v1/retrieve`:
   * "What red flags should the chronic-care patient report?"
   * "Telehealth FAQ — how do I prepare?"
5. Prints the top-k passages with citations and scores.
6. Stops the mock bridge.

## Switch to the real `ssdb-sql-rag` service

Bring up the SSDB substrate, an embedder, and the new service, then point
the demo at `:8080`. The full recipe (with Docker compose) is
[`../../../docs/RUNBOOK_NVIDIA.md`](../../../docs/RUNBOOK_NVIDIA.md) Tier A.
The short version:

```bash
# 1. SSDB proxy + 3 share-Postgres + ssdb-sql-rag (one compose)
docker compose -f ../../deploy/compose/ssdb-overlay.yaml \
               -f ../../deploy/compose/laptop-overlay.yaml up -d

# 2. demo against the real service
./run_demo.sh real
```

To pin a different bridge URL explicitly:

```bash
SSDB_BRIDGE_URL=http://127.0.0.1:8080 ./run_demo.sh real
```

## Develop the plug-in alongside this demo

If you have a checkout of `nat-retriever-ssdb` next to the blueprint
(common during plug-in development), point the demo at it for an editable
install instead of the published wheel:

```bash
LOCAL_PLUGIN=../../../nat-retriever-ssdb ./run_demo.sh
```

## What this is not

This is a **plug-in × bridge** wiring smoke test. It does **not** exercise
the LLM, the agent loop, or the chat UI. For those:

* `../nat_run.sh` runs the full toolkit + LLM via `nat run`.
* `../fallback_ui/` is the laptop-tier chat UI (no NIMs required).
* The reference NVIDIA `rag-frontend` (port 8090) is the polished demo —
  see [`../../../docs/RUNBOOK_NVIDIA.md`](../../../docs/RUNBOOK_NVIDIA.md)
  Tier B.
