"""End-to-end demo query: NeMo Agent Toolkit plug-in -> SSDB bridge.

Loads the SSDB retriever block straight out of ``src/workflow.yml`` so the
demo proves the YAML and the plug-in agree on the schema, then issues two
known-answer queries.

Output is a small Markdown-ish dump: one line per hit with score + source
citation, suitable for screen-grabbing in a meeting.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any

import httpx
import yaml  # type: ignore

from nat_retriever_ssdb import SSDBRetriever, SSDBRetrieverConfig


# This file lives at <blueprint-repo>/examples/cross_component_smoke/ask_one.py
# parents[0] = cross_component_smoke/, [1] = examples/, [2] = blueprint repo root.
REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_YAML = REPO_ROOT / "src" / "workflow.yml"


def _load_retriever_cfg(path: Path, *, override_uri: str | None) -> SSDBRetrieverConfig:
    """Load the ``default_kb`` retriever block, optionally overriding ``uri``.

    The YAML targets the production bridge (``http://ssdb-sql-rag:8080``); for
    the laptop demo we override with the mock's URL.
    """
    if not path.is_file():
        raise SystemExit(f"!! could not find blueprint workflow at {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    blocks = (raw or {}).get("retrievers", {})
    if "default_kb" not in blocks:
        raise SystemExit(f"!! missing retrievers.default_kb in {path}")
    block: dict[str, Any] = dict(blocks["default_kb"])
    if block.get("_type") != "ssdb_retriever":
        raise SystemExit(f"!! default_kb._type is {block.get('_type')!r}, not ssdb_retriever")
    block.pop("_type", None)
    if override_uri:
        block["uri"] = override_uri
    return SSDBRetrieverConfig(**block)


def _format(out, query: str) -> str:
    lines: list[str] = [f"\n# Q: {query}"]
    for i, item in enumerate(out.items, start=1):
        title  = item.metadata.get("title", "?")
        source = item.metadata.get("source", "?")
        score  = item.metadata.get("score", 0.0)
        snippet = (item.content or "").replace("\n", " ").strip()
        if len(snippet) > 220:
            snippet = snippet[:220] + "…"
        lines.append(f"  [{i}] {title}  ({source})  score={score:.3f}")
        lines.append(f"      {snippet}")
    if not out.items:
        lines.append("  (no results)")
    return "\n".join(lines)


async def _run(bridge_url: str, queries: list[str]) -> int:
    cfg = _load_retriever_cfg(WORKFLOW_YAML, override_uri=bridge_url)
    print(f"== using bridge: {cfg.uri}  collection={cfg.collection_name}  top_k={cfg.top_k}")
    print(f"== plug-in description: {cfg.description.strip().splitlines()[0] if cfg.description else '(default)'}")

    # Quick liveness probe so the demo fails loudly if the bridge isn't up.
    # Try v1 first (canonical), fall back to legacy alias.
    try:
        base = str(cfg.uri).rstrip("/")
        with httpx.Client(timeout=2.0) as cx:
            r = cx.get(f"{base}/api/v1/health")
            if r.status_code == 404:
                cx.get(f"{base}/api/health").raise_for_status()
            else:
                r.raise_for_status()
    except Exception as e:
        print(f"!! bridge {cfg.uri} unreachable: {e}", file=sys.stderr)
        return 4

    retriever = SSDBRetriever(**cfg.model_dump())
    for q in queries:
        out = await retriever.search(q)
        print(_format(out, q))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bridge", default=os.getenv("SSDB_BRIDGE_URL", "http://127.0.0.1:8765"))
    ap.add_argument("--query", action="append", default=None,
                    help="May be passed multiple times. Defaults to two known-answer queries.")
    args = ap.parse_args()
    queries = args.query or [
        "What red flags should the chronic-care patient report?",
        "Telehealth FAQ: how do I prepare for the visit?",
    ]
    return asyncio.run(_run(args.bridge, queries))


if __name__ == "__main__":
    sys.exit(main())
