"""
utils/vector_store.py
---------------------
FAISS-backed dense vector store with:
- Inner-product index (≡ cosine similarity on L2-normalised vectors)
- Medical-domain BioBERT sentence encoder
- Per-document soft-delete via IDMap reconstruction
- Similarity-threshold retrieval for hallucination mitigation
- Per-user retrieval filtering (user_id stored in chunk metadata)
"""

import logging
from typing import List, Dict, Optional, Set

import numpy as np
import faiss
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

# Multiplier for the FAISS search horizon before user-filtering.
# e.g. top_k=5, multiplier=30 → search top 150 globally, then filter by user.
_FILTER_SEARCH_MULTIPLIER = 30


class VectorStore:
    """
    Thread-safe (read-heavy) FAISS vector store.

    User scoping strategy
    ─────────────────────
    The single FAISS index holds vectors from ALL users. Each chunk's metadata
    contains a `user_id` field. During `retrieve()`, we search a wider pool
    (top_k × _FILTER_SEARCH_MULTIPLIER) and then post-filter by user_id before
    returning the final top_k results.

    This keeps the implementation simple and fast for the typical user counts in
    a medical RAG deployment. For very large multi-tenant deployments, consider
    one index-per-user or an IVF index with partitioning.
    """

    def __init__(self, embed_model_name: str):
        logger.info("Loading embedding model: %s", embed_model_name)
        self.encoder = SentenceTransformer(embed_model_name)
        self.dim: int = self.encoder.get_sentence_embedding_dimension()
        self._build_fresh_index()
        logger.info("VectorStore ready — dim=%d", self.dim)

    # ── Private helpers ───────────────────────────────────────────────────

    def _build_fresh_index(self) -> None:
        self.index = faiss.IndexFlatIP(self.dim)
        self.metadata: List[Dict] = []
        self._embeddings: List[np.ndarray] = []

    def _normalise(self, vecs: np.ndarray) -> np.ndarray:
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        return vecs / (norms + 1e-10)

    # ── Public interface ──────────────────────────────────────────────────

    @property
    def total_vectors(self) -> int:
        return self.index.ntotal

    def add_chunks(self, chunks: List[Dict]) -> List[int]:
        """
        Embed and index a list of chunk dicts.
        Each chunk MUST contain a `user_id` key for retrieval scoping.
        Returns the list of FAISS row indices assigned to these chunks.
        """
        if not chunks:
            return []

        texts = [c["text"] for c in chunks]
        logger.info("Embedding %d chunks…", len(texts))

        embeddings = self.encoder.encode(
            texts,
            show_progress_bar=False,
            batch_size=16,
            convert_to_numpy=True,
        )
        embeddings = self._normalise(embeddings).astype("float32")

        start_idx = self.index.ntotal
        self.index.add(embeddings)

        indices = list(range(start_idx, start_idx + len(chunks)))
        for chunk, emb in zip(chunks, embeddings):
            self.metadata.append(chunk)
            self._embeddings.append(emb)

        logger.info(
            "Index now contains %d vectors (added %d)",
            self.index.ntotal,
            len(chunks),
        )
        return indices

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        threshold: float = 0.35,
        user_id: Optional[str] = None,
    ) -> List[Dict]:
        """
        Dense passage retrieval scoped to a specific user.

        Searches a wider pool globally then post-filters by user_id so that
        users only ever see their own document chunks.
        """
        if self.index.ntotal == 0:
            return []

        q_emb = self.encoder.encode([query], convert_to_numpy=True)
        q_emb = self._normalise(q_emb).astype("float32")

        # Search wider to account for cross-user filtering
        search_k = min(top_k * _FILTER_SEARCH_MULTIPLIER, self.index.ntotal)
        scores, indices = self.index.search(q_emb, search_k)

        results: List[Dict] = []
        for score, idx in zip(scores[0], indices[0]):
            if idx == -1:
                continue
            if float(score) < threshold:
                break  # scores are sorted descending; no point continuing

            meta = self.metadata[idx]

            # ── User isolation ────────────────────────────────────────────
            if user_id is not None and meta.get("user_id") != user_id:
                continue

            results.append(
                {**meta, "similarity_score": round(float(score), 4)}
            )
            if len(results) == top_k:
                break

        return results

    def delete_by_indices(self, faiss_indices: List[int]) -> int:
        """
        Remove all vectors at the given FAISS row indices and rebuild the index.
        Ownership is guaranteed at the RAGService layer before this is called.
        """
        if not faiss_indices:
            return 0

        to_delete: Set[int] = set(faiss_indices)
        n_before = self.index.ntotal

        surviving_meta = []
        surviving_embs = []
        for i, (meta, emb) in enumerate(zip(self.metadata, self._embeddings)):
            if i not in to_delete:
                surviving_meta.append(meta)
                surviving_embs.append(emb)

        self._build_fresh_index()

        if surviving_embs:
            emb_matrix = np.stack(surviving_embs, axis=0).astype("float32")
            self.index.add(emb_matrix)
            self.metadata = surviving_meta
            self._embeddings = surviving_embs

        removed = n_before - self.index.ntotal
        logger.info(
            "Deleted %d vectors — index now has %d vectors",
            removed,
            self.index.ntotal,
        )
        return removed

    def get_indexed_sources(self, user_id: Optional[str] = None) -> List[str]:
        """Return deduplicated source identifiers, optionally filtered by user."""
        return list({
            m.get("source", "unknown")
            for m in self.metadata
            if user_id is None or m.get("user_id") == user_id
        })