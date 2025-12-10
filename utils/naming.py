# utils/naming.py
import re
import hashlib
from pathlib import Path


def _clean_stem(filename: str) -> str:
    """
    Turn '01 ITQ Office Equipment (MOF).pdf'
    into '01_ITQ_Office_Equipment_MOF'
    """
    stem = Path(filename).stem
    stem = stem.strip()
    stem = stem.replace(" ", "_")
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", stem)  # kill weird chars
    stem = re.sub(r"_+", "_", stem)                # squash multiple _
    return stem.strip("_")


def short_name_hash(name: str, length: int = 6) -> str:
    """
    Deterministic short checksum for a given name.
    6 hex chars => 1 in 16M collision chance.
    """
    return hashlib.sha1(name.encode("utf-8")).hexdigest()[:length]


def make_base_id(filename: str, length: int = 6) -> str:
    """
    Main API: given an original filename, return a nice base id.

    '01_ITQ_Office_Equipment_MOF_Demo.pdf'
    -> '01_ITQ_Office_Equipment_MOF_Demo__a1f9cd'
    """
    stem = _clean_stem(filename)
    h = short_name_hash(stem, length=length)
    return f"{stem}__{h}"