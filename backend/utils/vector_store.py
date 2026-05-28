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
import os
import pickle
import numpy as np
import faiss
# from sentence_transformers import SentenceTransformer
from utils.embedding import SentenceTransformerEmbeddings as SentenceTransformer
# Add this import at the top of vector_store.py
from langchain_community.vectorstores.utils import maximal_marginal_relevance


logger = logging.getLogger(__name__)

# Multiplier for the FAISS search horizon before user-filtering.
# e.g. top_k=5, multiplier=30 → search top 150 globally, then filter by user.
_FILTER_SEARCH_MULTIPLIER = 30
_INDEX_PATH = "data/faiss.index"
_META_PATH  = "data/faiss_meta.pkl"
_EMBS_PATH  = "data/faiss_embs.pkl"

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
        self._load_or_build()
        logger.info("VectorStore ready — dim=%d  vectors=%d", self.dim, self.index.ntotal)

    def _build_fresh_index(self) -> None:
        self.index = faiss.IndexFlatIP(self.dim)
        self.metadata: List[Dict] = []
        self._embeddings: List[np.ndarray] = []

    def _load_or_build(self) -> None:
        if (
            os.path.exists(_INDEX_PATH)
            and os.path.exists(_META_PATH)
            and os.path.exists(_EMBS_PATH)
        ):
            try:
                logger.info("Restoring FAISS index from disk…")
                self.index = faiss.read_index(_INDEX_PATH)
                with open(_META_PATH, "rb") as f:
                    self.metadata = pickle.load(f)
                with open(_EMBS_PATH, "rb") as f:
                    self._embeddings = pickle.load(f)
                logger.info("Restored %d vectors from disk", self.index.ntotal)
            except Exception as e:
                logger.warning("Failed to restore index (%s) — rebuilding fresh", e)
                self._build_fresh_index()
        else:
            logger.info("No saved index found — building fresh")
            self._build_fresh_index()

    def _save(self) -> None:
        os.makedirs("data", exist_ok=True)
        faiss.write_index(self.index, _INDEX_PATH)
        with open(_META_PATH, "wb") as f:
            pickle.dump(self.metadata, f)
        with open(_EMBS_PATH, "wb") as f:
            pickle.dump(self._embeddings, f)
        logger.info("FAISS index persisted — %d vectors", self.index.ntotal)

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

        logger.info("Index now contains %d vectors (added %d)", self.index.ntotal, len(chunks))
        self._save()  # ← add
        return indices

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        threshold: float = 0.2,
        user_id: Optional[str] = None,
        mmr_fetch_k: int = 50,
        mmr_lambda: float = 0.6,
    ) -> List[Dict]:
        """
        MMR retrieval scoped to a specific user.

        mmr_lambda controls relevance/diversity tradeoff:
            1.0 = pure relevance (identical to cosine similarity search)
            0.0 = maximum diversity
            0.6 = good default for medical docs (avoids returning 5 near-identical chunks)
        """
        if self.index.ntotal == 0:
            return []

        q_emb = self.encoder.encode([query], convert_to_numpy=True)
        q_emb = self._normalise(q_emb).astype("float32")

        # Step 1 — fetch a wide candidate pool globally, then user-filter
        search_k = min(top_k * _FILTER_SEARCH_MULTIPLIER, self.index.ntotal)
        scores, indices = self.index.search(q_emb, search_k)

        # Step 2 — apply threshold + user filter on candidates
        candidate_indices = []
        candidate_embeddings = []

        for score, idx in zip(scores[0], indices[0]):
            if idx == -1:
                continue
            meta = self.metadata[idx]
            if user_id is not None and meta.get("user_id") != user_id:
                continue
            if float(score) < threshold:
                continue
            candidate_indices.append(idx)
            candidate_embeddings.append(self._embeddings[idx])

        if not candidate_indices:
            return []

        # Step 3 — run LangChain's MMR over the filtered candidates
        candidate_matrix = np.stack(candidate_embeddings, axis=0)  # (n_candidates, dim)

        mmr_selected = maximal_marginal_relevance(
            query_embedding=q_emb[0],           # shape (dim,)
            embedding_list=candidate_matrix,
            lambda_mult=mmr_lambda,
            k=min(top_k, len(candidate_indices)),
        )

        # Step 4 — build results in MMR-selected order
        results = []
        for pos in mmr_selected:
            idx = candidate_indices[pos]
            meta = self.metadata[idx]
            # recompute cosine score for this chunk (already normalised vectors)
            score = float(np.dot(q_emb[0], self._embeddings[idx]))
            results.append(
                {**meta, "similarity_score": round(score, 4)}
            )

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
        self._save()
        return removed

    def get_indexed_sources(self, user_id: Optional[str] = None) -> List[str]:
        """Return deduplicated source identifiers, optionally filtered by user."""
        return list({
            m.get("source", "unknown")
            for m in self.metadata
            if user_id is None or m.get("user_id") == user_id
        })