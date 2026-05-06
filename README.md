# rag-blueprint-ssdb

**An overlay for [`NVIDIA-AI-Blueprints/rag`](https://github.com/NVIDIA-AI-Blueprints/rag)
v2.5.0 that swaps Milvus for SecretSkyDB (SSDB).**

The chat UI, the agent loop, the NIMs, the reranker, the LLM call, the
ingestion pipeline, and the OTel/eval scaffolding are all unchanged. The
only architectural difference is the vector store.

* **What this is:** the design-partner integration with NVIDIA. White
  paper: [`docs/whitepaper-nvidia.md`](../../docs/whitepaper-nvidia.md).
  Ten-minute reviewer recipe: [`docs/RUNBOOK_NVIDIA.md`](../../docs/RUNBOOK_NVIDIA.md).
* **What changes vs. upstream:** two env vars
  (`APP_VECTORSTORE_NAME=ssdb`, `APP_VECTORSTORE_URL=http://ssdb-sql-rag:8080`),
  one `_type: ssdb_retriever` block in `workflow.yml`, and one extra
  Docker Compose overlay (`ssdb-overlay.yaml`).
* **License:** Apache-2.0 (matches upstream).

---

## End-to-end chain

```
                                 ┌────────────────────┐
                                 │   rag-frontend     │  upstream image
                                 │  (NVIDIA UI :8090) │  rag-frontend:2.5.0
                                 └─────────┬──────────┘
                                           │ REST
                                           ▼
                ┌──────────────────┐   ┌──────────────────┐
                │ ingestor-server  │   │   rag-server     │  upstream images
                │ :8082            │   │   :8081          │  v2.5.0
                └────────┬─────────┘   └────────┬─────────┘
                         │ APP_VECTORSTORE_URL  │ APP_VECTORSTORE_URL
                         │                      │
                         │  POST /api/v1/...    │
                         │  via                 │
                         │  nat-retriever-ssdb  │  PyPI plug-in
                         │  (toolkit plug-in)   │  v0.2.1
                         ▼                      ▼
                       ┌────────────────────────────────┐
                       │       ssdb-sql-rag :8080       │  this repo
                       │    /api/v1/{health,setup,      │  ssdb/sql/services/rag/
                       │     ingest,retrieve}           │
                       │           NO LLM               │
                       └──────────────┬─────────────────┘
                                      │ Postgres wire
                                      ▼
                              ┌──────────────┐
                              │  ssdb-proxy  │  Lagrange reconstruction
                              │   :55432     │
                              └──┬────┬────┬─┘
                                 │    │    │
                       ┌─────────┴┐ ┌─┴──┐ ┌┴────────┐
                       │ share-1  │ │ -2 │ │ share-3 │
                       │ Postgres │ │    │ │         │
                       │ +ssdbpg  │ │    │ │         │   3 separate cloud
                       │ vector   │ │    │ │         │   accounts/countries/
                       └──────────┘ └────┘ └─────────┘   clearance levels
```

The four layers each do one job:

| Layer | Job | Code |
|---|---|---|
| Chat UI | take a question, render an answer | `rag-frontend` (upstream) — or `examples/fallback_ui/` for laptop |
| Toolkit + Blueprint | wire retriever × LLM × reranker | `src/workflow.yml` + the two `docker-compose-*-server.yaml` files |
| Plug-in | speak `/api/v1/retrieve` (toolkit-side) | [`nat-retriever-ssdb`](https://pypi.org/project/nat-retriever-ssdb/) |
| Service | embed text → top-k over secret-shared vectors | `ssdb/sql/services/rag/` |
| Substrate | store ciphertext shares, do homomorphic dot product | `ssdb/sql/src/` + 3 share-Postgres |

---

## Quick start (the green-field-engineer path)

> Three Docker tiers; full step-by-step is
> [`docs/RUNBOOK_NVIDIA.md`](../../docs/RUNBOOK_NVIDIA.md). For an even
> shorter "is anything wired up?" smoke test that needs neither Docker
> nor NIMs, see [`examples/cross_component_smoke/`](examples/cross_component_smoke/) — runs in ~60 s.

### Tier A — laptop only (~10 min, no GPU, no NVIDIA key)

```bash
brew install ollama && ollama pull mxbai-embed-large
cp deploy/compose/.env.example deploy/compose/.env       # edit SSDB_SHARE_PWD
docker compose \
  -f deploy/compose/ssdb-overlay.yaml \
  -f deploy/compose/laptop-overlay.yaml \
  up -d --build
open http://localhost:8501                               # fallback chat UI
```

### Tier B — full stack with NVIDIA-hosted NIMs (~25 min)

```bash
# .env: NVIDIA_API_KEY=<your build.nvidia.com key>
docker compose \
  -f deploy/compose/docker-compose-rag-server.yaml \
  -f deploy/compose/docker-compose-ingestor-server.yaml \
  -f deploy/compose/ssdb-overlay.yaml \
  up -d --build
# ingest a few docs through NVIDIA's ingestor REST API
curl -X POST http://localhost:8082/v1/documents \
    -F "files=@data/healthcare_synthetic/health_synthetic_01_telehealth_faq.md" \
    -F "collection_name=nv_rag_documents"
open http://localhost:8090                               # NVIDIA's reference UI
```

### Tier D — toolkit CLI (no UI, for CI)

```bash
pip install nvidia-nat~=1.0
pip install nat-retriever-ssdb              # https://pypi.org/project/nat-retriever-ssdb/
SSDB_RAG_URL=http://localhost:8080 \
  ./examples/nat_run.sh "Telehealth FAQ: how do I prepare?"
```

> Plug-in developers can substitute the second line with
> `pip install -e ../nat-retriever-ssdb` to get an editable install of a
> sibling checkout.

`nat run --config_file=src/workflow.yml --input "..."` is the toolkit's
own way to drive a workflow.

---

## Two-tier variant (Milvus *and* SSDB side by side)

`src/workflow.two_tier.yml` exposes both `milvus_retriever` (public corpus)
and `ssdb_retriever` (regulated/PHI corpus) to one ReAct agent. The agent
picks the right tool from the descriptions. Useful for customers who
already have Milvus for their public KB and want to add SSDB only for the
PHI subset.

---

## What changed vs. upstream

We track this in [`UPSTREAM.md`](UPSTREAM.md). Summary:

* **Compose:** Milvus services removed; `deploy/compose/ssdb-overlay.yaml`
  adds the proxy + 3 shareholders + `ssdb-sql-rag`. The two upstream
  compose files (`docker-compose-rag-server.yaml`,
  `docker-compose-ingestor-server.yaml`) keep their NVIDIA-shipped service
  names + ports verbatim; we only override the two `APP_VECTORSTORE_*`
  env vars.
* **Workflow:** one `_type: ssdb_retriever` block.
* **Requirements:** `+ nat-retriever-ssdb` (from PyPI:
  <https://pypi.org/project/nat-retriever-ssdb/>).
* **Examples:** `examples/cross_component_smoke/` (no-Docker plug-in smoke
  test), `examples/nat_run.sh` (toolkit CLI exerciser), `examples/fallback_ui/`
  (a chat UI we control for the laptop tier).

Everything else inherits unchanged. Monthly rebases against upstream
v2.6, v2.7, ... should be trivial.

---

## Repository

* This source: lives in the SSDB private mono-repo today as
  `nemo_trunk/blueprint/`. Will be split into the public Apache-2.0
  repo `SecretSkyDB/rag-blueprint-ssdb` at the design-partner kickoff.
* Tracks: <https://github.com/NVIDIA-AI-Blueprints/rag>
* Plug-in: <https://pypi.org/project/nat-retriever-ssdb/> *(Apache-2.0
  source: <https://github.com/SecretSkyDB/nat-retriever-ssdb>)*.

## Verified upstream pinning (May 2026)

* RAG Blueprint v2.5.0, port table:
  <https://docs.nvidia.com/rag/2.5.0/service-port-gpu-reference.html>
* NeMo Agent Toolkit `nat` CLI / `nvidia-nat` package:
  <https://docs.nvidia.com/nemo/agent-toolkit/latest/get-started/quick-start.html>
* Toolkit plug-in entry-point group `nat.plugins`:
  <https://docs.nvidia.com/nemo/agent-toolkit/1.4/extend/plugins.html>
