# utils/file_processor.py
from __future__ import annotations

import base64
from pathlib import Path
from typing import Dict, List, Tuple

from chunknorris.parsers import (
    PdfParser,
    DocxParser,
    MarkdownParser,
    CSVParser,
    ExcelParser,
)
from chunknorris.chunkers import MarkdownChunker
from chunknorris.pipelines import BasePipeline

from utils.date_extract import DateExtractor
from utils.ner import extract_entities
from utils.keywords_tfidf import extract_taxonomy_keywords


class FileProcessor:
    """
    Chunk + extract dates, entities, and taxonomy-style keywords.
    """

    SUPPORTED_SUFFIXES = {".pdf", ".docx", ".csv", ".xlsx", ".xls", ".md", ".markdown"}

    def __init__(self, raw_dir: Path, markdown_dir: Path, chunk_dir: Path) -> None:
        self.raw_dir = raw_dir
        self.markdown_dir = markdown_dir
        self.chunk_dir = chunk_dir
        self.date_extractor = DateExtractor()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def ingest_file(self, raw_path: Path) -> Tuple[bool, Dict]:
        raw_path = raw_path.resolve()
        if not raw_path.exists():
            return False, {"error": f"File not found: {raw_path}"}

        try:
            pipeline = self._build_pipeline_for_path(raw_path)
        except ValueError as e:
            return False, {"error": str(e)}

        try:
            chunks = pipeline.chunk_file(str(raw_path))
        except Exception as e:
            return False, {"error": f"Chunking failed: {e}"}

        doc_stem = raw_path.stem
        doc_chunk_dir = self.chunk_dir / doc_stem
        doc_chunk_dir.mkdir(parents=True, exist_ok=True)
        self.markdown_dir.mkdir(parents=True, exist_ok=True)

        combined_md_parts: List[str] = []
        sample_chunks: List[str] = []
        entities_rows: List[Dict] = []

        # -----------------------------
        # Chunk processing + NER
        # -----------------------------
        for idx, ch in enumerate(chunks, start=1):
            text = getattr(ch, "get_text", lambda: str(ch))()
            combined_md_parts.append(text)

            # Save chunk markdown
            chunk_path = doc_chunk_dir / f"{doc_stem}_chunk_{idx:04d}.md"
            chunk_path.write_text(text, encoding="utf-8")

            # NER (safe)
            try:
                ents = extract_entities(text)
            except Exception:
                ents = []

            for ent in ents:
                entities_rows.append(
                    {
                        "Document": raw_path.name,
                        "Chunk": idx,
                        "Entity": ent.get("text", ""),
                        "Label": ent.get("label", ""),
                        "Context": text[:400],
                    }
                )

            # Preview
            if idx <= 3:
                preview = text[:1000] + ("\n...[truncated]" if len(text) > 1000 else "")
                sample_chunks.append(preview)

        # -----------------------------
        # Combined markdown
        # -----------------------------
        combined_markdown = "\n\n---\n\n".join(combined_md_parts)
        md_path = self.markdown_dir / f"{doc_stem}.md"
        md_path.write_text(combined_markdown, encoding="utf-8")

        # -----------------------------
        # TAXONOMY KEYWORDS (spaCy + TF-IDF)
        # -----------------------------
        doc_keywords = extract_taxonomy_keywords(
            texts=[combined_markdown],
            top_k=25,
        )

        # -----------------------------
        # Dates + Gantt
        # -----------------------------
        dates_rows, gantt_b64 = self._extract_dates_and_gantt(
            raw_path.name,
            combined_markdown,
        )

        payload: Dict = {
            "doc_stem": doc_stem,
            "markdown_path": str(md_path),
            "chunks_dir": str(doc_chunk_dir),
            "num_chunks": len(chunks),
            "sample_chunks": sample_chunks,
            "dates": dates_rows,
            "entities": entities_rows,
            "keywords": doc_keywords,
            "full_text": combined_markdown,
            "gantt_img_b64": gantt_b64,
        }

        return True, payload

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _get_parser_for_path(self, path: Path):
        ext = path.suffix.lower()
        if ext == ".pdf":
            return PdfParser(use_ocr="never")
        if ext == ".docx":
            return DocxParser()
        if ext in {".md", ".markdown"}:
            return MarkdownParser()
        if ext == ".csv":
            return CSVParser()
        if ext in {".xls", ".xlsx"}:
            return ExcelParser()
        raise ValueError(f"Unsupported file extension: {ext}")

    def _build_pipeline_for_path(self, path: Path) -> BasePipeline:
        return BasePipeline(
            parser=self._get_parser_for_path(path),
            chunker=MarkdownChunker(),
        )

    def _extract_dates_and_gantt(
        self,
        source_filename: str,
        full_text: str,
    ) -> Tuple[List[Dict], str | None]:

        raw_dates = self.date_extractor.extract_dates_from_text(full_text)
        if not raw_dates:
            return [], None

        rows = []
        for idx, d in enumerate(raw_dates, start=1):
            rows.append(
                {
                    "source_file": source_filename,
                    "chunk_number": idx,
                    "date_text": d["original_text"],
                    "parsed_date": d["parsed_date"],
                    "formatted_date": d["formatted"],
                    "context": d["context"],
                    "method": d.get("method", "unknown"),
                }
            )

        df = self.date_extractor.create_dates_dataframe(rows)
        if df is None or df.empty:
            return [], None

        buf = self.date_extractor.create_gantt_chart(df)
        if not buf:
            return df.to_dict(orient="records"), None

        return df.to_dict(orient="records"), base64.b64encode(buf.getvalue()).decode("ascii")