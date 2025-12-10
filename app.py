# app.py
from pathlib import Path
import base64

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


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "GET":
        return render_template("index.html")

    files = request.files.getlist("files")
    if not files or all(f.filename == "" for f in files):
        flash("Please choose at least one file.")
        return redirect(url_for("index"))

    results = []
    total_chunks = 0

    for file in files:
        if not file or file.filename == "":
            continue

        original_name = file.filename
        suffix = Path(original_name).suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            flash(f"Unsupported file type: {suffix} for {original_name}")
            continue

        # deterministic, human-readable id
        base_id = make_base_id(original_name)

        # store raw file as <base_id><ext>
        raw_filename = f"{base_id}{suffix}"
        raw_path = RAW_DIR / raw_filename
        file.save(raw_path)

        # run full ingestion
        success, payload = processor.ingest_file(raw_path)
        if not success:
            flash(
                f"Ingestion failed for {original_name}: "
                f"{payload.get('error', 'Unknown error')}"
            )
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
                # per-document dates (list of dicts)
                "dates": payload.get("dates", []),
                # per-document entities (list of dicts)
                "entities": payload.get("entities", []),
            }
        )

        total_chunks += payload["num_chunks"]

    # If everything failed, go back to upload page
    if not results:
        return redirect(url_for("index"))

    # ---------- build combined dates + Gantt ----------

    all_dates = []
    for doc in results:
        for row in doc.get("dates") or []:
            all_dates.append(
                {
                    # normalise keys to what DateExtractor.create_dates_dataframe expects
                    "source_file": row.get("Document") or doc["original_filename"],
                    "chunk_number": row.get("Chunk") or 0,
                    "date_text": row.get("Date Found") or "",
                    "formatted_date": row.get("Parsed Date") or "",
                    "context": row.get("Context") or "",
                    # preserve the original detection method
                    "method": row.get("Method") or "unknown",
                }
            )

    # ---------- collect entities across all docs ----------

    all_entities = []
    for doc in results:
        for row in doc.get("entities") or []:
            all_entities.append(
                {
                    "Document": row.get("Document") or doc["original_filename"],
                    "Chunk": row.get("Chunk") or 0,
                    "Entity": row.get("Entity") or "",
                    "Label": row.get("Label") or "",
                    "Context": row.get("Context") or "",
                }
            )

    combined_gantt_b64 = None
    dates_table = []

    if all_dates:
        dates_df = date_extractor.create_dates_dataframe(all_dates)
        if not dates_df.empty:
            dates_table = dates_df.to_dict(orient="records")

            buf = date_extractor.create_gantt_chart(dates_df)
            if buf is not None:
                combined_gantt_b64 = base64.b64encode(buf.getvalue()).decode("ascii")

    # write the current run into Neo4j (docs + chunks + dates + entities)
    if dates_table or all_entities:
        build_graph_from_results(results, dates_table, all_entities)

    return render_template(
        "result.html",
        results=results,
        total_chunks=total_chunks,
        combined_gantt_b64=combined_gantt_b64,
        dates_table=dates_table,
    )


@app.route("/graph-data")
def graph_data():
    """
    Return a JSON snapshot of the current Neo4j graph
    (Documents, Chunks, Dates, Entities + relationships).
    """
    data = fetch_graph_snapshot()
    return jsonify(data)


if __name__ == "__main__":
    app.run(debug=True)