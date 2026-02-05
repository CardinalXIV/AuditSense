# utils/config.py
from __future__ import annotations

import os
from pathlib import Path
from typing import Final

from dotenv import load_dotenv

load_dotenv()


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[1]
DATA_ROOT: Final[Path] = Path(
    os.getenv("AUDIT_PIPELINE_DATA_ROOT", str(PROJECT_ROOT / "data"))
).expanduser()

RAW_DIR: Final[Path] = DATA_ROOT / "raw"
MD_DIR: Final[Path] = DATA_ROOT / "markdown"
CHUNK_DIR: Final[Path] = DATA_ROOT / "chunks"
EXTRACTION_DIR: Final[Path] = DATA_ROOT / "extraction"
KG_DIR: Final[Path] = DATA_ROOT / "kg"
OUTPUT_DIR: Final[Path] = Path(
    os.getenv("AUDIT_PIPELINE_OUTPUT_ROOT", str(PROJECT_ROOT / "output"))
).expanduser()

ALLOWED_SUFFIXES: Final[set[str]] = {
    ".pdf",
    ".docx",
    ".csv",
    ".xlsx",
    ".xls",
    ".md",
    ".markdown",
}

SECRET_KEY: Final[str] = os.getenv("AUDITSENSE_SECRET_KEY", "dev-secret-change-me")
MAX_CONTENT_LENGTH: Final[int] = _env_int("MAX_CONTENT_LENGTH_MB", 50) * 1024 * 1024
MAX_TERM_MATCHES: Final[int] = _env_int("MAX_TERM_MATCHES", 60)

GRAPH_ENABLED: Final[bool] = _env_bool("GRAPH_ENABLED", True)
NEO4J_URI: Final[str] = os.getenv("NEO4J_URI", "neo4j://127.0.0.1:7687")
NEO4J_USER: Final[str] = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD: Final[str | None] = os.getenv("NEO4J_PASSWORD")

FLASK_HOST: Final[str] = os.getenv("FLASK_HOST", "127.0.0.1")
FLASK_PORT: Final[int] = _env_int("FLASK_PORT", 5000)
FLASK_DEBUG: Final[bool] = _env_bool("FLASK_DEBUG", False)


def ensure_directories() -> None:
    for path in [RAW_DIR, MD_DIR, CHUNK_DIR, EXTRACTION_DIR, KG_DIR, OUTPUT_DIR]:
        path.mkdir(parents=True, exist_ok=True)


ensure_directories()
