# utils/keywords_tfidf.py
from __future__ import annotations

import re
from typing import List, Tuple

import spacy
from sklearn.feature_extraction.text import TfidfVectorizer, ENGLISH_STOP_WORDS


# ---------------------------------------------------------------------
# spaCy setup (loaded once, lightweight)
# ---------------------------------------------------------------------
# We only need tokenization + POS + lemmatization
_nlp = spacy.load("en_core_web_sm", disable=["ner", "parser"])


# ---------------------------------------------------------------------
# Stopwords
# ---------------------------------------------------------------------
# Project / legal / audit-domain stopwords
DOMAIN_STOPWORDS = {
    "shall", "must", "may", "including", "hereby", "thereof", "herein",
    "section", "clause", "annex", "appendix", "schedule",
    "benefit", "type", "use", "using", "get", "gain", "provide",
}

URL_JUNK = {
    "http", "https", "www", "com", "net", "org", "io",
    "fwlink", "lnkid", "linkid",
}

# Combined stopwords (sklearn + domain)
ALL_STOPWORDS = set(ENGLISH_STOP_WORDS) | DOMAIN_STOPWORDS | URL_JUNK


# ---------------------------------------------------------------------
# spaCy-based linguistic cleaning
# ---------------------------------------------------------------------
def spacy_clean_for_tfidf(text: str) -> str:
    """
    Reduce text to lemmatized NOUN / PROPN tokens only.

    Removes:
    - stopwords (English + domain)
    - numbers
    - punctuation
    - short / low-signal tokens

    Output is a space-separated string suitable for TF-IDF.
    """
    if not text:
        return ""

    doc = _nlp(text)
    kept: List[str] = []

    for tok in doc:
        if tok.is_stop or tok.is_punct or tok.is_space or tok.like_num:
            continue
        if tok.pos_ not in {"NOUN", "PROPN"}:
            continue
        if tok.like_url or tok.like_email:
            continue

        lemma = tok.lemma_.lower().strip()

        if "." in lemma or "/" in lemma:   # kills com/fwlink, microsoft.com, paths, etc.
            continue
        if not lemma:
            continue
        if lemma in ALL_STOPWORDS:
            continue
        if len(lemma) < 3:
            continue

        kept.append(lemma)

    return " ".join(kept)


# ---------------------------------------------------------------------
# Safe TF-IDF vectorizer factory
# ---------------------------------------------------------------------
def make_vectorizer_for_corpus(
    doc_count: int,
    ngram_range: Tuple[int, int] = (1, 2),
    max_features: int = 5000,
) -> TfidfVectorizer:
    """
    Create a TF-IDF vectorizer that is SAFE for small corpora.

    Avoids the classic:
        ValueError: max_df corresponds to < documents than min_df
    """
    if doc_count <= 1:
        min_df = 1
        max_df = 1.0
    else:
        min_df = 1
        # ensure max_df never drops below min_df
        max_df = min(0.85, (doc_count - 1) / doc_count)

    return TfidfVectorizer(
        preprocessor=spacy_clean_for_tfidf,
        lowercase=True,
        ngram_range=ngram_range,
        max_features=max_features,
        min_df=min_df,
        max_df=max_df,
        sublinear_tf=True,
        norm="l2",
    )


# ---------------------------------------------------------------------
# Public API: taxonomy-style keyword extraction
# ---------------------------------------------------------------------
def extract_taxonomy_keywords(
    texts: List[str],
    top_k: int = 20,
) -> List[str]:
    """
    Extract clean, business-meaningful keywords across a corpus
    using spaCy-filtered TF-IDF.

    Intended for:
    - quick keyword chips
    - document taxonomy hints
    - graph search shortcuts

    Returns:
        A single ranked keyword list (highest signal first).
    """
    if not texts:
        return []

    vec = make_vectorizer_for_corpus(len(texts))
    X = vec.fit_transform(texts)

    if X.shape[1] == 0:
        return []

    # Average TF-IDF score across documents
    scores = X.mean(axis=0).A1
    features = vec.get_feature_names_out()

    ranked = sorted(
        zip(features, scores),
        key=lambda x: x[1],
        reverse=True,
    )

    return [term for term, _ in ranked[:top_k]]