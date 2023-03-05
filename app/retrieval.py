"""Local lexical and fitted latent retrieval; scores are rankings, not probabilities."""

import re

import numpy as np
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer
from sklearn.preprocessing import normalize

WORDS = re.compile(r"[^\W_]+", re.UNICODE)


def query_terms(query: str) -> list[str]:
    """Only literal FTS tokens, never caller-supplied MATCH syntax."""
    return [word[:64] for word in WORDS.findall(query.lower()) if word not in ENGLISH_STOP_WORDS][
        :32
    ]


class LatentIndex:
    """A revision-scoped, bounded local TF-IDF/SVD fit over live chunk text."""

    def __init__(self, chunks: list[dict]):
        self.ids = [chunk["id"] for chunk in chunks[:1000]]
        self.vectorizer = TfidfVectorizer(stop_words="english", max_features=10000)
        self.matrix = None
        self.svd = None
        if not self.ids:
            return
        try:
            matrix = self.vectorizer.fit_transform(chunk["text"] for chunk in chunks[:1000])
        except ValueError:  # No meaningful terms in the live corpus.
            return
        if min(matrix.shape) > 1:
            self.svd = TruncatedSVD(n_components=min(64, min(matrix.shape) - 1), random_state=0)
            self.matrix = normalize(self.svd.fit_transform(matrix))
        else:
            self.matrix = normalize(matrix)

    def ranks(
        self, query: str, allowed: set[str] | None, owners: dict[str, str]
    ) -> list[tuple[str, float]]:
        if self.matrix is None or not query_terms(query):
            return []
        vector = self.vectorizer.transform([query])
        if vector.nnz == 0:
            return []
        vector = self.svd.transform(vector) if self.svd is not None else vector
        vector = normalize(vector)
        scores = self.matrix @ vector.T
        values = np.asarray(scores.toarray() if hasattr(scores, "toarray") else scores).reshape(-1)
        # SVD can yield nonzero similarities for terms that never co-occur; these are
        # deliberately shown as latent associations, not confidence estimates.
        ranked = [
            (chunk_id, float(score))
            for chunk_id, score in zip(self.ids, values, strict=True)
            if np.isfinite(score)
            and score > 1e-9
            and (allowed is None or owners[chunk_id] in allowed)
        ]
        return sorted(ranked, key=lambda item: (-item[1], item[0]))[:100]


def fuse(lexical: list[tuple[str, float]], latent: list[tuple[str, float]]) -> list[dict]:
    """Reciprocal-rank fusion, k=60, with deterministic chunk-ID ties."""
    hits: dict[str, dict] = {}
    for key, ranked in (("lexical_rank", lexical), ("latent_rank", latent)):
        for rank, (chunk_id, _) in enumerate(ranked, 1):
            hit = hits.setdefault(chunk_id, {"chunk_id": chunk_id, "score": 0.0})
            hit[key] = rank
            hit["score"] += 1 / (60 + rank)
    return sorted(hits.values(), key=lambda item: (-item["score"], item["chunk_id"]))
