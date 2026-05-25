"""
services/rag_service.py
-----------------------
Top-level RAG pipeline orchestrator — SQLite-backed, user-scoped.
v2: Every method is scoped to a user_id extracted from the JWT.

Owns:
- The FAISS VectorStore singleton (shared index, per-user filtering)
- The MemoryManager singleton
- The GeminiService (OCR + summarisation)
- The GroqService (chat + memory extraction)
- Document registry  → SQLite: documents + document_faiss_indices tables
- Chat sessions      → SQLite: chat_sessions + chat_history tables
"""

import json
import logging
from datetime import datetime
from typing import List, Optional

from config import settings
from database import get_connection
from models.schemas import (
    ChatHistoryEntry,
    ChatResponse,
    ChatSession,
    ChatSessionDetailResponse,
    ChatSessionListResponse,
    DeleteDocumentResponse,
    DocumentRecord,
    DocumentSummary,
    MemoryEntry,
    RetrievedChunk,
    UploadResponse,
    new_uuid,
)
from services.gemini_service import GeminiService
from services.groq_service import GroqService
from utils.chunker import SemanticChunker
from utils.memory_manager import MemoryManager
from utils.vector_store import VectorStore

logger = logging.getLogger(__name__)


class RAGService:
    """Singleton orchestrator for the Medical RAG pipeline."""

    def __init__(self):
        logger.info("Initialising RAGService…")
        settings.data_dir.mkdir(parents=True, exist_ok=True)

        self.vector_store = VectorStore(settings.embed_model)
        self.memory = MemoryManager()
        self.gemini = GeminiService()
        self.groq = GroqService()
        self.chunker = SemanticChunker(
            chunk_size=settings.chunk_size,
            overlap=settings.chunk_overlap,
        )

        total_docs = self._count_documents()
        logger.info("RAGService ready — %d total documents in DB", total_docs)

    # ══════════════════════════════════════════════════════════════════════
    # Internal helpers
    # ══════════════════════════════════════════════════════════════════════

    def _count_documents(self) -> int:
        with get_connection() as conn:
            row = conn.execute("SELECT COUNT(*) FROM documents").fetchone()
        return row[0]

    def _fetch_document_record(
        self, doc_id: str, user_id: str
    ) -> Optional[DocumentRecord]:
        """Fetch a document record — returns None if not found OR not owned by user."""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM documents WHERE id = ? AND user_id = ?",
                (doc_id, user_id),
            ).fetchone()
            if row is None:
                return None
            indices = [
                r["faiss_index"]
                for r in conn.execute(
                    "SELECT faiss_index FROM document_faiss_indices WHERE document_id = ?",
                    (doc_id,),
                ).fetchall()
            ]
        return self._row_to_record(row, indices)

    @staticmethod
    def _row_to_record(row, faiss_indices: List[int]) -> DocumentRecord:
        summary = DocumentSummary(
            core_content=row["core_content"] or "",
            doctor_concerned=row["doctor_concerned"] or "Not mentioned",
            date_time=row["date_time"] or "Not mentioned",
            document_type=row["document_type"] or "Other",
        )
        return DocumentRecord(
            id=row["id"],
            filename=row["filename"],
            uploaded_at=row["uploaded_at"],
            chunk_count=row["chunk_count"],
            char_count=row["char_count"],
            summary=summary,
            faiss_indices=faiss_indices,
        )

    # ══════════════════════════════════════════════════════════════════════
    # Document operations
    # ══════════════════════════════════════════════════════════════════════

    async def ingest_pdf(
        self, pdf_bytes: bytes, filename: str, user_id: str
    ) -> UploadResponse:
        """OCR → chunk → embed → summarise → persist to SQLite (user-scoped)."""
        logger.info(
            "Ingesting PDF for user=%s: %s (%d bytes)", user_id[:8], filename, len(pdf_bytes)
        )

        # Step 1 — OCR
        extracted_text = self.gemini.extract_text_from_pdf(pdf_bytes, filename)
        if not extracted_text.strip():
            raise ValueError(f"Gemini OCR returned empty text for '{filename}'.")

        # Step 2 — Chunk
        doc_id = new_uuid()
        chunks = self.chunker.chunk(extracted_text, source_name=doc_id)
        logger.info("Chunked '%s' into %d segments", filename, len(chunks))

        # Step 3 — Inject user_id into each chunk for FAISS-level scoping
        for chunk in chunks:
            chunk["user_id"] = user_id

        # Step 4 — Embed & index
        faiss_indices = self.vector_store.add_chunks(chunks)

        # Step 5 — Summarise
        summary = self.gemini.summarise_document(extracted_text)

        # Step 6 — Persist to SQLite
        uploaded_at = datetime.now().isoformat()
        with get_connection() as conn:
            conn.execute(
                """INSERT INTO documents
                   (id, user_id, filename, uploaded_at, chunk_count, char_count,
                    core_content, doctor_concerned, date_time, document_type)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    doc_id, user_id, filename, uploaded_at,
                    len(chunks), len(extracted_text),
                    summary.core_content, summary.doctor_concerned,
                    summary.date_time, summary.document_type,
                ),
            )
            if faiss_indices:
                conn.executemany(
                    "INSERT INTO document_faiss_indices (document_id, faiss_index) VALUES (?, ?)",
                    [(doc_id, idx) for idx in faiss_indices],
                )
            conn.commit()

        # Step 7 — Log to patient memory
        self.memory.add(
            user_id=user_id,
            category="GENERAL",
            fact=(
                f"Document ingested: '{filename}' ({len(chunks)} chunks). "
                f"Type: {summary.document_type}. Doctor: {summary.doctor_concerned}."
            ),
            source="auto",
        )

        logger.info(
            "Ingestion complete — user=%s doc_id=%s file=%s",
            user_id[:8], doc_id, filename,
        )
        return UploadResponse(
            document_id=doc_id,
            filename=filename,
            chunk_count=len(chunks),
            summary=summary,
        )

    def delete_document(self, document_id: str, user_id: str) -> DeleteDocumentResponse:
        """Remove a document's embeddings and SQL record. Enforces ownership."""
        record = self._fetch_document_record(document_id, user_id)
        if record is None:
            # Could be not found OR not owned — return 404 either way (no info leakage)
            raise KeyError(f"Document '{document_id}' not found.")

        removed = self.vector_store.delete_by_indices(record.faiss_indices)
        logger.info(
            "Scrubbed %d vectors for doc '%s' (%s) — user=%s",
            removed, record.filename, document_id, user_id[:8],
        )

        with get_connection() as conn:
            conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))
            conn.commit()

        return DeleteDocumentResponse(
            document_id=document_id,
            message=(
                f"Document '{record.filename}' deleted. "
                f"{removed} embedding vectors removed from the index."
            ),
        )

    def list_documents(self, user_id: str) -> List[DocumentRecord]:
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM documents WHERE user_id = ? ORDER BY uploaded_at DESC",
                (user_id,),
            ).fetchall()
            records = []
            for row in rows:
                indices = [
                    r["faiss_index"]
                    for r in conn.execute(
                        "SELECT faiss_index FROM document_faiss_indices WHERE document_id = ?",
                        (row["id"],),
                    ).fetchall()
                ]
                records.append(self._row_to_record(row, indices))
        return records

    # ══════════════════════════════════════════════════════════════════════
    # Session operations
    # ══════════════════════════════════════════════════════════════════════

    def create_session(
        self, user_id: str, title: Optional[str] = None
    ) -> ChatSession:
        now = datetime.now().isoformat()
        session = ChatSession(title=title, created_at=now, updated_at=now)
        with get_connection() as conn:
            conn.execute(
                """INSERT INTO chat_sessions (id, user_id, title, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (session.id, user_id, session.title, session.created_at, session.updated_at),
            )
            conn.commit()
        logger.info(
            "Created session id=%s user=%s title=%s", session.id, user_id[:8], session.title
        )
        return session

    def get_session(
        self, session_id: str, user_id: str
    ) -> Optional[ChatSessionDetailResponse]:
        """Return session + history only if it belongs to the requesting user."""
        with get_connection() as conn:
            sess_row = conn.execute(
                "SELECT * FROM chat_sessions WHERE id = ? AND user_id = ?",
                (session_id, user_id),
            ).fetchone()
            if sess_row is None:
                return None
            hist_rows = conn.execute(
                "SELECT * FROM chat_history WHERE session_id = ? ORDER BY timestamp",
                (session_id,),
            ).fetchall()

        session = ChatSession(**dict(sess_row))
        history = []
        for r in hist_rows:
            meta = json.loads(r["metadata"]) if r["metadata"] else None
            history.append(
                ChatHistoryEntry(
                    id=r["id"],
                    session_id=r["session_id"],
                    role=r["role"],
                    content=r["content"],
                    timestamp=r["timestamp"],
                    metadata=meta,
                )
            )
        return ChatSessionDetailResponse(
            session=session, history=history, total_turns=len(history)
        )

    def list_sessions(self, user_id: str) -> ChatSessionListResponse:
        with get_connection() as conn:
            rows = conn.execute(
                """SELECT * FROM chat_sessions WHERE user_id = ?
                   ORDER BY updated_at DESC""",
                (user_id,),
            ).fetchall()
        sessions = [ChatSession(**dict(r)) for r in rows]
        return ChatSessionListResponse(sessions=sessions, total=len(sessions))

    def delete_session(self, session_id: str, user_id: str) -> bool:
        """Delete session only if it belongs to the requesting user."""
        with get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM chat_sessions WHERE id = ? AND user_id = ?",
                (session_id, user_id),
            )
            conn.commit()
        deleted = cursor.rowcount > 0
        if deleted:
            logger.info("Deleted session id=%s user=%s", session_id, user_id[:8])
        return deleted

    # ══════════════════════════════════════════════════════════════════════
    # Chat
    # ══════════════════════════════════════════════════════════════════════

    def chat(self, query: str, session_id: str, user_id: str) -> ChatResponse:
        """
        Full RAG inference pipeline scoped to a user and session.

        1. Verify session exists AND belongs to user
        2. Retrieve top-k chunks (user-isolated FAISS search)
        3. Load this user's patient memory as context
        4. Generate grounded answer (Groq)
        5. Auto-extract + persist new memory entries for this user
        6. Persist both turns to chat_history
        7. Update session.updated_at
        8. Return ChatResponse
        """
        # Step 1 — Verify session ownership
        with get_connection() as conn:
            sess = conn.execute(
                "SELECT id FROM chat_sessions WHERE id = ? AND user_id = ?",
                (session_id, user_id),
            ).fetchone()
        if sess is None:
            raise KeyError(f"Session '{session_id}' not found.")

        # Step 2 — Retrieve user-scoped chunks
        raw_chunks = self.vector_store.retrieve(
            query=query,
            top_k=settings.top_k,
            threshold=settings.similarity_thresh,
            user_id=user_id,
        )

        # Map source UUIDs → filenames (only this user's documents)
        with get_connection() as conn:
            doc_rows = conn.execute(
                "SELECT id, filename FROM documents WHERE user_id = ?", (user_id,)
            ).fetchall()
        doc_id_to_name = {r["id"]: r["filename"] for r in doc_rows}

        enriched_chunks = []
        for c in raw_chunks:
            enriched = dict(c)
            enriched["source"] = doc_id_to_name.get(c["source"], c["source"])
            enriched_chunks.append(enriched)

        # Step 3 — User-scoped patient memory
        patient_memory = self.memory.as_context_string(user_id=user_id)

        # Step 4 — LLM answer
        indexed_doc_names = list(doc_id_to_name.values())
        llm_result = self.groq.answer(
            query=query,
            retrieved_chunks=enriched_chunks,
            patient_memory=patient_memory,
            indexed_docs=indexed_doc_names,
        )
        answer_text = llm_result["answer"]

        # Step 5 — Memory extraction + persistence (user-scoped)
        raw_entries = self.groq.extract_memory(query, answer_text)
        new_memory_entries: List[MemoryEntry] = []
        if raw_entries:
            new_memory_entries = self.memory.batch_add(
                raw_entries, user_id=user_id, source="auto"
            )
            logger.info(
                "Auto-persisted %d memory entries — user=%s",
                len(new_memory_entries), user_id[:8],
            )

        # Step 6 — Persist chat turns
        ts = datetime.now().isoformat()
        user_msg_id = new_uuid()
        assistant_msg_id = new_uuid()
        assistant_meta = json.dumps({
            "sources_cited": llm_result.get("sources_cited", []),
            "confidence": llm_result.get("confidence"),
            "disclaimer": llm_result.get("disclaimer"),
            "chunks_retrieved": len(enriched_chunks),
            "new_memory_count": len(new_memory_entries),
            # persist full data for frontend re-hydration
            "retrieved_chunks": [
                {
                    "source": c["source"],
                    "text": c["text"],
                    "similarity_score": c["similarity_score"],
                }
                for c in enriched_chunks
            ],
            "new_memory_entries": [
                {
                    "id": e.id,
                    "category": e.category,
                    "fact": e.fact,
                    "created_at": e.created_at,
                    "updated_at": e.updated_at,
                    "source": e.source,
                }
                for e in new_memory_entries
            ],
        })

        with get_connection() as conn:
            conn.executemany(
                """INSERT INTO chat_history
                   (id, session_id, role, content, timestamp, metadata)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [
                    (user_msg_id, session_id, "user", query, ts, None),
                    (assistant_msg_id, session_id, "assistant", answer_text, ts, assistant_meta),
                ],
            )
            # Step 7 — Touch session timestamp
            conn.execute(
                "UPDATE chat_sessions SET updated_at = ? WHERE id = ?",
                (ts, session_id),
            )
            conn.commit()

        # Step 8 — Return
        return ChatResponse(
            session_id=session_id,
            query=query,
            answer=answer_text,
            retrieved_chunks=[
                RetrievedChunk(
                    source=c["source"],
                    text=c["text"],
                    similarity_score=c["similarity_score"],
                )
                for c in enriched_chunks
            ],
            chunks_retrieved=len(enriched_chunks),
            new_memory_entries=new_memory_entries,
        )
    
    def rename_session(self, session_id: str, title: str, user_id: str) -> Optional[ChatSession]:
        with get_connection() as conn:
            cursor = conn.execute(
                "UPDATE chat_sessions SET title = ? WHERE id = ? AND user_id = ?",
                (title, session_id, user_id),
            )
            conn.commit()
            if cursor.rowcount == 0:
                return None
            row = conn.execute(
                "SELECT * FROM chat_sessions WHERE id = ?", (session_id,)
            ).fetchone()
        return ChatSession(**dict(row))