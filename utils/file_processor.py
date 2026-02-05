from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Tuple

try:
    from chunknorris.chunkers import MarkdownChunker
    from chunknorris.parsers import CSVParser, DocxParser, ExcelParser, MarkdownParser, PdfParser
    from chunknorris.pipelines import BasePipeline
    CHUNKNORRIS_AVAILABLE = True
except ModuleNotFoundError:
    MarkdownChunker = None
    CSVParser = DocxParser = ExcelParser = MarkdownParser = PdfParser = None
    BasePipeline = Any
    CHUNKNORRIS_AVAILABLE = False

from utils.date_extract import DateExtractor
from utils.keywords_tfidf import extract_taxonomy_keywords
from utils.ner import extract_entities

logger = logging.getLogger(__name__)


class FileProcessor:
    """Ingest files into markdown/chunks and extract dates, entities, and keywords."""

    SUPPORTED_SUFFIXES = {".pdf", ".docx", ".csv", ".xlsx", ".xls", ".md", ".markdown"}

    def __init__(self, raw_dir: Path, markdown_dir: Path, chunk_dir: Path) -> None:
        self.raw_dir = raw_dir
        self.markdown_dir = markdown_dir
        self.chunk_dir = chunk_dir
        self.date_extractor = DateExtractor()

    def ingest_file(self, raw_path: Path) -> Tuple[bool, Dict[str, Any]]:
        if not CHUNKNORRIS_AVAILABLE:
            return False, {"error": "Missing dependency: chunknorris is not installed."}

        raw_path = raw_path.resolve()
        if not raw_path.exists():
            return False, {"error": f"File not found: {raw_path}"}

        try:
            pipeline = self._build_pipeline_for_path(raw_path)
        except ValueError as exc:
            return False, {"error": str(exc)}

        try:
            chunks = pipeline.chunk_file(str(raw_path))
        except Exception as exc:
            logger.exception("Chunking failed for %s", raw_path)
            return False, {"error": f"Chunking failed: {exc}"}

        if not chunks:
            return False, {"error": "No chunks generated from file."}

        doc_stem = raw_path.stem
        doc_chunk_dir = self.chunk_dir / doc_stem
        doc_chunk_dir.mkdir(parents=True, exist_ok=True)
        self.markdown_dir.mkdir(parents=True, exist_ok=True)

        combined_md_parts: List[str] = []
        sample_chunks: List[str] = []
        entities_rows: List[Dict[str, Any]] = []
        chunk_records: List[Dict[str, Any]] = []

        for idx, chunk in enumerate(chunks, start=1):
            text = self._chunk_to_text(chunk)
            combined_md_parts.append(text)

            chunk_file = doc_chunk_dir / f"{doc_stem}_chunk_{idx:04d}.md"
            chunk_file.write_text(text, encoding="utf-8")

            chunk_id = f"{doc_stem}#{idx}"
            chunk_records.append(
                {
                    "id": idx,
                    "chunk_id": chunk_id,
                    "source_file": raw_path.name,
                    "document_chunk_id": idx,
                    "text": text,
                }
            )

            try:
                entities = extract_entities(text)
            except Exception:
                logger.exception("Entity extraction failed for %s chunk %s", raw_path.name, idx)
                entities = []

            for entity in entities:
                entities_rows.append(
                    {
                        "Document": raw_path.name,
                        "Chunk": idx,
                        "Entity": entity.get("text", ""),
                        "Label": entity.get("label", ""),
                        "Context": text[:400],
                    }
                )

            if idx <= 3:
                preview = text[:1000] + ("\n...[truncated]" if len(text) > 1000 else "")
                sample_chunks.append(preview)

        combined_markdown = "\n\n---\n\n".join(combined_md_parts)
        md_path = self.markdown_dir / f"{doc_stem}.md"
        md_path.write_text(combined_markdown, encoding="utf-8")

        chunks_json_path = doc_chunk_dir / "chunks.json"
        chunks_json_path.write_text(
            json.dumps(chunk_records, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        try:
            doc_keywords = extract_taxonomy_keywords(texts=[combined_markdown], top_k=25)
        except Exception:
            logger.exception("Keyword extraction failed for %s", raw_path.name)
            doc_keywords = []

        dates_rows, gantt_b64 = self._extract_dates_and_gantt(chunk_records)

        payload: Dict[str, Any] = {
            "doc_stem": doc_stem,
            "markdown_path": str(md_path),
            "chunks_dir": str(doc_chunk_dir),
            "chunks_json_path": str(chunks_json_path),
            "num_chunks": len(chunks),
            "sample_chunks": sample_chunks,
            "dates": dates_rows,
            "entities": entities_rows,
            "keywords": doc_keywords,
            "full_text": combined_markdown,
            "gantt_img_b64": gantt_b64,
        }
        return True, payload

    def _chunk_to_text(self, chunk: Any) -> str:
        getter = getattr(chunk, "get_text", None)
        if callable(getter):
            value = getter()
            if isinstance(value, str):
                return value
            return str(value)
        return str(chunk)

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
        return BasePipeline(parser=self._get_parser_for_path(path), chunker=MarkdownChunker())

    def _extract_dates_and_gantt(
        self,
        chunk_records: List[Dict[str, Any]],
    ) -> Tuple[List[Dict[str, Any]], str | None]:
        raw_dates = self.date_extractor.extract_from_chunks_list(chunk_records)
        if not raw_dates:
            return [], None

        df = self.date_extractor.create_dates_dataframe(raw_dates)
        if df is None or df.empty:
            return [], None

        buf = self.date_extractor.create_gantt_chart(df)
        if not buf:
            return df.to_dict(orient="records"), None

        return (
            df.to_dict(orient="records"),
            base64.b64encode(buf.getvalue()).decode("ascii"),
        )
