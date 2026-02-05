from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List

from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for
from werkzeug.utils import secure_filename

from utils.config import (
    ALLOWED_SUFFIXES,
    CHUNK_DIR,
    FLASK_DEBUG,
    FLASK_HOST,
    FLASK_PORT,
    MAX_CONTENT_LENGTH,
    MAX_TERM_MATCHES,
    MD_DIR,
    RAW_DIR,
    SECRET_KEY,
)
from utils.date_extract import DateExtractor
from utils.file_processor import FileProcessor
from utils.graph_client import graph_client
from utils.naming import make_base_id

SESSION_DOC_IDS_KEY = "last_run_doc_ids"
LAST_RUN_STATE: Dict[str, Any] = {}
BOT_OUTPUT_HINTS = {
    "bot",
    "chatgpt",
    "assistant",
    "llm",
    "claude",
    "gemini",
    "copilot",
    "response",
    "model_output",
}


def create_app(
    processor: FileProcessor | None = None,
    graph: Any = graph_client,
) -> Flask:
    app = Flask(__name__, static_folder="static", template_folder="templates")
    app.config["SECRET_KEY"] = SECRET_KEY
    app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    processor = processor or FileProcessor(raw_dir=RAW_DIR, markdown_dir=MD_DIR, chunk_dir=CHUNK_DIR)
    date_extractor = DateExtractor()

    @app.after_request
    def add_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

    @app.errorhandler(413)
    def handle_large_upload(_):
        flash("Upload is too large. Reduce file size and try again.")
        return redirect(url_for("index"))

    @app.route("/health")
    def health():
        return jsonify(
            {
                "status": "ok",
                "graph_enabled": bool(getattr(graph, "is_enabled", False)),
            }
        )

    @app.route("/", methods=["GET", "POST"])
    def index():
        if request.method == "GET":
            return render_template("index.html")

        files = request.files.getlist("files")
        if not files or all((f.filename or "").strip() == "" for f in files):
            flash("Please choose at least one file.")
            return redirect(url_for("index"))

        results: List[Dict[str, Any]] = []
        total_chunks = 0

        for uploaded in files:
            original_name = uploaded.filename or ""
            if not original_name:
                continue

            cleaned_name = secure_filename(original_name) or original_name
            suffix = Path(cleaned_name).suffix.lower()
            if suffix not in ALLOWED_SUFFIXES:
                flash(f"Unsupported file type: {suffix or '(none)'} for {original_name}")
                continue

            base_id = make_base_id(cleaned_name)
            raw_path = RAW_DIR / f"{base_id}{suffix}"

            try:
                uploaded.save(raw_path)
            except Exception:
                app.logger.exception("Failed to save uploaded file: %s", original_name)
                flash(f"Could not save file: {original_name}")
                continue

            success, payload = processor.ingest_file(raw_path)
            if not success:
                flash(f"Ingestion failed for {original_name}: {payload.get('error', 'unknown error')}")
                continue

            result_row = {
                "doc_id": base_id,
                "original_filename": original_name,
                "source_kind": _detect_source_kind(original_name),
                "raw_path": str(raw_path),
                "markdown_path": payload.get("markdown_path"),
                "chunks_dir": payload.get("chunks_dir"),
                "chunks_json_path": payload.get("chunks_json_path"),
                "num_chunks": payload.get("num_chunks", 0),
                "sample_chunks": payload.get("sample_chunks", []),
                "dates": payload.get("dates", []),
                "entities": payload.get("entities", []),
                "keywords": payload.get("keywords", []),
            }
            results.append(result_row)
            total_chunks += int(result_row["num_chunks"])

        if not results:
            return redirect(url_for("index"))

        session[SESSION_DOC_IDS_KEY] = [doc["doc_id"] for doc in results]

        all_keywords = _collect_keywords(results, limit=40)
        all_dates = _collect_dates(results)
        all_entities = _collect_entities(results)

        combined_gantt_b64 = None
        dates_table: List[Dict[str, Any]] = []

        if all_dates:
            dates_df = date_extractor.create_dates_dataframe(all_dates)
            if dates_df is not None and not dates_df.empty:
                dates_table = dates_df.to_dict(orient="records")
                buf = date_extractor.create_gantt_chart(dates_df)
                if buf:
                    import base64

                    combined_gantt_b64 = base64.b64encode(buf.getvalue()).decode("ascii")

        if (dates_table or all_entities) and getattr(graph, "is_enabled", False):
            try:
                graph.build_graph_from_results(results, dates_table, all_entities)
            except Exception:
                app.logger.exception("Failed to persist graph snapshot.")

        LAST_RUN_STATE.clear()
        LAST_RUN_STATE.update(
            {
                "results": results,
                "total_chunks": total_chunks,
                "combined_gantt_b64": combined_gantt_b64,
                "dates_table": dates_table,
                "all_keywords": all_keywords,
                "graph_enabled": bool(getattr(graph, "is_enabled", False)),
            }
        )
        return redirect(url_for("results_analysis"))

    @app.route("/results")
    def results():
        return redirect(url_for("results_analysis"))

    @app.route("/results/analysis")
    def results_analysis():
        if not LAST_RUN_STATE:
            flash("Run an upload first to view analysis.")
            return redirect(url_for("index"))
        return render_template(
            "result_analysis.html",
            results=LAST_RUN_STATE["results"],
            total_chunks=LAST_RUN_STATE["total_chunks"],
            combined_gantt_b64=LAST_RUN_STATE["combined_gantt_b64"],
            dates_table=LAST_RUN_STATE["dates_table"],
            graph_enabled=LAST_RUN_STATE["graph_enabled"],
        )

    @app.route("/results/graph")
    def results_graph():
        if not LAST_RUN_STATE:
            flash("Run an upload first to view graph workspace.")
            return redirect(url_for("index"))
        return render_template(
            "result_graph.html",
            results=LAST_RUN_STATE["results"],
            total_chunks=LAST_RUN_STATE["total_chunks"],
            all_keywords=LAST_RUN_STATE["all_keywords"],
            graph_enabled=LAST_RUN_STATE["graph_enabled"],
        )

    @app.route("/graph-data")
    def graph_data():
        if not getattr(graph, "is_enabled", False):
            return jsonify({"nodes": [], "edges": [], "disabled": True})

        try:
            data = graph.fetch_graph_snapshot() or {"nodes": [], "edges": []}
            return jsonify(data)
        except Exception:
            app.logger.exception("Error in /graph-data")
            return jsonify({"nodes": [], "edges": [], "error": "graph-fetch-failed"}), 500

    @app.route("/term-search")
    def term_search():
        query = (request.args.get("q") or "").strip()
        if not query:
            return jsonify({"q": query, "matches": []})

        q_lower = query.lower()
        matches: List[Dict[str, Any]] = []
        doc_ids = session.get(SESSION_DOC_IDS_KEY) or [
            p.name for p in CHUNK_DIR.glob("*") if p.is_dir()
        ]

        def make_snippet(text: str, match_start: int, window: int = 180) -> str:
            left = max(0, match_start - window)
            right = min(len(text), match_start + len(query) + window)
            snippet = re.sub(r"\s+", " ", text[left:right]).strip()
            prefix = "..." if left > 0 else ""
            suffix = "..." if right < len(text) else ""
            return f"{prefix}{snippet}{suffix}"

        for doc_id in doc_ids:
            if len(matches) >= MAX_TERM_MATCHES:
                break

            doc_dir = CHUNK_DIR / doc_id
            if not doc_dir.exists():
                continue

            from_json = _search_in_chunks_json(doc_dir / "chunks.json", q_lower, make_snippet)
            matches.extend(from_json)

            if len(matches) >= MAX_TERM_MATCHES:
                break

            if from_json:
                continue

            fallback = _search_in_chunk_markdown(doc_dir, q_lower, make_snippet)
            matches.extend(fallback)

        return jsonify({"q": query, "matches": matches[:MAX_TERM_MATCHES]})

    @app.route("/term-evidence")
    def term_evidence():
        return term_search()

    return app


