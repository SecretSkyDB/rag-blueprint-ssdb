# UPSTREAM.md — diff catalogue against `NVIDIA-AI-Blueprints/rag` v2.5.0

Tracked weekly via `.github/workflows/rebase-upstream.yml`. Every modified
or new file is listed here with the *why*. Anything not in this list
should match upstream byte-for-byte so a quarterly rebase to v2.6 / v2.7
stays trivial.

| Path | Status | Why |
|------|--------|-----|
| `README.md` | **REWRITTEN** | Re-frames the Blueprint around the secret-shared retrieval tier; preserves SecretSkyDB attribution. |
| `LICENSE` | preserved | Apache-2.0 — kept identical to upstream. |
| `UPSTREAM.md` | **NEW** | This file. |
| `deploy/compose/docker-compose-rag-server.yaml` | **NEW (mirrors upstream)** | Same service shape (`rag-server`, `rag-frontend`) and ports (8081, 8090) as upstream's compose; only `APP_VECTORSTORE_NAME` and `APP_VECTORSTORE_URL` differ. |
| `deploy/compose/docker-compose-ingestor-server.yaml` | **NEW (mirrors upstream)** | Same; only the two `APP_VECTORSTORE_*` env vars point at SSDB. |
| `deploy/compose/ssdb-overlay.yaml` | **NEW** | Adds SSDB proxy + 3 PG/ssdbpgvector shareholders + the `ssdb-sql-rag` service. Replaces upstream's Milvus block. |
| `deploy/compose/laptop-overlay.yaml` | **NEW** | No-NIM, no-GPU overlay using Ollama for embeddings + the toolkit served standalone via `nat serve` + the `fallback_ui`. For laptop reviews. |
| `deploy/compose/.env.example` | **MODIFIED** | Adds `NVIDIA_API_KEY`, `SSDB_SHARE_PWD`, `RAG_VERSION`, `SSDB_VERSION`, and the `APP_*` model overrides documented at https://docs.nvidia.com/rag/2.4.0/change-model.html. |
| `deploy/helm/values.yaml` | **MODIFIED** | `vector_store: ssdb` (default `milvus` in upstream); references the SSDB sub-chart. |
| `src/workflow.yml` | **MODIFIED** | One block: `_type: ssdb_retriever`, `uri: http://ssdb-sql-rag:8080`. LLM block defaults to `nvidia/llama-3.3-nemotron-super-49b-v1.5` per change-model.html. |
| `src/workflow.two_tier.yml` | **NEW** | Demonstrates Milvus public + SSDB regulated under one ReAct agent. |
| `src/chains/vector_store.py` | **MODIFIED** | Selects `ssdb_retriever` when `VECTOR_STORE=ssdb`. |
| `requirements.txt` | **MODIFIED** | Adds `nvidia-nat~=1.0` (the renamed `aiqtoolkit`). The `nat-retriever-ssdb` plug-in is installed editable from the sibling repo today (`pip install -e ../nat-retriever-ssdb`); a PyPI line replaces it once public v0.1.0 ships. |
| `examples/nat_run.sh` | **NEW** | Toolkit-CLI exerciser (`nat run --config_file=...`) of the workflow. Canonical CI smoke test. |
| `examples/fallback_ui/` | **NEW** | A 150-line HTML+Flask chat UI we control; shipped as the laptop-tier UI. |
| `examples/README.md` | **NEW** | Documents the four exerciser tiers (mock / laptop / full / CLI). |
| `notebooks/01_quickstart_ssdb.ipynb` | **NEW** | Quickstart variant of upstream's notebook against `ssdb-sql-rag`. |
| `notebooks/02_two_tier_milvus_plus_ssdb.ipynb` | **NEW** | Walks through the two-tier workflow. |
| `data/healthcare_synthetic/` | **NEW** | Synthetic chronic-care + telehealth corpus, freely shareable for demos. |
| `.github/workflows/rebase-upstream.yml` | **NEW** | Weekly rebase + PR. |
| `.github/workflows/ci.yml` | **MODIFIED** | Adds the SSDB integration job (compose-up + ingest + 5 known-answer queries). |

## Hot files most likely to conflict on rebase

* `src/workflow.yml` — when upstream renames the retriever block schema.
* `deploy/compose/docker-compose-rag-server.yaml` — when upstream re-numbers
  ports or splits the rag-server further.
* `deploy/compose/docker-compose-ingestor-server.yaml` — same.
* `requirements.txt` — when upstream bumps `nvidia-nat`.
* `src/chains/vector_store.py` — when upstream changes the vector-store
  factory dispatch.

When upstream changes the workflow.yml schema, surface a single PR adapting
the SSDB block to match — never accumulate multi-release drift.

## Verified upstream pins (May 2026)

* RAG Blueprint repo / latest release v2.5.0 (2026-03-17):
  https://github.com/NVIDIA-AI-Blueprints/rag
* Service / port reference:
  https://docs.nvidia.com/rag/2.5.0/service-port-gpu-reference.html
* Vector-store + model env vars:
  https://docs.nvidia.com/rag/2.4.0/change-model.html
* Toolkit CLI + package name:
  https://docs.nvidia.com/nemo/agent-toolkit/latest/get-started/quick-start.html
* Toolkit plug-in entry-point group `nat.plugins`:
  https://docs.nvidia.com/nemo/agent-toolkit/1.4/extend/plugins.html
* Retriever provider/client decorators:
  https://docs.nvidia.com/nemo/agent-toolkit/1.4/api/nat/cli/register_workflow/index.html
