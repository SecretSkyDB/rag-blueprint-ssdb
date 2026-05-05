# Blueprint exercisers

Four ways to drive the workflow, easiest first. Pick by intent.

| Goal | Use |
|---|---|
| Smoke-test in CI without a UI | (1) `nat_run.sh` |
| Demo on a laptop, no NIMs, no NVIDIA key | (2) fallback UI + `laptop-overlay.yaml` |
| NVIDIA reviewer demo with the reference chat UI | (3) `rag-frontend` (upstream image, default in `docker-compose-rag-server.yaml`) |
| Probe `/api/v1/retrieve` raw, for debugging | `curl` |

## 1. `nat_run.sh` — toolkit CLI exerciser (canonical CI smoke test)

```bash
./examples/nat_run.sh "Telehealth FAQ: how do I prepare for the visit?"
```

Wraps `nat run --config_file=src/workflow.yml --input "..."`. The toolkit
loads the workflow, registers `_type: ssdb_retriever` via the `nat.plugins`
entry-point group (provided by the installed `nat-retriever-ssdb` package),
runs the ReAct agent loop, and prints the answer.

Requires:

* `pip install nvidia-nat~=1.0` and `pip install -e ../nat-retriever-ssdb`
  (editable install of the sibling repo; replaced by `pip install
  nat-retriever-ssdb` once public v0.1.0 ships at design-partner kickoff)
* the SSDB stack reachable at `http://ssdb-sql-rag:8080` (or set `SSDB_RAG_URL`
  to override the workflow's `uri`);
* an LLM the toolkit can call — either a NIM endpoint, NVIDIA-hosted via
  `NVIDIA_API_KEY`, or a local Ollama configured in your `workflow.yml`.

This is what `.github/workflows/ci.yml` runs on every push.

## 2. `fallback_ui/` — chat UI we control

A 150-line Flask + HTML app. It talks to the toolkit's HTTP runner
(`nat serve` on `:8000`) and renders streaming responses. Brought up by
the laptop overlay; see `RUNBOOK_NVIDIA.md` Tier A.

```bash
docker compose \
  -f deploy/compose/ssdb-overlay.yaml \
  -f deploy/compose/laptop-overlay.yaml \
  up -d
open http://localhost:8501
```

Use this when:

* you don't want to pull the full upstream `rag-frontend` image (e.g. air-gapped);
* you're demoing on a MacBook and don't want a `rag-server` container running;
* you want a brandable UI without forking NVIDIA's repo.

## 3. `rag-frontend` — NVIDIA's reference chat UI (upstream)

Default in `docker-compose-rag-server.yaml`. Pulls
`nvcr.io/nvidia/blueprint/rag-frontend:2.5.0`. Listens on host port `8090`.
This is the polished chat UI an NVIDIA reviewer expects to see.

```bash
docker compose \
  -f deploy/compose/docker-compose-rag-server.yaml \
  -f deploy/compose/docker-compose-ingestor-server.yaml \
  -f deploy/compose/ssdb-overlay.yaml \
  up -d
open http://localhost:8090
```

Requires `docker login nvcr.io` if you haven't already.

## 4. Raw `/api/v1/retrieve` probe

For debugging the SSDB tier independently of the toolkit:

```bash
curl -fsS -X POST http://localhost:8080/api/v1/retrieve \
    -H 'content-type: application/json' \
    -d '{"query":"telehealth visit preparation","collection":"nv_rag_documents","k":4}' \
  | jq .
```

Bypasses the toolkit, the agent loop, and the LLM — pure
embed-and-secret-shared-top-k.
