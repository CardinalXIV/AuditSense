# app.py
from __future__ import annotations

from pathlib import Path
import base64
import json
import re

from flask import Flask, request, redirect, url_for, render_template, flash, jsonify

from utils.config import RAW_DIR, MD_DIR, CHUNK_DIR
from utils.file_processor import FileProcessor
from utils.naming import make_base_id
from utils.date_extract import DateExtractor
from utils.graph_client import build_graph_from_results, fetch_graph_snapshot

app = Flask(__name__)
app.secret_key = "dev-secret-change-me"

processor = FileProcessor(
    raw_dir=RAW_DIR,
    markdown_dir=MD_DIR,
    chunk_dir=CHUNK_DIR,
)

date_extractor = DateExtractor()

ALLOWED_SUFFIXES = {".pdf", ".docx", ".csv", ".xlsx", ".xls", ".md", ".markdown"}

# Tracks last uploaded run (used by /term-search)
LAST_RUN_DOC_IDS: list[str] = []


# ---------------------------------------------------------------------
# Upload + ingestion
# ---------------------------------------------------------------------
@app.route("/", methods=["GET", "POST"])
def index():
    global LAST_RUN_DOC_IDS

    if request.method == "GET":
        return render_template("index.html")

    files = request.files.getlist("files")
    if not files or all(f.filename == "" for f in files):
        flash("Please choose at least one file.")
        return redirect(url_for("index"))

    results: list[dict] = []
    total_chunks = 0

    # -----------------------------
    # Ingest documents
    # -----------------------------
    for file in files:
        if not file or file.filename == "":
            continue

        original_name = file.filename
        suffix = Path(original_name).suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            flash(f"Unsupported file type: {suffix} for {original_name}")
            continue

        base_id = make_base_id(original_name)
        raw_path = RAW_DIR / f"{base_id}{suffix}"
        file.save(raw_path)

        success, payload = processor.ingest_file(raw_path)
        if not success:
            flash(f"Ingestion failed for {original_name}: {payload.get('error')}")
            continue

        results.append(
            {
                "doc_id": base_id,
                "original_filename": original_name,
                "raw_path": str(raw_path),
                "markdown_path": payload["markdown_path"],
                "chunks_dir": payload["chunks_dir"],
                "num_chunks": payload["num_chunks"],
                "sample_chunks": payload["sample_chunks"],
                "dates": payload.get("dates", []),
                "entities": payload.get("entities", []),
                "keywords": payload.get("keywords", []),
            }
        )

        total_chunks += payload["num_chunks"]

    if not results:
        return redirect(url_for("index"))

    # Track this run for term search
    LAST_RUN_DOC_IDS = [doc["doc_id"] for doc in results]

    # -----------------------------
    # Collect ALL keywords (deduped)
    # -----------------------------
    all_keywords: list[str] = []
    seen: set[str] = set()

    for doc in results:
        for kw in doc.get("keywords", []):
            k = (kw or "").strip()
            if k and k not in seen:
                seen.add(k)
                all_keywords.append(k)

    all_keywords = all_keywords[:40]  # UI-safe cap

    # -----------------------------
    # Build combined dates + Gantt
    # -----------------------------
    all_dates: list[dict] = []
    for doc in results:
        for row in doc.get("dates") or []:
            all_dates.append(
                {
                    "source_file": row.get("Document") or doc["original_filename"],
                    "chunk_number": row.get("Chunk") or 0,
                    "date_text": row.get("Date Found") or "",
                    "formatted_date": row.get("Parsed Date") or "",
                    "context": row.get("Context") or "",
                    "method": row.get("Method") or "unknown",
                }
            )

    combined_gantt_b64 = None
    dates_table: list[dict] = []

    if all_dates:
        dates_df = date_extractor.create_dates_dataframe(all_dates)
        if dates_df is not None and not dates_df.empty:
            dates_table = dates_df.to_dict(orient="records")
            buf = date_extractor.create_gantt_chart(dates_df)
            if buf:
                combined_gantt_b64 = base64.b64encode(buf.getvalue()).decode("ascii")

    # -----------------------------
    # Write to Neo4j
    # (keep same behavior as you had: you’re not passing entities here)
    # -----------------------------
    if dates_table or any(d.get("entities") for d in results):
        build_graph_from_results(results, dates_table, [])

    return render_template(
        "result.html",
        results=results,
        total_chunks=total_chunks,
        combined_gantt_b64=combined_gantt_b64,
        dates_table=dates_table,
        all_keywords=all_keywords,
    )


