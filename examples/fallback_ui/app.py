"""Fallback chat UI we control — for when the upstream NVIDIA UI image
isn't pinned for your release, or when you just want a tiny brandable
front-end.

Two backends are supported, picked by env:

* ``AIQ_RUNNER_URL``  — full toolkit pipeline. POSTs ``{input}`` to
  ``{AIQ_RUNNER_URL}/generate`` and renders the answer + citations. This
  is what you want once the NIMs / LLM are wired.

* ``SSDB_RAG_URL``    — no toolkit yet. POSTs ``{query}`` to
  ``{SSDB_RAG_URL}/api/v1/retrieve`` and shows raw chunks. Useful during
  early bring-up, on a laptop, or to prove the SSDB tier works without
  needing an LLM.

If both are set, the toolkit path wins. If neither is reachable, the page
shows a clear "no backend reachable" message instead of crashing.
"""
from __future__ import annotations

import os
from typing import Any

import requests
from flask import Flask, jsonify, render_template, request

AIQ_RUNNER_URL = os.getenv("AIQ_RUNNER_URL", "").rstrip("/") or None
SSDB_RAG_URL = os.getenv("SSDB_RAG_URL", "http://ssdb-sql-rag:8080").rstrip("/")
COLLECTION = os.getenv("SSDB_RAG_COLLECTION", "nv_rag_documents")
TOP_K = int(os.getenv("SSDB_RAG_TOP_K", "8"))
TIMEOUT = float(os.getenv("HTTP_TIMEOUT_S", "60"))


app = Flask(__name__)


@app.route("/")
def index():
    return render_template(
        "index.html",
        backend=("toolkit" if AIQ_RUNNER_URL else "ssdb-rag-direct"),
        backend_url=AIQ_RUNNER_URL or SSDB_RAG_URL,
        collection=COLLECTION,
    )


@app.route("/api/health")
def health():
    return jsonify({"ok": True, "backend": ("toolkit" if AIQ_RUNNER_URL else "ssdb-rag-direct")})


@app.route("/api/ask", methods=["POST"])
def ask():
    body = request.get_json(force=True, silent=True) or {}
    question = (body.get("question") or "").strip()
    if not question:
        return jsonify({"ok": False, "error": "missing 'question'"}), 400

    # ---- toolkit path -------------------------------------------------------
    if AIQ_RUNNER_URL:
        try:
            r = requests.post(
                f"{AIQ_RUNNER_URL}/generate",
                json={"input": question},
                timeout=TIMEOUT,
            )
            r.raise_for_status()
            data: dict[str, Any] = r.json()
            return jsonify({
                "ok": True,
                "backend": "toolkit",
                "answer": data.get("output") or data.get("answer") or "",
                "citations": data.get("citations") or [],
                "raw": data,
            })
        except Exception as e:
            return jsonify({"ok": False, "backend": "toolkit", "error": str(e)}), 502

    # ---- direct-retrieval fallback -----------------------------------------
    try:
        r = requests.post(
            f"{SSDB_RAG_URL}/api/v1/retrieve",
            json={"query": question, "top_k": TOP_K, "collection": COLLECTION},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return jsonify({"ok": False, "backend": "ssdb-rag-direct", "error": str(e)}), 502

    if not data.get("ok"):
        return jsonify({"ok": False, "backend": "ssdb-rag-direct",
                        "error": data.get("error", "unknown")}), 502

    chunks = data.get("results", [])
    # Build a Markdown-ish "answer" that's just the top chunks. Useful for
    # showing the SSDB tier works before an LLM is in the loop.
    if not chunks:
        answer = "_(no documents found)_"
    else:
        answer = "\n\n".join(
            f"**[{i+1}] {c.get('title','')}** — score `{c.get('score',0):.3f}`\n\n{c.get('content','')}"
            for i, c in enumerate(chunks)
        )
    return jsonify({
        "ok": True,
        "backend": "ssdb-rag-direct",
        "answer": answer,
        "citations": [
            {"id": f"[{i+1}]", "title": c.get("title", ""),
             "source": c.get("source", ""), "score": c.get("score", 0.0)}
            for i, c in enumerate(chunks)
        ],
        "raw": data,
    })


if __name__ == "__main__":
    print(f"== ssdb-rag-fallback-ui ==")
    print(f"  backend: {'toolkit' if AIQ_RUNNER_URL else 'ssdb-rag-direct'}")
    print(f"  url    : {AIQ_RUNNER_URL or SSDB_RAG_URL}")
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "3000")), debug=False)
