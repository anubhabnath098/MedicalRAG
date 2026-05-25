"""
utils/chunker.py
----------------
Semantic sliding-window text chunker.
Splits on sentence boundaries (NLTK) then groups into word-count windows
with configurable overlap to prevent mid-clause cuts.
"""

import re
from typing import List, Dict

import nltk

# Ensure punkt tokeniser data is available
for resource in ("punkt", "punkt_tab"):
    try:
        nltk.data.find(f"tokenizers/{resource}")
    except LookupError:
        nltk.download(resource, quiet=True)

from nltk.tokenize import sent_tokenize


class SemanticChunker:
    """
    Sliding-window semantic chunker.

    Algorithm:
    1. Normalise whitespace.
    2. Tokenise into sentences (NLTK punkt).
    3. Accumulate sentences until the word budget is exceeded.
    4. Emit chunk; retain the last `overlap` words as carry-over context.
    5. Repeat until all sentences are consumed.
    """

    def __init__(self, chunk_size: int = 300, overlap: int = 50):
        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk(self, text: str, source_name: str) -> List[Dict]:
        """
        Parameters
        ----------
        text        : Raw document text.
        source_name : Identifier embedded in each chunk's metadata
                      (typically the document UUID or filename).

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

        sentences = sent_tokenize(text)
        chunks: List[Dict] = []
        current_words: List[str] = []
        chunk_id = 0

        for sent in sentences:
            words = sent.split()
            if len(current_words) + len(words) > self.chunk_size and current_words:
                chunk_text = " ".join(current_words)
                chunks.append(
                    {
                        "id": f"{source_name}_chunk_{chunk_id}",
                        "text": chunk_text,
                        "source": source_name,
                        "word_cnt": len(current_words),
                    }
                )
                chunk_id += 1
                # Slide: carry over the last `overlap` words as context seed
                carry = current_words[-self.overlap :]
                current_words = carry + words
            else:
                current_words.extend(words)

        # Flush the trailing window
        if current_words:
            chunks.append(
                {
                    "id": f"{source_name}_chunk_{chunk_id}",
                    "text": " ".join(current_words),
                    "source": source_name,
                    "word_cnt": len(current_words),
                }
            )

        return chunks
