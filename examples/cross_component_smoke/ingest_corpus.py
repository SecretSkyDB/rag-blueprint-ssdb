"""Ingest the synthetic healthcare corpus into the SSDB bridge.

Calls the canonical ``POST /api/v1/ingest`` (with a fallback to the legacy
``/api/ingest`` alias) - works against the mock bridge and the real
``ssdb-sql-rag`` service. Exits non-zero if any document fails to ingest.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx


# This file lives at <blueprint-repo>/examples/cross_component_smoke/ingest_corpus.py
# parents[0] = cross_component_smoke/, [1] = examples/, [2] = blueprint repo root.
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CORPUS = REPO_ROOT / "data" / "healthcare_synthetic"


def _post_v1(cx: httpx.Client, base: str, path: str, body: dict) -> httpx.Response:
    """POST to /api/v1{path}, falling back to /api{path} on 404."""
    base = base.rstrip("/")
    r = cx.post(f"{base}/api/v1{path}", json=body)
    if r.status_code == 404:
        r = cx.post(f"{base}/api{path}", json=body)
    return r


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bridge", default="http://127.0.0.1:8765",
                    help="SSDB bridge base URL (default: local mock)")
    ap.add_argument("--collection", default="nv_rag_documents",
                    help="SSDB collection name (default: nv_rag_documents)")
    ap.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS,
                    help="Directory of .md/.txt files to ingest")
    args = ap.parse_args()

    if not args.corpus.is_dir():
        print(f"!! corpus dir not found: {args.corpus}", file=sys.stderr)
        return 2

    files = sorted([
        p for p in args.corpus.iterdir()
        if p.suffix.lower() in {".md", ".txt"}
    ])
    if not files:
        print(f"!! no .md/.txt files in {args.corpus}")
        return 2

    total = 0
    with httpx.Client(timeout=30.0) as cx:
        for p in files:
            text = p.read_text(encoding="utf-8")
            r = _post_v1(cx, args.bridge, "/ingest", {
                "collection": args.collection,
                "text": text,
                "title": p.name,
                "source": p.name,
            })
            r.raise_for_status()
            data = r.json()
            if not data.get("ok"):
                print(f"!! ingest failed for {p.name}: {data.get('error')}")
                return 3
            total += int(data.get("inserted", 0))
            print(f"   + {p.name}: {data.get('inserted')} chunk(s)")

    print(f"== ingested {total} chunks across {len(files)} files "
          f"into {args.bridge} (collection={args.collection})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