def _collect_keywords(results: Iterable[Dict[str, Any]], limit: int = 40) -> List[str]:
    output: List[str] = []
    seen = set()
    for row in results:
        for kw in row.get("keywords", []):
            value = (kw or "").strip()
            if not value or value in seen:
                continue
            seen.add(value)
            output.append(value)
            if len(output) >= limit:
                return output
    return output


def _collect_dates(results: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    output: List[Dict[str, Any]] = []
    for doc in results:
        for row in doc.get("dates") or []:
            output.append(
                {
                    "source_file": row.get("Document") or row.get("source_file") or doc.get("original_filename"),
                    "chunk_number": row.get("Chunk") or row.get("chunk_number") or 0,
                    "date_text": row.get("Date Found") or row.get("date_text") or "",
                    "formatted_date": row.get("Parsed Date") or row.get("formatted_date") or "",
                    "context": row.get("Context") or row.get("context") or "",
                    "method": row.get("Method") or row.get("method") or "unknown",
                }
            )
    return output


def _collect_entities(results: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    output: List[Dict[str, Any]] = []
    for doc in results:
        for row in doc.get("entities") or []:
            output.append(
                {
                    "Document": row.get("Document") or doc.get("original_filename"),
                    "Chunk": row.get("Chunk") or 0,
                    "Entity": row.get("Entity") or "",
                    "Label": row.get("Label") or "ENTITY",
                }
            )
    return output


def _detect_source_kind(filename: str) -> str:
    lowered = filename.lower()
    if any(hint in lowered for hint in BOT_OUTPUT_HINTS):
        return "bot_output"
    return "document"


def _search_in_chunks_json(
    chunks_json_path: Path,
    q_lower: str,
    make_snippet,
) -> List[Dict[str, Any]]:
    if not chunks_json_path.exists():
        return []

    try:
        import json

        chunks = json.loads(chunks_json_path.read_text(encoding="utf-8"))
    except Exception:
        return []

    matches: List[Dict[str, Any]] = []
    for entry in chunks:
        text = str(entry.get("text") or "")
        if not text:
            continue

        pos = text.lower().find(q_lower)
        if pos == -1:
            continue

        matches.append(
            {
                "doc_id": chunks_json_path.parent.name,
                "source_file": entry.get("source_file") or chunks_json_path.parent.name,
                "document": entry.get("source_file") or chunks_json_path.parent.name,
                "chunk": entry.get("id") or entry.get("document_chunk_id") or 0,
                "chunk_id": entry.get("chunk_id") or "",
                "snippet": make_snippet(text, pos),
                "pos": pos,
            }
        )
    return matches


def _search_in_chunk_markdown(
    doc_dir: Path,
    q_lower: str,
    make_snippet,
) -> List[Dict[str, Any]]:
    matches: List[Dict[str, Any]] = []

    for md_path in sorted(doc_dir.glob("*.md")):
        try:
            text = md_path.read_text(encoding="utf-8")
        except Exception:
            continue

        pos = text.lower().find(q_lower)
        if pos == -1:
            continue

        chunk_num = 0
        parsed = re.search(r"_chunk_(\d+)\.md$", md_path.name)
        if parsed:
            try:
                chunk_num = int(parsed.group(1))
            except ValueError:
                chunk_num = 0

        matches.append(
            {
                "doc_id": doc_dir.name,
                "source_file": doc_dir.name,
                "document": doc_dir.name,
                "chunk": chunk_num,
                "chunk_id": md_path.stem,
                "snippet": make_snippet(text, pos),
                "pos": pos,
            }
        )
    return matches


app = create_app()


if __name__ == "__main__":
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=FLASK_DEBUG)
