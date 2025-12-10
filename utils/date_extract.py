# utils/date_extract.py

import re
import json

import matplotlib
matplotlib.use("Agg")

from pathlib import Path
from typing import List, Dict, Any, Optional
from io import BytesIO
from datetime import datetime

import pandas as pd
from dateutil import parser
import matplotlib.pyplot as plt
import numpy as np


class DateExtractor:
    """
    Deterministic date extractor working directly on chunk text.

    Designed to work with:
    - full_chunks.txt JSON produced by FileProcessor, or
    - any in-memory list of {"source_file", "document_chunk_id", "text", ...}
    """

    def __init__(self) -> None:
        # Date patterns for explicit regex fallback
        self.date_patterns = [
            # 10/01/2025, 1-2-25, etc.
            r'\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b',

            # 2 Jan 2026 / 02 Jan 2026
            r'\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{2,4}\b',

            # 2 January 2026 / 02 January 2026 (day first, full month)  👈 NEW
            r'\b\d{1,2}\s+'
            r'(?:January|February|March|April|May|June|July|August|September|October|November|December)'
            r'\s+\d{2,4}\b',

            # Jan 2 2026 / Jan 2, 2026
            r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{2,4}\b',

            # January 2 2026 / January 2, 2026
            r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December)'
            r'\s+\d{1,2},?\s+\d{2,4}\b',

            # 2026-01-02 style
            r'\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b',
        ]

        # PDF / OCR artefact cleanup
        self.cleanup_patterns = [
            (r'(\d)\s+(\d)', r'\1\2'),          # "2 0 2 3" -> "2023"
            (r'([A-Za-z])(\d)', r'\1 \2'),      # "March15" -> "March 15"
            (r'(\d)([A-Za-z])', r'\1 \2'),      # "15March" -> "15 March"
            (r'\s+', ' '),                      # collapse spaces
            (r'([A-Za-z])\s*,\s*(\d)', r'\1, \2'),
        ]

    # ---------- low-level helpers ----------

    def clean_text_for_pdf(self, text: str) -> str:
        cleaned = text
        for pattern, replacement in self.cleanup_patterns:
            cleaned = re.sub(pattern, replacement, cleaned)
        return cleaned.strip()

    def _find_potential_date_chunks(self, text: str) -> List[Dict[str, Any]]:
        """Find text fragments that might contain dates."""
        chunks: List[Dict[str, Any]] = []

        # Hint patterns – broad, used only to grab small surrounding chunks
        date_hint_patterns = [
            # Numeric-looking dates
            r'\b\d{1,4}[\s\-/]\d{1,4}[\s\-/]\d{1,4}\b',

            # Month first (short)
            r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[\s,]*\d{1,2}[\s,]*\d{2,4}\b',

            # Day first, short month
            r'\b\d{1,2}[\s,]*(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[\s,]*\d{2,4}\b',

            # Month first (full)
            r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December)'
            r'[\s,]*\d{1,2}[\s,]*\d{2,4}\b',

            # Day first, full month  👈 NEW
            r'\b\d{1,2}[\s,]*'
            r'(?:January|February|March|April|May|June|July|August|September|October|November|December)'
            r'[\s,]*\d{2,4}\b',
        ]

        for pattern in date_hint_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                start = max(0, match.start() - 10)
                end = min(len(text), match.end() + 10)
                chunk_text = text[start:end].strip()
                chunks.append(
                    {
                        "text": chunk_text,
                        "start": start,
                        "core_match": match.group(),
                    }
                )

        return self._remove_overlapping_chunks(chunks)

    def _remove_overlapping_chunks(
        self, chunks: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Remove overlapping chunks, prefer longer ones."""
        if not chunks:
            return chunks

        chunks.sort(key=lambda x: x["start"])
        filtered = [chunks[0]]

        for chunk in chunks[1:]:
            last = filtered[-1]
            last_end = last["start"] + len(last["text"])

            if chunk["start"] < last_end:
                # overlapping – keep longer
                if len(chunk["text"]) > len(last["text"]):
                    filtered[-1] = chunk
            else:
                filtered.append(chunk)

        return filtered

    def _dedupe_dates(self, dates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Deduplicate by formatted date; prefer dateutil over regex."""
        if not dates:
            return dates

        groups: Dict[str, List[Dict[str, Any]]] = {}
        for info in dates:
            key = info["formatted"]
            groups.setdefault(key, []).append(info)

        final: List[Dict[str, Any]] = []
        method_priority = {"dateutil_fuzzy": 2, "regex": 1}

        for key, items in groups.items():
            if len(items) == 1:
                final.append(items[0])
                continue

            best = max(
                items, key=lambda x: method_priority.get(x.get("method", "regex"), 0)
            )
            final.append(best)

        final.sort(key=lambda x: x["position"][0])
        return final

    # ---------- core extraction ----------

    def extract_dates_from_text(self, text: str) -> List[Dict[str, Any]]:
        """Extract all dates from a single text string."""
        all_dates: List[Dict[str, Any]] = []

        potential_chunks = self._find_potential_date_chunks(text)

        # Fallback: if hint patterns fail, just treat the whole text as one chunk
        if not potential_chunks:
            potential_chunks = [{
                "text": text,
                "start": 0,
                "core_match": "",
            }]

        for chunk_info in potential_chunks:
            chunk_text = chunk_info["text"]
            chunk_start = chunk_info["start"]

            cleaned = self.clean_text_for_pdf(chunk_text)
            chunk_dates: List[Dict[str, Any]] = []

            # 1) dateutil fuzzy parse on the cleaned chunk
            try:
                parsed = parser.parse(cleaned, fuzzy=True)
                chunk_dates.append(
                    {
                        "original_text": chunk_text,
                        "parsed_date": parsed,
                        "formatted": parsed.strftime("%Y-%m-%d"),
                        "position": (chunk_start, chunk_start + len(chunk_text)),
                        "context": text[
                            max(0, chunk_start - 50) : chunk_start + len(chunk_text) + 50
                        ],
                        "method": "dateutil_fuzzy",
                    }
                )
            except Exception:
                pass

            # 2) regex patterns inside the chunk
            for pattern in self.date_patterns:
                for match in re.finditer(pattern, cleaned, re.IGNORECASE):
                    try:
                        parsed_date = parser.parse(match.group(), fuzzy=False)
                        match_start = chunk_start + match.start()
                        chunk_dates.append(
                            {
                                "original_text": match.group(),
                                "parsed_date": parsed_date,
                                "formatted": parsed_date.strftime("%Y-%m-%d"),
                                "position": (
                                    match_start,
                                    match_start + len(match.group()),
                                ),
                                "context": text[
                                    max(0, match_start - 50) : match_start
                                    + len(match.group())
                                    + 50
                                ],
                                "method": "regex",
                            }
                        )
                    except Exception:
                        pass

            all_dates.extend(chunk_dates)

        return self._dedupe_dates(all_dates)

    # ---------- integration with our pipeline ----------

    def extract_from_chunks_list(
        self, chunks: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Extract dates from an in-memory list of chunk dicts.

        Expected dict schema (matches FileProcessor's all_chunks_data):
        {
            "chunk_id": str,
            "source_file": str,
            "document_chunk_id": int,
            "text": str,
            ... (optional extra metadata)
        }
        """
        results: List[Dict[str, Any]] = []

        for record in chunks:
            text = record.get("text", "")
            if not text:
                continue

            dates = self.extract_dates_from_text(text)
            for d in dates:
                results.append(
                    {
                        "source_file": record.get("source_file"),
                        "chunk_number": record.get("document_chunk_id"),
                        "date_text": d["original_text"],
                        "parsed_date": d["parsed_date"],
                        "formatted_date": d["formatted"],
                        "context": d["context"],
                        "method": d.get("method", "unknown"),
                    }
                )

        return results

    def extract_from_chunks_json(
        self, chunks_json_path: Path | str
    ) -> List[Dict[str, Any]]:
        """
        Convenience wrapper: read full_chunks.txt JSON from disk
        and run extraction over it.
        """
        path = Path(chunks_json_path)
        if not path.exists():
            raise FileNotFoundError(path)

        with path.open("r", encoding="utf-8") as f:
            chunks = json.load(f)

        return self.extract_from_chunks_list(chunks)

    # ---------- tabular & visual outputs ----------

    def create_dates_dataframe(self, dates_list: List[Dict]) -> pd.DataFrame:
        """Convert dates list to pandas DataFrame for tabular output.

        This is defensive: it tolerates missing keys and slightly different
        shapes for the date dictionaries.
        """
        if not dates_list:
            return pd.DataFrame(
                columns=["Document", "Chunk", "Date Found", "Parsed Date", "Method", "Context"]
            )

        rows = []
        for info in dates_list:
            # Try multiple key names for each field to be robust
            doc = (
                info.get("source_file")
                or info.get("Document")
                or info.get("document_name")
                or "Unknown"
            )

            chunk = (
                info.get("chunk_number")
                or info.get("Chunk")
                or info.get("chunk_index")
                or 0
            )

            date_found = (
                info.get("date_text")
                or info.get("Date Found")
                or info.get("original_text")
                or ""
            )

            parsed = (
                info.get("formatted_date")
                or info.get("Parsed Date")
                or ""
            )

            method = info.get("method", "unknown")

            ctx = (
                info.get("context")
                or info.get("Context")
                or ""
            )
            if isinstance(ctx, str) and len(ctx) > 100:
                ctx = ctx[:100] + "..."

            rows.append(
                {
                    "Document": doc,
                    "Chunk": chunk,
                    "Date Found": date_found,
                    "Parsed Date": parsed,
                    "Method": method,
                    "Context": ctx,
                }
            )

        df = pd.DataFrame(rows)

        # Best-effort sorting by date
        try:
            df["Parsed Date Temp"] = pd.to_datetime(
                df["Parsed Date"], format="%Y-%m-%d", errors="coerce"
            )
            df = df.sort_values(["Document", "Parsed Date Temp", "Chunk"])
            df = df.drop("Parsed Date Temp", axis=1)
        except Exception as e:
            print(f"Warning: Could not sort dates properly: {e}")

        return df

    def create_gantt_chart(
        self, dates_df: pd.DataFrame, width_cm: float = 18, height_cm: float = 12
    ) -> Optional[BytesIO]:
        """
        Create a Gantt-style chart of date ranges by document (month granularity).

        Returns a PNG image in a BytesIO buffer, or None if no dates.
        """
        if dates_df is None or dates_df.empty:
            return None

        df = dates_df.copy()
        df["Parsed Date"] = pd.to_datetime(
            df["Parsed Date"], format="%Y-%m-%d", errors="coerce"
        )
        df = df.dropna(subset=["Parsed Date"])
        if df.empty:
            return None

        df["Year-Month"] = df["Parsed Date"].dt.to_period("M")
        doc_ranges = df.groupby("Document")["Year-Month"].agg(["min", "max"]).reset_index()

        doc_ranges["start_date"] = doc_ranges["min"].dt.start_time
        doc_ranges["end_date"] = doc_ranges["max"].dt.end_time
        doc_ranges["duration_months"] = (doc_ranges["max"] - doc_ranges["min"]).apply(
            lambda x: x.n + 1
        )

        doc_ranges = doc_ranges.sort_values("start_date")

        fig, ax = plt.subplots(figsize=(width_cm / 2, height_cm / 2.54))

        colors = plt.cm.Set3(np.linspace(0, 1, len(doc_ranges)))
        y_positions: List[int] = []
        y_labels: List[str] = []

        for i, (_, row) in enumerate(doc_ranges.iterrows()):
            doc_name = row["Document"]
            start_date = row["start_date"]
            end_date = row["end_date"]
            duration_days = (end_date - start_date).days + 1

            display_name = doc_name[:35] + "..." if len(doc_name) > 35 else doc_name
            y_positions.append(i)
            y_labels.append(display_name)

            ax.barh(
                i,
                duration_days,
                left=start_date,
                height=0.6,
                color=colors[i],
                alpha=0.7,
                edgecolor="black",
                linewidth=0.5,
            )

            if row["duration_months"] == 1:
                date_text = row["min"].strftime("%b %Y")
            else:
                date_text = f"{row['min'].strftime('%b %Y')} - {row['max'].strftime('%b %Y')}"

            text_x = start_date + pd.Timedelta(days=duration_days / 2)
            ax.text(
                text_x,
                i,
                date_text,
                va="center",
                ha="center",
                fontsize=8,
                weight="bold",
                color="darkblue",
                bbox=dict(
                    boxstyle="round,pad=0.3", facecolor="white", alpha=0.8
                ),
            )

        ax.set_yticks(y_positions)
        ax.set_yticklabels(y_labels, fontsize=9, weight="bold")
        ax.tick_params(axis="y", which="major", pad=5)
        ax.set_xlabel("Timeline", fontsize=11, weight="bold")

        plt.subplots_adjust(left=0.25, right=0.95, top=0.72, bottom=0.15)

        total_docs = len(doc_ranges)
        earliest_date = doc_ranges["min"].min().strftime("%b %Y")
        latest_date = doc_ranges["max"].max().strftime("%b %Y")

        fig.text(
            0.5,
            0.92,
            "Document Date Ranges by Month/Year",
            ha="center",
            va="center",
            fontsize=13,
            weight="bold",
        )
        summary_text = f"Documents: {total_docs} | Period: {earliest_date} to {latest_date}"
        fig.text(
            0.5,
            0.82,
            summary_text,
            ha="center",
            va="center",
            fontsize=10,
            weight="bold",
            bbox=dict(
                boxstyle="round,pad=0.5", facecolor="lightgray", alpha=0.8
            ),
        )

        ax.grid(True, axis="x", alpha=0.3, linestyle="--")
        ax.set_axisbelow(True)

        buf = BytesIO()
        plt.savefig(
            buf, format="png", bbox_inches="tight", dpi=150, facecolor="white", edgecolor="none"
        )
        buf.seek(0)
        plt.close(fig)
        return buf