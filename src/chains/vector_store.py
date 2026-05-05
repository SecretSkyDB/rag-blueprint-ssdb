"""Vector-store selector for rag-blueprint-ssdb.

Tiny shim that routes the upstream Blueprint's vector-store factory to either
Milvus (upstream default) or SSDB (this fork's default). Only the SSDB branch
is exercised by the SSDB-only `workflow.yml`; the two-tier `workflow.two_tier.yml`
exercises both.

Real chain construction is delegated to the upstream module when available.
This shim is intentionally small so the rebase footprint stays trivial.
"""
from __future__ import annotations

import os
from typing import Any


VECTOR_STORE = os.getenv("VECTOR_STORE", "ssdb").strip().lower()


def get_vector_store_retriever(**cfg: Any):
    """Return a retriever instance suitable for the upstream RAG chain.

    For ``VECTOR_STORE=ssdb`` we instantiate the SSDB plug-in directly (so the
    chain works even when running outside the toolkit's registry, e.g. notebooks).
    For ``VECTOR_STORE=milvus`` we defer to the upstream factory.
    """
    if VECTOR_STORE == "ssdb":
        from nat_retriever_ssdb import SSDBRetriever  # type: ignore

        return SSDBRetriever(
            uri=cfg.get("uri", os.getenv("SSDB_BRIDGE_URI", "http://ssdb-bridge:8000")),
            collection_name=cfg.get("collection_name", "nv_rag_documents"),
            top_k=int(cfg.get("top_k", 8)),
            description=cfg.get(
                "description",
                "SecretSkyDB encrypted-nearest-neighbor retriever over "
                "secret-shared shards in independent shareholder Postgres instances.",
            ),
            license_token=cfg.get("license_token"),
        )

    # Default upstream path; imports are lazy because Milvus deps are heavy.
    try:
        from nat.retrievers.milvus import MilvusRetriever  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "VECTOR_STORE=milvus selected but the upstream Milvus retriever "
            "is not importable in this environment."
        ) from e
    return MilvusRetriever(**cfg)
