"""Fallback chat UI we control — for when the upstream NVIDIA UI image
isn't pinned for your release, or when you just want a tiny brandable
front-end.

HTTP surface:

* ``GET  /``                 — the chat + upload + corpus page.
* ``POST /api/ask``          — RAG/LLM question. Body: ``{question, mode?}``.
                               ``mode`` ∈ ``auto`` | ``rag`` | ``retrieval`` |
                               ``llm_only``. ``auto`` keeps prior behavior:
                               toolkit if available, else direct retrieval.
* ``POST /api/ask/stream``   — Phase 4: SSE stream of the same answer.
                               Falls back to a single ``data: ...`` line if
                               the underlying backend doesn't stream.
* ``POST /api/upload``       — ingest a doc into the SSDB collection. Phase
                               2: PDF/DOCX/HTML/EPUB/RTF via ``extractors.py``.
* ``GET  /api/list``         — Phase 3: list distinct (title, source, count)
                               in the collection.
* ``POST /api/delete``       — Phase 3: delete by ``source`` (or ``id``).
* ``GET  /api/collections``  — Phase 5: list all SSDB collections (PG tables).
* ``GET  /api/health``       — liveness.

Backends (env vars):

* ``AIQ_RUNNER_URL``           full RAG agent (toolkit + tools).
* ``AIQ_RUNNER_LLM_ONLY_URL``  LLM-only toolkit (no retriever tool).
                                Used by ``mode=llm_only``. If unset, falls
                                back to ``AIQ_RUNNER_URL`` with a system
                                directive that disables tool calls.
* ``SSDB_RAG_URL``             SSDB rag service. Used by upload, by
                                ``mode=retrieval``, and by ``ask`` when
                                ``AIQ_RUNNER_URL`` is missing.
* ``SSDB_RAG_COLLECTION``      default collection name (``demo_kb``).
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Iterator

import requests
from flask import Flask, Response, jsonify, render_template, request, stream_with_context

from extractors import extract as extract_doc

# ── Config ────────────────────────────────────────────────────────────────

AIQ_RUNNER_URL = os.getenv("AIQ_RUNNER_URL", "").rstrip("/") or None
AIQ_RUNNER_LLM_ONLY_URL = os.getenv("AIQ_RUNNER_LLM_ONLY_URL", "").rstrip("/") or None
SSDB_RAG_URL = os.getenv("SSDB_RAG_URL", "http://ssdb-sql-rag:8080").rstrip("/")
COLLECTION = os.getenv("SSDB_RAG_COLLECTION", "nv_rag_documents")
TOP_K = int(os.getenv("SSDB_RAG_TOP_K", "8"))
TIMEOUT = float(os.getenv("HTTP_TIMEOUT_S", "60"))
INGEST_TIMEOUT = float(os.getenv("HTTP_INGEST_TIMEOUT_S", "300"))
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))  # 10 MiB
MAX_INGEST_CHARS = int(os.getenv("MAX_INGEST_CHARS", str(2 * 1024 * 1024)))   # 2 MiB

# Phase 1: directive prepended to the user message when mode=llm_only and
# we have to share AIQ_RUNNER_URL with the RAG variant. tool_calling_agent
# respects an inline "do not call tools" instruction reasonably well on
# llama3.2:3b; on :1b it occasionally still calls the tool, which is why
# AIQ_RUNNER_LLM_ONLY_URL (a separate `nat serve` with no tools) is
# preferred when set.
_LLM_ONLY_DIRECTIVE = (
    "You are answering from your own knowledge ONLY. "
    "Do NOT call any tools. Do NOT search the corpus. "
    "Do NOT cite documents. If you don't know, say so. Question: "
)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES


# ── Index ─────────────────────────────────────────────────────────────────


@app.route("/")
def index():
    backend = "toolkit" if AIQ_RUNNER_URL else "ssdb-rag-direct"
    return render_template(
        "index.html",
        backend=backend,
        backend_url=AIQ_RUNNER_URL or SSDB_RAG_URL,
        ssdb_rag_url=SSDB_RAG_URL,
        collection=COLLECTION,
        has_llm_only=bool(AIQ_RUNNER_LLM_ONLY_URL or AIQ_RUNNER_URL),
    )


@app.route("/api/health")
def health():
    return jsonify({
        "ok": True,
        "backend": ("toolkit" if AIQ_RUNNER_URL else "ssdb-rag-direct"),
        "llm_only_url": AIQ_RUNNER_LLM_ONLY_URL or AIQ_RUNNER_URL,
        "ssdb_rag_url": SSDB_RAG_URL,
        "collection": COLLECTION,
    })


# ──────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────


def _maybe_unwrap_tool_json(text: str) -> tuple[str, list[dict]]:
    """Some small models echo the tool's raw JSON. Surface readable text
    + best-effort citations rather than a wall of ``{"status":"success"...}``.
    """
    s = (text or "").strip()
    if not (s.startswith("{") or s.startswith("[")):
        return text, []
    try:
        data = json.loads(s)
    except Exception:
        return text, []

    citations: list[dict] = []

    # Shape 1: {results: [...]}
    if isinstance(data, dict) and isinstance(data.get("results"), list):
        results = data["results"]
        parts: list[str] = []
        for i, h in enumerate(results, 1):
            if not isinstance(h, dict):
                continue
            content = h.get("content") or h.get("text") or h.get("page_content") or ""
            title = h.get("title") or h.get("source") or f"chunk {i}"
            src = h.get("source") or ""
            parts.append(f"**[{i}] {title}**\n\n{content}")
            citations.append({"id": f"[{i}]", "title": title, "source": src,
                              "score": float(h.get("score") or 0.0)})
        if parts:
            return "\n\n".join(parts), citations

    if isinstance(data, dict) and "result" in data:
        r = data["result"]
        if isinstance(r, dict):
            content = r.get("page_content") or r.get("content") or r.get("text") or ""
            title = r.get("title") or r.get("source") or "result"
            src = r.get("source") or ""
            if content:
                citations.append({"id": "[1]", "title": title, "source": src, "score": 0.0})
                return content, citations
        if isinstance(r, str):
            return r, []

    if isinstance(data, dict) and "page_content" in data:
        return data["page_content"], []

    return text, []


def _ssdb_post(path: str, payload: dict, *, timeout: float = TIMEOUT) -> tuple[bool, dict]:
    """POST to the SSDB rag service; return (ok, json-or-error-dict)."""
    try:
        r = requests.post(f"{SSDB_RAG_URL}{path}", json=payload, timeout=timeout)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return False, {"error": f"{path} failed: {e}"}
    if not data.get("ok", True):
        return False, {"error": data.get("error", f"{path} returned ok=false")}
    return True, data


def _ssdb_get(path: str, *, params: dict | None = None, timeout: float = TIMEOUT) -> tuple[bool, dict]:
    try:
        r = requests.get(f"{SSDB_RAG_URL}{path}", params=params or {}, timeout=timeout)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return False, {"error": f"{path} failed: {e}"}
    return True, data


def _toolkit_ask(url: str, question: str) -> tuple[bool, dict, int]:
    """Hit a `nat serve` /generate endpoint; return (ok, payload, http_status)."""
    try:
        r = requests.post(
            f"{url}/generate",
            json={"input_message": question},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        data: dict[str, Any] = r.json()
    except Exception as e:
        return False, {"error": str(e)}, 502
    raw_answer = data.get("value") or data.get("output") or data.get("answer") or ""
    answer, citations = _maybe_unwrap_tool_json(raw_answer)
    if not citations:
        citations = data.get("citations") or []
    return True, {"answer": answer, "citations": citations, "raw": data}, 200


# ──────────────────────────────────────────────────────────────────────────
# Ask
# ──────────────────────────────────────────────────────────────────────────


@app.route("/api/ask", methods=["POST"])
def ask():
    body = request.get_json(force=True, silent=True) or {}
    question = (body.get("question") or "").strip()
    mode = (body.get("mode") or "auto").strip().lower()
    collection = (body.get("collection") or COLLECTION).strip()
    if not question:
        return jsonify({"ok": False, "error": "missing 'question'"}), 400
    if mode not in {"auto", "rag", "retrieval", "llm_only"}:
        return jsonify({"ok": False, "error": f"unknown mode {mode!r}"}), 400

    # Resolve effective backend.
    if mode == "auto":
        mode = "rag" if AIQ_RUNNER_URL else "retrieval"

    # ---- LLM-only (no retrieval) ------------------------------------------
    if mode == "llm_only":
        target = AIQ_RUNNER_LLM_ONLY_URL or AIQ_RUNNER_URL
        if not target:
            return jsonify({"ok": False, "mode": mode,
                            "error": "no toolkit URL configured (AIQ_RUNNER_LLM_ONLY_URL or AIQ_RUNNER_URL)"}), 400
        # If we have a dedicated llm-only toolkit, the question goes through
        # as-is (the workflow has no retriever tool). Otherwise prepend the
        # directive to discourage the agent from calling search_kb.
        prompt = question if AIQ_RUNNER_LLM_ONLY_URL else (_LLM_ONLY_DIRECTIVE + question)
        ok, payload, status = _toolkit_ask(target, prompt)
        return jsonify({"ok": ok, "mode": mode, "backend": "toolkit-llm-only", **payload}), (200 if ok else status)

    # ---- Retrieval-only (no LLM) ------------------------------------------
    if mode == "retrieval":
        ok, data = _ssdb_post(
            "/api/v1/retrieve",
            {"query": question, "top_k": TOP_K, "collection": collection},
        )
        if not ok:
            return jsonify({"ok": False, "mode": mode, "backend": "ssdb-rag-direct", **data}), 502
        chunks = data.get("results", [])
        if not chunks:
            answer = "_(no documents found)_"
        else:
            answer = "\n\n".join(
                f"**[{i+1}] {c.get('title','')}** — score `{c.get('score',0):.3f}`\n\n{c.get('content','')}"
                for i, c in enumerate(chunks)
            )
        return jsonify({
            "ok": True,
            "mode": mode,
            "backend": "ssdb-rag-direct",
            "answer": answer,
            "citations": [
                {"id": f"[{i+1}]", "title": c.get("title", ""),
                 "source": c.get("source", ""), "score": c.get("score", 0.0)}
                for i, c in enumerate(chunks)
            ],
            "raw": data,
        })

    # ---- Full RAG via toolkit --------------------------------------------
    if not AIQ_RUNNER_URL:
        return jsonify({"ok": False, "mode": mode,
                        "error": "AIQ_RUNNER_URL not configured; pick mode=retrieval"}), 400
    ok, payload, status = _toolkit_ask(AIQ_RUNNER_URL, question)
    return jsonify({"ok": ok, "mode": mode, "backend": "toolkit", **payload}), (200 if ok else status)


# ──────────────────────────────────────────────────────────────────────────
# Ask (streaming) — Phase 4
# ──────────────────────────────────────────────────────────────────────────


@app.route("/api/ask/stream", methods=["POST"])
def ask_stream():
    """Server-sent events wrapper around /api/ask.

    nvidia-nat 1.6 /generate is single-shot (no native SSE), so this
    currently sends one ``data:`` event per logical chunk: an opening
    ``meta`` event with mode/backend, then a single ``token`` event with
    the full answer, then a ``done`` event with citations. The front-end
    can render incrementally and gracefully handle either shape — this
    leaves room to upgrade to true token streaming when the toolkit
    exposes it.
    """
    body = request.get_json(force=True, silent=True) or {}

    @stream_with_context
    def gen() -> Iterator[str]:
        try:
            with app.test_request_context("/api/ask", method="POST", json=body):
                resp = ask()
            data = resp.get_json() if hasattr(resp, "get_json") else json.loads(resp[0].data)
        except Exception as e:
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
            return
        meta = {k: data.get(k) for k in ("mode", "backend", "ok") if k in data}
        yield f"event: meta\ndata: {json.dumps(meta)}\n\n"
        if not data.get("ok"):
            yield f"event: error\ndata: {json.dumps({'error': data.get('error', 'unknown')})}\n\n"
            return
        # Single-shot answer for now; chunk by paragraph to feel streamy.
        ans = data.get("answer") or ""
        if ans:
            for para in re.split(r"(\n\n)", ans):
                if not para:
                    continue
                yield f"event: token\ndata: {json.dumps({'text': para})}\n\n"
        cits = data.get("citations") or []
        yield f"event: done\ndata: {json.dumps({'citations': cits})}\n\n"

    return Response(gen(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ──────────────────────────────────────────────────────────────────────────
# Upload (ingest into SSDB) — Phase 2
# ──────────────────────────────────────────────────────────────────────────


@app.route("/api/upload", methods=["POST"])
def upload():
    """Ingest a document into the SSDB collection.

    Two ways to call this:

    * ``multipart/form-data`` with a ``file`` field. Optional ``title``,
      ``source``, ``collection`` form fields.
    * ``application/json`` with ``{"text": "...", "title": "...",
      "source": "...", "collection": "..."}``.
    """
    title = ""
    source = ""
    text = ""
    collection = COLLECTION
    fmt = "plain"
    extract_meta: dict = {}

    if request.files and "file" in request.files:
        f = request.files["file"]
        title = request.form.get("title") or f.filename or "uploaded"
        source = request.form.get("source") or f.filename or "uploaded"
        collection = request.form.get("collection") or COLLECTION
        try:
            raw = f.read()
        except Exception as e:
            return jsonify({"ok": False, "error": f"could not read file: {e}"}), 400
        try:
            text, extract_meta = extract_doc(raw, filename=f.filename or "", mimetype=f.mimetype or "")
            fmt = extract_meta.get("format", "plain")
        except Exception as e:
            return jsonify({"ok": False, "error": f"extract failed ({fmt}): {e}"}), 400
    else:
        body = request.get_json(force=True, silent=True) or {}
        text = (body.get("text") or "").strip()
        title = (body.get("title") or "pasted-text").strip()
        source = (body.get("source") or title).strip()
        collection = (body.get("collection") or COLLECTION).strip()
        extract_meta = {"format": "plain", "chars": len(text), "bytes_in": len(text.encode("utf-8"))}

    if not text.strip():
        return jsonify({"ok": False, "error": "missing text / empty file"}), 400

    if len(text) > MAX_INGEST_CHARS:
        return jsonify({
            "ok": False,
            "error": (f"extracted text too large: {len(text)} chars > "
                      f"MAX_INGEST_CHARS={MAX_INGEST_CHARS}"),
            "extract": extract_meta,
        }), 413

    ok, data = _ssdb_post("/api/v1/setup", {"collection": collection})
    if not ok:
        return jsonify({"ok": False, **data, "extract": extract_meta}), 502

    ok, data = _ssdb_post("/api/v1/ingest", {
        "collection": collection,
        "title": title,
        "source": source,
        "text": text,
    }, timeout=INGEST_TIMEOUT)
    if not ok:
        return jsonify({"ok": False, **data, "extract": extract_meta}), 502

    return jsonify({
        "ok": True,
        "title": title,
        "source": source,
        "collection": collection,
        "inserted": data.get("inserted"),
        "rows": data.get("rows"),
        "elapsed_ms": data.get("elapsed_ms"),
        "extract": extract_meta,
    })


# ──────────────────────────────────────────────────────────────────────────
# Corpus management — Phase 3
# ──────────────────────────────────────────────────────────────────────────


@app.route("/api/list", methods=["GET"])
def api_list():
    collection = (request.args.get("collection") or COLLECTION).strip()
    ok, data = _ssdb_get("/api/v1/list", params={"collection": collection})
    if not ok:
        return jsonify({"ok": False, **data}), 502
    return jsonify(data)


@app.route("/api/delete", methods=["POST"])
def api_delete():
    body = request.get_json(force=True, silent=True) or {}
    payload = {
        "collection": (body.get("collection") or COLLECTION).strip(),
    }
    if body.get("source"):
        payload["source"] = str(body["source"])
    elif body.get("id"):
        payload["id"] = str(body["id"])
    else:
        return jsonify({"ok": False, "error": "need 'source' or 'id'"}), 400
    ok, data = _ssdb_post("/api/v1/delete", payload)
    if not ok:
        return jsonify({"ok": False, **data}), 502
    return jsonify(data)


# ──────────────────────────────────────────────────────────────────────────
# Collections — Phase 5
# ──────────────────────────────────────────────────────────────────────────


@app.route("/api/collections", methods=["GET"])
def api_collections():
    ok, data = _ssdb_get("/api/v1/collections")
    if not ok:
        return jsonify({"ok": False, **data}), 502
    return jsonify(data)


# ──────────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    print(f"== ssdb-rag-fallback-ui ==")
    print(f"  ask backend     : {'toolkit' if AIQ_RUNNER_URL else 'ssdb-rag-direct'}")
    print(f"  ask url         : {AIQ_RUNNER_URL or SSDB_RAG_URL}")
    print(f"  llm-only url    : {AIQ_RUNNER_LLM_ONLY_URL or '(shared with ask url)'}")
    print(f"  ingest url      : {SSDB_RAG_URL}/api/v1/ingest")
    print(f"  collection      : {COLLECTION}")
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "3000")), debug=False)
