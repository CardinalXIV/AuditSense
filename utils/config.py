# utils/config.py
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Everything under ./data locally; override base in MAESTRO with env var if needed
DATA_ROOT = Path(os.getenv("AUDIT_PIPELINE_DATA_ROOT",
                           str(PROJECT_ROOT / "data")))

RAW_DIR        = DATA_ROOT / "raw"
MD_DIR         = DATA_ROOT / "markdown"
CHUNK_DIR      = DATA_ROOT / "chunks"
EXTRACTION_DIR = DATA_ROOT / "extraction"
KG_DIR         = DATA_ROOT / "kg"

OUTPUT_DIR     = PROJECT_ROOT / "output"

for p in [RAW_DIR, MD_DIR, CHUNK_DIR, EXTRACTION_DIR, KG_DIR, OUTPUT_DIR]:
    p.mkdir(parents=True, exist_ok=True)



