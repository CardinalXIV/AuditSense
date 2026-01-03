# utils/file_processor.py

from __future__ import annotations
import re
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS
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
from utils.keywords_tfidf import make_vectorizer, top_keywords_for_many_texts


class FileProcessor:
    """
    Thin facade around ChunkNorris + DateExtractor (+ NER + TF-IDF keywords).

    ingest_file() returns:
        (success: bool, payload: dict)

    payload on success:
        {
            "doc_stem": str,
            "markdown_path": str,
            "chunks_dir": str,
            "num_chunks": int,
            "sample_chunks": List[str],
            "dates": List[dict],
            "entities": List[dict],
            "keywords": List[str],             # doc-level
            "chunk_keywords": List[dict],      # per-chunk
            "gantt_img_b64": Optional[str]
        }
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
        """
        Ingest + chunk + extract dates/entities/keywords for a single file.

        Returns:
            (True, payload_dict) on success
            (False, {"error": "..."}) on failure
        """
        raw_path = raw_path.resolve()
        if not raw_path.exists():
            return False, {"error": f"File not found: {raw_path}"}

        try:
            pipeline = self._build_pipeline_for_path(raw_path)
        except ValueError as e:
            return False, {"error": str(e)}

        # --- Chunking via ChunkNorris ---
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
        entities_rows: List[Dict] = []  # per-chunk entities

        # Save per-chunk markdown + collect text + run NER
        for idx, ch in enumerate(chunks, start=1):
            text = getattr(ch, "get_text", lambda: str(ch))()
            combined_md_parts.append(text)

            # Write chunk markdown file
            chunk_id = f"{doc_stem}_chunk_{idx:04d}"
            chunk_path = doc_chunk_dir / f"{chunk_id}.md"
            chunk_path.write_text(text, encoding="utf-8")

            # NER on full chunk text (PERSON/ORG)
            try:
                ents = extract_entities(text)
            except Exception:
                ents = []

            for ent in ents:
                entities_rows.append(
                    {
                        "Document": raw_path.name,
                        "Chunk": idx,  # 1-based index
                        "Entity": ent.get("text", ""),
                        "Label": ent.get("label", ""),
                        "Context": text[:400],
                    }
                )

            # Keep first 3 as preview
            if idx <= 3:
                if len(text) > 1000:
                    text_preview = text[:1000] + "\n...[truncated]"
                else:
                    text_preview = text
                sample_chunks.append(text_preview)

        # Save combined Markdown file
        combined_markdown = "\n\n---\n\n".join(combined_md_parts)
        md_path = self.markdown_dir / f"{doc_stem}.md"
        md_path.write_text(combined_markdown, encoding="utf-8")
        
        # per-document keywords (TF-IDF on just this doc)
        doc_keywords = self.extract_keywords_tfidf([combined_markdown], top_k=40)

        # Also write per-doc full.txt + chunks.json for easier inspection
        self._write_doc_artifacts(doc_chunk_dir, raw_path, chunks)

        # --- TF-IDF Keywords (fit within this document across chunks) ---
        doc_keywords: List[str] = []
        chunk_keywords_rows: List[Dict] = []

        try:
            # TF-IDF across chunks gives a "KeyBERT-ish" feel deterministically
            vectorizer = make_vectorizer(ngram_range=(1, 3), max_df=0.85, min_df=1)

            per_chunk_keywords = top_keywords_for_many_texts(
                combined_md_parts,   # each chunk text
                top_k=8,
                vectorizer=vectorizer,
            )

            # collect per chunk rows
            for idx, kws in enumerate(per_chunk_keywords, start=1):
                chunk_keywords_rows.append(
                    {
                        "Document": raw_path.name,
                        "Chunk": idx,
                        "Keywords": kws,
                    }
                )

            # doc-level keywords: stable union (first come, first served)
            seen = set()
            for kws in per_chunk_keywords:
                for k in kws:
                    if k not in seen:
                        seen.add(k)
                        doc_keywords.append(k)
                if len(doc_keywords) >= 20:
                    break

        except Exception:
            # keywords are optional; don't fail ingestion if sklearn/vectorizer errors
            doc_keywords = []
            chunk_keywords_rows = []

        # --- Date extraction + Gantt chart (document-level) ---
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
            # avoid OCR / Tesseract dependency for now
            return PdfParser(use_ocr="never")
        if ext == ".docx":
            return DocxParser()
        if ext in {".md", ".markdown"}:
            return MarkdownParser()
        if ext == ".csv":
            return CSVParser()
        if ext in {".xls", ".xlsx"}:
            return ExcelParser()

        raise ValueError(f"Unsupported file extension for ingestion: {ext}")

    def _build_pipeline_for_path(self, path: Path) -> BasePipeline:
        parser = self._get_parser_for_path(path)
        chunker = MarkdownChunker()
        return BasePipeline(parser=parser, chunker=chunker)

    def _write_doc_artifacts(self, doc_dir: Path, raw_path: Path, chunks: List) -> None:
        """
        For each document, create:
        - full.txt     : all chunks with markers
        - chunks.json  : JSON array of chunk texts + basic metadata
        """
        # full.txt
        try:
            full_txt_path = doc_dir / "full.txt"
            with full_txt_path.open("w", encoding="utf-8", newline="\n") as fh:
                for idx, ch in enumerate(chunks, start=1):
                    text = getattr(ch, "get_text", lambda: str(ch))()
                    fh.write(f"--- chunk {idx} ---\n{text}\n\n")
        except Exception:
            pass

        # chunks.json
        try:
            import json

            json_path = doc_dir / "chunks.json"
            data = []
            for idx, ch in enumerate(chunks, start=1):
                text = getattr(ch, "get_text", lambda: str(ch))()
                entry = {
                    "id": idx,
                    "source_file": raw_path.name,
                    "chunk_id": f"{raw_path.stem}_{idx}",
                    "text": text,
                    "metadata": getattr(ch, "metadata", {}) or {},
                }
                if hasattr(ch, "page_number"):
                    entry["page_number"] = ch.page_number
                if hasattr(ch, "section"):
                    entry["section"] = ch.section
                data.append(entry)

            json_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass

    def _extract_dates_and_gantt(
        self,
        source_filename: str,
        full_text: str,
    ) -> Tuple[List[Dict], str | None]:
        """
        Run DateExtractor on the full document text and return:
        - dates_rows: list of dicts for the dates table
        - gantt_b64: base64 PNG string or None
        """
        raw_dates = self.date_extractor.extract_dates_from_text(full_text)

        if not raw_dates:
            return [], None

        dates_list = []
        for idx, d in enumerate(raw_dates, start=1):
            dates_list.append(
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

        dates_df = self.date_extractor.create_dates_dataframe(dates_list)
        if dates_df is None or dates_df.empty:
            return [], None

        dates_rows = dates_df.to_dict(orient="records")

        img_buffer = self.date_extractor.create_gantt_chart(dates_df)
        if not img_buffer:
            return dates_rows, None

        gantt_b64 = base64.b64encode(img_buffer.getvalue()).decode("ascii")
        return dates_rows, gantt_b64
    
    def extract_keywords_tfidf(self, texts: List[str], top_k: int = 80) -> List[str]:
        extra_stop = {
            "a", "an", "the", "and", "or", "but", "if", "then", "else",
            "of", "to", "in", "on", "at", "by", "for", "from", "as",
            "is", "are", "was", "were", "be", "been", "being",
            "this", "that", "these", "those", "here", "there",
            "shall", "may", "must", "can", "will", "would", "should",
        }
        stop_words = set(ENGLISH_STOP_WORDS).union(extra_stop)

        token_pattern = r"(?u)\b[a-zA-Z][a-zA-Z]+\b"

        cleaned = []
        for t in texts:
            t = (t or "").strip()
            t = re.sub(r"\s+", " ", t)
            cleaned.append(t)

        # drop empties
        cleaned = [t for t in cleaned if t]
        n_docs = len(cleaned)
        if n_docs == 0:
            return []

        # ✅ critical: don’t use fractional max_df when n_docs is tiny
        # For 1 doc: allow all terms -> max_df must be 1.0 (or an int >= 1)
        # For 2 docs: 0.85*2=1.7 -> ok, but keep it safe anyway
        if n_docs <= 2:
            max_df = 1.0
            min_df = 1
        else:
            max_df = 0.85
            min_df = 1

        vec = TfidfVectorizer(
            lowercase=True,
            stop_words=list(stop_words),
            token_pattern=token_pattern,
            ngram_range=(1, 2),
            min_df=min_df,
            max_df=max_df,
            strip_accents="unicode",
        )

        X = vec.fit_transform(cleaned)
        feats = vec.get_feature_names_out()
        scores = X.sum(axis=0).A1

        ranked_idx = scores.argsort()[::-1]
        out, seen = [], set()

        for i in ranked_idx:
            term = feats[i].strip()
            if len(term) < 3:
                continue
            key = term.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(term)
            if len(out) >= top_k:
                break

        return out