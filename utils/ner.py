# utils/ner.py

from __future__ import annotations
from typing import List, Dict, Set, Tuple
import re

try:
    import spacy
except ModuleNotFoundError:
    spacy = None

if spacy is None:
    _nlp = None
else:
    try:
        _nlp = spacy.load("en_core_web_sm")
    except OSError:
        _nlp = spacy.blank("en")

CORE_ENTITY_LABELS = {"PERSON", "ORG", "GPE", "LOC", "FAC"}

BAD_CHARS = set('*"\'{}[]()<>:\\/|#@!~`+=')

# acronyms we know we want as ORG
ORG_ALLOW_ACRONYMS: Set[str] = {
    "MOF",
    # add "MAS", "IRAS", "GovTech", etc. as you see them
}

# phrases we never want as ORG
ORG_BLOCK_PHRASES: Set[str] = {
    "invitation to quote",
    "letter of award",
    "this letter of award",
    "the letter of award",
    "terms and conditions",
    "agreement",
    "annex",
    "annexes",
    "singapore time",
    "quote",
    "supply",
    "estimated quantity",
}

# words that signal a real org name
ORG_KEYWORDS: Set[str] = {
    "ministry",
    "department",
    "authority",
    "board",
    "council",
    "division",
    "corporate",
    "services",
    "government",
    "govt",
    "university",
    "hospital",
    "bank",
    "company",
    "co.",
    "corp",
    "corporation",
    "inc",
    "pte",
    "ltd",
    "llp",
    "llc",
    "agency",
    "office",
}

# vendor-style pattern: Something ... Pte Ltd / Pte. Ltd.
VENDOR_PATTERN = re.compile(
    r"\b([A-Z][A-Za-z0-9& ,./\-]+?\s+(?:Pte\.?|PTE\.?)\s+Ltd\.?)\b"
)
EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_PATTERN = re.compile(r"\b(?:\+?\d{1,3}[\s-]?)?(?:\(?\d{2,4}\)?[\s-]?)?\d{3,4}[\s-]?\d{3,4}\b")
URL_PATTERN = re.compile(r"\b(?:https?://|www\.)[A-Za-z0-9./?=_-]+\b", re.IGNORECASE)
ADDRESS_PATTERN = re.compile(
    r"\b\d{1,5}\s+[A-Za-z0-9.,' -]+?"
    r"(?:Street|St|Road|Rd|Avenue|Ave|Boulevard|Blvd|Lane|Ln|Drive|Dr|Way|Court|Ct|Place|Pl|Terrace|Ter|Highway|Hwy)\b"
    r"(?:,\s*[A-Za-z .'-]+){0,2}",
    re.IGNORECASE,
)


def clean_entity_text(text: str) -> str:
    """Remove surrounding special chars and normalize whitespace."""
    t = text.strip()
    t = re.sub(r"^[^A-Za-z0-9]+", "", t)
    t = re.sub(r"[^A-Za-z0-9]+$", "", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def contains_bad_chars(text: str) -> bool:
    return any(ch in BAD_CHARS for ch in text)


# --- PERSON heuristics -------------------------------------------------

def _looks_like_person(text: str) -> bool:
    """Conservative PERSON: 2–4 tokens, each starting with a capital letter."""
    parts = text.strip().split()
    if len(parts) < 2 or len(parts) > 4:
        return False

    for p in parts:
        if not p or not p[0].isupper():
            return False

    return True


# --- ORG heuristics ----------------------------------------------------

def _is_blocked_org(text: str) -> bool:
    lower = text.lower()
    for phrase in ORG_BLOCK_PHRASES:
        if phrase in lower:
            return True
    return False


def _looks_like_org(text: str) -> bool:
    """Conservative ORG filter."""
    t = text.strip()
    lower = t.lower()
    tokens = t.split()

    # Always keep known acronyms like MOF
    if t in ORG_ALLOW_ACRONYMS:
        return True

    # Hard blocklist phrases
    if _is_blocked_org(t):
        return False

    # Reject single-token ORGs unless in allowlist (kills QUOTE, Supply, etc.)
    if len(tokens) == 1:
        return False

    # If it contains any org-ish keyword, that's a strong positive
    if any(kw in lower for kw in ORG_KEYWORDS):
        return True

    # Fallback: allow 2–4 tokens that are mostly capitalised
    if 2 <= len(tokens) <= 4:
        caps_tokens = sum(1 for tok in tokens if tok and tok[0].isupper())
        if caps_tokens >= len(tokens) - 1:
            return True

    return False


# --- main API ----------------------------------------------------------

def extract_entities(text: str) -> List[Dict[str, str]]:
    if not text:
        return []

    entities_set: Set[Tuple[str, str]] = set()
    entities: List[Dict[str, str]] = []

    # 1) spaCy-based entities
    if _nlp is not None:
        doc = _nlp(text)
        for ent in doc.ents:
            if ent.label_ not in CORE_ENTITY_LABELS:
                continue

            raw = ent.text
            cleaned = clean_entity_text(raw)

            if not cleaned:
                continue

            if contains_bad_chars(cleaned):
                continue

            label = ent.label_

            if label == "PERSON":
                if not _looks_like_person(cleaned):
                    continue

            if label == "ORG":
                if not _looks_like_org(cleaned):
                    continue

            key = (cleaned, label)
            if key in entities_set:
                continue

            entities_set.add(key)
            entities.append(
                {
                    "text": cleaned,
                    "label": label,
                }
            )

    # 2) Regex fallback for vendor-style names (Pte Ltd)
    for match in VENDOR_PATTERN.finditer(text):
        vendor = clean_entity_text(match.group(1))
        if not vendor:
            continue
        key = (vendor, "ORG")
        if key in entities_set:
            continue
        entities_set.add(key)
        entities.append(
            {
                "text": vendor,
                "label": "ORG",
            }
        )

    # 3) Regex entities for contact/address intelligence.
    regex_entities = [
        (EMAIL_PATTERN, "EMAIL"),
        (PHONE_PATTERN, "PHONE"),
        (URL_PATTERN, "URL"),
        (ADDRESS_PATTERN, "ADDRESS"),
    ]
    for pattern, label in regex_entities:
        for match in pattern.finditer(text):
            value = clean_entity_text(match.group(0))
            if len(value) < 4:
                continue
            if label == "PHONE" and len(re.sub(r"\D", "", value)) < 7:
                continue
            key = (value, label)
            if key in entities_set:
                continue
            entities_set.add(key)
            entities.append(
                {
                    "text": value,
                    "label": label,
                }
            )

    return entities
