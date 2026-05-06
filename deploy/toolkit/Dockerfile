# syntax=docker/dockerfile:1.6
#
# rag-blueprint-ssdb toolkit image.
#
# Wraps the NVIDIA NeMo Agent Toolkit (`nat`) with the SSDB retriever
# plug-in pre-installed, so a workflow that declares
# `_type: ssdb_retriever` in `retrievers:` resolves at boot via the
# standard `nat.plugins` entry-point group.
#
# Run shape (driven from compose):
#
#   nat serve --config_file=/workflows/<flavor>.yml --host 0.0.0.0 --port 8000
#
# The compose mount injects the workflow file. There are two flavors in
# this repo's src/:
#
#   workflow.yml         - production: NIM LLM + SSDB retriever
#   workflow.laptop.yml  - laptop tier: Ollama LLM + SSDB retriever
#
# Build (from blueprint repo root):
#
#   docker build -f deploy/toolkit/Dockerfile -t ghcr.io/secretskydb/rag-blueprint-ssdb:0.1.0 .

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Toolkit + SSDB retriever plug-in. Both are public Apache-2.0 PyPI
# packages; pinning is loose so a `pip install` on a future patch
# release doesn't bust the image tag.
#
# nvidia-nat:        https://docs.nvidia.com/nemo/agent-toolkit/
# nat-retriever-ssdb: https://pypi.org/project/nat-retriever-ssdb/
RUN pip install --no-cache-dir \
    "nvidia-nat~=1.0" \
    "nat-retriever-ssdb~=0.2"

EXPOSE 8000

# Healthcheck pings `nat serve`'s root once it's listening.
HEALTHCHECK --interval=20s --timeout=3s --start-period=15s --retries=5 \
  CMD curl -fsS http://127.0.0.1:8000/ >/dev/null || exit 1

# `command:` in compose supplies the actual `nat serve ...` arguments;
# this default is a sensible fallback if someone runs the image directly.
CMD ["nat", "serve", "--config_file=/workflows/workflow.yml", \
     "--host", "0.0.0.0", "--port", "8000"]
