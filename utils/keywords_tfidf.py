# utils/keywords_tfidf.py
from __future__ import annotations

import re
from typing import List, Tuple, Optional

from sklearn.feature_extraction.text import TfidfVectorizer

# Keep this small and project-specific; you can expand later.
DOMAIN_STOPWORDS = {
    "shall", "must", "may", "including", "hereby", "thereof", "herein",
    "section", "clause", "annex", "appendix", "schedule",
}

_token_re = re.compile(r"[A-Za-z0-9]+(?:[-_/][A-Za-z0-9]+)*")

def _preprocess(text: str) -> str:
    if not text:
        return ""
    # keep hyphenated tokens, normalize whitespace
    text = text.replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text

def make_vectorizer(
    ngram_range: Tuple[int, int] = (1, 3),
    max_features: int = 20000,
    min_df: int = 1,
    max_df: float = 0.85,
) -> TfidfVectorizer:
    return TfidfVectorizer(
        preprocessor=_preprocess,
        token_pattern=_token_re.pattern,
        lowercase=True,
        stop_words=list(DOMAIN_STOPWORDS),
        ngram_range=ngram_range,
        max_features=max_features,
        min_df=min_df,
        max_df=max_df,
        sublinear_tf=True,   # helps tame repetition
        norm="l2",
    )

def top_keywords_for_text(
    text: str,
    top_k: int = 15,
    vectorizer: Optional[TfidfVectorizer] = None,
) -> List[str]:
    """
    If you only have ONE document, TF-IDF reduces to TF (IDF constant).
    Still useful, but best results come from fitting across multiple docs/chunks.
    """
    if not text or not text.strip():
        return []

    vec = vectorizer or make_vectorizer()
    X = vec.fit_transform([text])
    return _top_terms_from_row(X, vec, row=0, top_k=top_k)

def top_keywords_for_many_texts(
    texts: List[str],
    top_k: int = 15,
    vectorizer: Optional[TfidfVectorizer] = None,
) -> List[List[str]]:
    """
    Fit TF-IDF across MANY texts (docs or chunks), then return top_k keywords per text.
    This is the most 'KeyBERT-like' usage.
    """
    cleaned = [t for t in (texts or [])]
    if not cleaned:
        return []

    vec = vectorizer or make_vectorizer()
    X = vec.fit_transform(cleaned)

    out: List[List[str]] = []
    for i in range(X.shape[0]):
        out.append(_top_terms_from_row(X, vec, row=i, top_k=top_k))
    return out

def _top_terms_from_row(X, vec: TfidfVectorizer, row: int, top_k: int) -> List[str]:
    feature_names = vec.get_feature_names_out()
    row_vec = X.getrow(row)
    if row_vec.nnz == 0:
        return []

    # get top indices by tfidf weight
    pairs = zip(row_vec.indices, row_vec.data)
    top = sorted(pairs, key=lambda x: x[1], reverse=True)[:top_k]

    terms = [feature_names[idx] for idx, _ in top]

    # small “diversity” cleanup: drop terms that are substrings of earlier picks
    dedup: List[str] = []
    for t in terms:
        if any(t in prev or prev in t for prev in dedup):
            continue
        dedup.append(t)
    return dedup