# ---------------------------------------------------------------------
# Graph snapshot
# ---------------------------------------------------------------------
@app.route("/graph-data")
def graph_data():
    try:
        data = fetch_graph_snapshot() or {"nodes": [], "edges": []}
        return jsonify(data)
    except Exception as e:
        app.logger.exception("Error in /graph-data")
        return jsonify({"nodes": [], "edges": [], "error": str(e)}), 500


# ---------------------------------------------------------------------
# 🔎 Term interrogation across chunks (ROBUST)
# - Uses chunks.json if present
# - Falls back to scanning per-chunk .md files if chunks.json is missing/broken
# ---------------------------------------------------------------------
@app.route("/term-search")
def term_search():
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"q": q, "matches": []})

    q_low = q.lower()
    matches: list[dict] = []

    def make_snippet(text: str, match_start: int, window: int = 160) -> str:
        left = max(0, match_start - window)
        right = min(len(text), match_start + len(q) + window)
        snippet = text[left:right].replace("\n", " ")
        snippet = re.sub(r"\s+", " ", snippet).strip()
        prefix = "…" if left > 0 else ""
        suffix = "…" if right < len(text) else ""
        return f"{prefix}{snippet}{suffix}"

    def find_pos(text: str) -> int:
        return text.lower().find(q_low)

    # If someone calls /term-search before uploading this session,
    # fall back to scanning all doc dirs (still capped).
    doc_ids = LAST_RUN_DOC_IDS or [p.name for p in CHUNK_DIR.glob("*") if p.is_dir()]

    for doc_id in doc_ids:
        doc_dir = CHUNK_DIR / doc_id
        if not doc_dir.exists():
            continue

        json_path = doc_dir / "chunks.json"

        used_json = False

        # 1) Try chunks.json
        if json_path.exists():
            try:
                chunks = json.loads(json_path.read_text(encoding="utf-8"))
                for entry in chunks:
                    text = entry.get("text") or ""
                    if not text:
                        continue

                    pos = find_pos(text)
                    if pos == -1:
                        continue

                    used_json = True
                    matches.append(
                        {
                            "doc_id": doc_id,
                            "source_file": entry.get("source_file") or doc_id,
                            "chunk": entry.get("id") or 0,
                            "chunk_id": entry.get("chunk_id") or "",
                            "snippet": make_snippet(text, pos),
                            "pos": pos,
                        }
                    )

                    if len(matches) >= 60:
                        break
            except Exception:
                used_json = False

        if len(matches) >= 60:
            break

        # 2) Fallback: scan per-chunk .md files (doc_id_chunk_0001.md etc.)
        if not used_json:
            for md_path in sorted(doc_dir.glob("*.md")):
                try:
                    text = md_path.read_text(encoding="utf-8")
                except Exception:
                    continue

                pos = find_pos(text)
                if pos == -1:
                    continue

                chunk_num = 0
                m = re.search(r"_chunk_(\d+)\.md$", md_path.name)
                if m:
                    try:
                        chunk_num = int(m.group(1))
                    except Exception:
                        chunk_num = 0

                matches.append(
                    {
                        "doc_id": doc_id,
                        "source_file": doc_id,
                        "chunk": chunk_num,
                        "chunk_id": md_path.stem,
                        "snippet": make_snippet(text, pos),
                        "pos": pos,
                    }
                )

                if len(matches) >= 60:
                    break

        if len(matches) >= 60:
            break

    return jsonify({"q": q, "matches": matches})


# Keep /term-evidence for backwards compatibility (optional).
# You can delete this later if nothing calls it.
@app.route("/term-evidence")
def term_evidence():
    return term_search()


if __name__ == "__main__":
    app.run(debug=True)
