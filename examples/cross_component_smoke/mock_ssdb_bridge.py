"""Mock SSDB bridge — byte-compatible with the real ``/api/v1/{ingest,retrieve}``
endpoints (and their legacy ``/api/...`` aliases), so the laptop demo runs
without Docker / NIMs.

Ranking is intentionally trivial: token-overlap (Jaccard) over chunked
documents. The point of the demo is to show the **plugin → bridge → corpus**
wiring; the real ``ssdb-sql-rag`` service (``ssdb/sql/services/rag/``)
swaps in NeMo Retriever / Ollama embeddings + SSDB secret-shared
homomorphic top-k.
"""
from __future__ import annotations

import os
import re
from collections import Counter

from flask import Flask, jsonify, request


app = Flask(__name__)

# Persistent in-memory "corpus" for the lifetime of this process.
# Each row: {"title", "source", "content", "tokens": frozenset(str)}
_CORPUS: list[dict] = []
_CHUNK_CHARS = int(os.getenv("MOCK_CHUNK_CHARS", "800"))
_OVERLAP = int(os.getenv("MOCK_CHUNK_OVERLAP", "120"))


def _tokens(text: str) -> Counter:
    return Counter(re.findall(r"[a-z0-9]+", text.lower()))


def _chunks(text: str) -> list[str]:
    text = text.replace("\r\n", "\n").strip()
    if len(text) <= _CHUNK_CHARS:
        return [text]
    out: list[str] = []
    i = 0
    while i < len(text):
        out.append(text[i : i + _CHUNK_CHARS])
        i += _CHUNK_CHARS - _OVERLAP
    return [c for c in out if c.strip()]


def health():
    return jsonify({"ok": True, "rows": len(_CORPUS)})


def ingest():
    data = request.get_json(force=True, silent=True) or {}

    if isinstance(data.get("chunks"), list):
        added = 0
        titles: list[str] = []
        for c in data["chunks"]:
            content = (c.get("content") or "").strip()
            if not content:
                continue
            row = {
                "title":   c.get("title")  or "uploaded",
                "source":  c.get("source") or "user-upload",
                "content": content,
                "tokens":  _tokens(content),
            }
            _CORPUS.append(row)
            titles.append(row["title"])
            added += 1
        return jsonify({"ok": True, "inserted": added, "rows": len(_CORPUS), "titles": titles[:20]})

    text = (data.get("text") or "").strip()
    title = data.get("title") or "uploaded"
    source = data.get("source") or "user-upload"
    if not text:
        return jsonify({"ok": False, "error": "no text/chunks provided"}), 400

    if data.get("reset"):
        _CORPUS.clear()

    titles: list[str] = []
    for chunk in _chunks(text):
        _CORPUS.append({
            "title":   title,
            "source":  source,
            "content": chunk,
            "tokens":  _tokens(chunk),
        })
        titles.append(title)
    return jsonify({"ok": True, "inserted": len(titles), "rows": len(_CORPUS),
                    "titles": titles[:20]})


def retrieve():
    data = request.get_json(force=True, silent=True) or {}
    q = (data.get("query") or "").strip()
    if not q:
        return jsonify({"ok": False, "error": "missing 'query'"}), 400
    k = int(data.get("top_k") or 4)

    if not _CORPUS:
        return jsonify({"ok": True, "results": []})

    qtok = _tokens(q)
    scored = []
    for row in _CORPUS:
        # Jaccard-like score over token *multisets*: shared / (q ∪ row).
        shared = sum((qtok & row["tokens"]).values())
        denom  = sum((qtok | row["tokens"]).values()) or 1
        scored.append((shared / denom, row))
    scored.sort(key=lambda x: x[0], reverse=True)

    results = [
        {
            "content": r["content"],
            "title":   r["title"],
            "source":  r["source"],
            "score":   float(s),
        }
        for s, r in scored[:k] if s > 0
    ]
    return jsonify({"ok": True, "results": results})


# Register each handler at both /api/v1/<x> (canonical, what the plug-in calls)
# and /api/<x> (legacy alias, what older clients still use).
for path, handler, methods in [
    ("/health",   health,   ["GET"]),
    ("/ingest",   ingest,   ["POST"]),
    ("/retrieve", retrieve, ["POST"]),
]:
    app.add_url_rule(f"/api/v1{path}", endpoint=f"v1_{handler.__name__}",
                     view_func=handler, methods=methods)
    app.add_url_rule(f"/api{path}",    endpoint=f"legacy_{handler.__name__}",
                     view_func=handler, methods=methods)


if __name__ == "__main__":
    host = os.getenv("MOCK_HOST", "127.0.0.1")
    port = int(os.getenv("MOCK_PORT", "8765"))
    print(f"[mock_ssdb_bridge] listening on http://{host}:{port}")
    app.run(host=host, port=port, debug=False)
