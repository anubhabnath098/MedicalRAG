"""
utils/chunker.py
----------------
Semantic sliding-window text chunker.
Splits on sentence boundaries (NLTK) then groups into word-count windows
with configurable overlap to prevent mid-clause cuts.
"""

from langchain_experimental.text_splitter import SemanticChunker
from utils.embedding import SentenceTransformerEmbeddings
from config import settings
import re
from typing import List, Dict


def semantic_chunk(
    text: str,
    source_name: str,
    embeddings=None,
    breakpoint_type: str = "percentile",  # or "standard_deviation", "interquartile"
    breakpoint_threshold: float = 60.0,
) -> List[Dict]:
    """
    Parameters
    ----------
    text                : Raw document text.
    source_name         : Identifier embedded in each chunk's metadata.
    embeddings          : LangChain-compatible embeddings instance.
    breakpoint_type     : Strategy for detecting semantic boundaries.
    breakpoint_threshold: Sensitivity of the boundary detector.

    Returns
    -------
    List of chunk dicts:
        {
            "id"       : "<source_name>_chunk_<n>",
            "text"     : "<chunk text>",
            "source"   : "<source_name>",
            "word_cnt" : <int>
        }
    """
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []

    if embeddings is None:
        embeddings = SentenceTransformerEmbeddings(settings.embed_model)

    splitter = SemanticChunker(
        embeddings,
        breakpoint_threshold_type=breakpoint_type,
        breakpoint_threshold_amount=breakpoint_threshold,
    )

    docs = splitter.create_documents([text])

    return [
        {
            "id": f"{source_name}_chunk_{i}",
            "text": doc.page_content,
            "source": source_name,
            "word_cnt": len(doc.page_content.split()),
        }
        for i, doc in enumerate(docs)
    ]
