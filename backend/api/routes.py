"""
api/routes.py
-------------
All API route definitions for the Medical RAG backend.

Endpoints
─────────
Documents
  POST   /api/documents/upload          Upload PDF → Gemini OCR → FAISS → summary
  GET    /api/documents                  List all indexed documents
  DELETE /api/documents/{id}             Remove document + scrub FAISS embeddings

Chat Sessions
  POST   /api/chat/sessions              Create a new chat session
  GET    /api/chat/sessions              List all sessions
  GET    /api/chat/sessions/{id}         Retrieve session + full history by session ID
  DELETE /api/chat/sessions/{id}         Delete a session and all its history

Chat
  POST   /api/chat                       RAG query within a session

Memory
  GET    /api/memory                     All patient memory entries
  GET    /api/health/memory/list         Alias used by frontend
  POST   /api/memory                     Manually add a memory entry
  PUT    /api/memory/{id}                Edit an existing memory entry
  DELETE /api/memory/{id}                Delete a specific memory entry
"""

import logging
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import JSONResponse

from models.schemas import (
    AddMemoryRequest,
    ChatRequest,
    ChatResponse,
    ChatSessionDetailResponse,
    ChatSessionListResponse,
    CreateSessionRequest,
    DeleteDocumentResponse,
    DocumentListResponse,
    MemoryActionResponse,
    MemoryResponse,
    UpdateMemoryRequest,
    UploadResponse,
    ChatSession,
)
from services.auth_service import get_current_user
from services.rag_service import RAGService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


# ── Dependencies ─────────────────────────────────────────────────────────────

def get_rag_service(request: Request) -> RAGService:
    return request.app.state.rag_service


RAGDep = Annotated[RAGService, Depends(get_rag_service)]
UserDep = Annotated[dict, Depends(get_current_user)]


# ════════════════════════════════════════════════════════════════════════════════
# DOCUMENT endpoints
# ════════════════════════════════════════════════════════════════════════════════

@router.post(
    "/documents/upload",
    response_model=UploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a PDF medical document",
    tags=["Documents"],
)
async def upload_document(
    rag: RAGDep,
    current_user: UserDep,
    file: UploadFile = File(..., description="PDF file to upload (max 20 MB)"),
) -> UploadResponse:
    """Upload a PDF → Gemini OCR → FAISS embedding → structured summary."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Only PDF files are accepted.",
        )

    pdf_bytes = await file.read()

    if len(pdf_bytes) == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Uploaded file is empty.",
        )
    if len(pdf_bytes) > 20 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File exceeds the 20 MB limit.",
        )

    try:
        return await rag.ingest_pdf(pdf_bytes, file.filename, user_id=current_user["user_id"])
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except Exception as exc:
        logger.exception("Unexpected error during PDF ingestion")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ingestion failed: {exc}",
        )


@router.get(
    "/documents",
    response_model=DocumentListResponse,
    summary="List all indexed documents",
    tags=["Documents"],
)
def list_documents(rag: RAGDep, current_user: UserDep) -> DocumentListResponse:
    docs = rag.list_documents(user_id=current_user["user_id"])
    return DocumentListResponse(documents=docs, total=len(docs))


@router.delete(
    "/documents/{document_id}",
    response_model=DeleteDocumentResponse,
    summary="Delete a document and scrub its embeddings",
    tags=["Documents"],
)
def delete_document(document_id: str, rag: RAGDep, current_user: UserDep) -> DeleteDocumentResponse:
    try:
        return rag.delete_document(document_id, user_id=current_user["user_id"])
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except Exception as exc:
        logger.exception("Error deleting document %s", document_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Deletion failed: {exc}",
        )


# ════════════════════════════════════════════════════════════════════════════════
# CHAT SESSION endpoints
# ════════════════════════════════════════════════════════════════════════════════

@router.post(
    "/chat/sessions",
    response_model=ChatSession,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new chat session",
    tags=["Chat Sessions"],
)
def create_session(body: CreateSessionRequest, rag: RAGDep, current_user: UserDep) -> ChatSession:
    """
    Create a new chat session. Returns a session_id that must be supplied
    with every subsequent POST /api/chat call for this conversation.
    """
    return rag.create_session(title=body.title, user_id=current_user["user_id"])


@router.get(
    "/chat/sessions",
    response_model=ChatSessionListResponse,
    summary="List all chat sessions",
    tags=["Chat Sessions"],
)
def list_sessions(rag: RAGDep, current_user: UserDep) -> ChatSessionListResponse:
    """Return all sessions ordered by most-recently updated."""
    return rag.list_sessions(user_id=current_user["user_id"])


@router.get(
    "/chat/sessions/{session_id}",
    response_model=ChatSessionDetailResponse,
    summary="Retrieve a session and its full conversation history",
    tags=["Chat Sessions"],
)
def get_session(session_id: str, rag: RAGDep, current_user: UserDep) -> ChatSessionDetailResponse:
    """Fetch the session metadata + every chat turn for the given session ID."""
    result = rag.get_session(session_id, user_id=current_user["user_id"])
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session '{session_id}' not found.",
        )
    return result


@router.delete(
    "/chat/sessions/{session_id}",
    summary="Delete a chat session and all its history",
    tags=["Chat Sessions"],
)
def delete_session(session_id: str, rag: RAGDep, current_user: UserDep) -> JSONResponse:
    """
    Permanently delete a chat session and every message it contains.
    Auto-extracted memory entries derived from this session are retained.
    """
    deleted = rag.delete_session(session_id, user_id=current_user["user_id"])
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session '{session_id}' not found.",
        )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "success": True,
            "session_id": session_id,
            "message": "Session and all associated history deleted.",
        },
    )


# ════════════════════════════════════════════════════════════════════════════════
# CHAT endpoint
# ════════════════════════════════════════════════════════════════════════════════

@router.post(
    "/chat",
    response_model=ChatResponse,
    summary="Send a message and receive a RAG-augmented response",
    tags=["Chat"],
)
def chat(body: ChatRequest, rag: RAGDep, current_user: UserDep) -> ChatResponse:
    """
    Submit a patient query within an existing session.

    Workflow:
    1. Retrieve top-k relevant chunks from FAISS.
    2. Load longitudinal patient memory as context.
    3. Generate a grounded answer via Groq LLaMA-3 70B.
    4. Auto-extract and persist new clinical facts.
    5. Persist both turns to the session history.
    6. Return the structured response.
    """
    try:
        return rag.chat(
            query=body.query,
            session_id=body.session_id,
            user_id=current_user["user_id"],
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except Exception as exc:
        logger.exception("Chat error for session=%s query=%s", body.session_id, body.query)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Chat failed: {exc}",
        )


# ════════════════════════════════════════════════════════════════════════════════
# MEMORY endpoints
# ════════════════════════════════════════════════════════════════════════════════

@router.get(
    "/memory",
    response_model=MemoryResponse,
    summary="Retrieve all patient memory entries",
    tags=["Memory"],
)
def get_memory(rag: RAGDep, current_user: UserDep) -> MemoryResponse:
    entries = rag.memory.get_all(user_id=current_user["user_id"])
    return MemoryResponse(entries=entries, total=len(entries))


# Frontend calls /api/health/memory/list — this alias keeps it working
@router.get(
    "/health/memory/list",
    response_model=MemoryResponse,
    summary="Retrieve all patient memory entries (frontend alias)",
    tags=["Memory"],
)
def get_memory_alias(rag: RAGDep, current_user: UserDep) -> MemoryResponse:
    entries = rag.memory.get_all(user_id=current_user["user_id"])
    return MemoryResponse(entries=entries, total=len(entries))


@router.post(
    "/memory",
    response_model=MemoryActionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Manually add a patient memory entry",
    tags=["Memory"],
)
def add_memory(body: AddMemoryRequest, rag: RAGDep, current_user: UserDep) -> MemoryActionResponse:
    entry = rag.memory.add(
        category=body.category,
        fact=body.fact,
        source="manual",
        user_id=current_user["user_id"],
    )
    return MemoryActionResponse(entry=entry, message=f"Memory entry added with ID {entry.id}.")


@router.put(
    "/memory/{entry_id}",
    response_model=MemoryActionResponse,
    summary="Update an existing memory entry",
    tags=["Memory"],
)
def update_memory(
    entry_id: str, body: UpdateMemoryRequest, rag: RAGDep, current_user: UserDep
) -> MemoryActionResponse:
    if body.category is None and body.fact is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide at least one of 'category' or 'fact' to update.",
        )
    updated = rag.memory.update(
        entry_id,
        category=body.category,
        fact=body.fact,
        user_id=current_user["user_id"],
    )
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Memory entry '{entry_id}' not found.",
        )
    return MemoryActionResponse(entry=updated, message=f"Memory entry {entry_id} updated.")

from models.schemas import UpdateSessionRequest  # add to schemas, see below

@router.patch(
    "/chat/sessions/{session_id}",
    response_model=ChatSession,
    summary="Rename a chat session",
    tags=["Chat Sessions"],
)
def rename_session(
    session_id: str, body: UpdateSessionRequest, rag: RAGDep, current_user: UserDep
) -> ChatSession:
    result = rag.rename_session(session_id, title=body.title, user_id=current_user["user_id"])
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found.")
    return result

@router.delete(
    "/memory/{entry_id}",
    response_model=MemoryActionResponse,
    summary="Delete a specific memory entry",
    tags=["Memory"],
)
def delete_memory(entry_id: str, rag: RAGDep, current_user: UserDep) -> MemoryActionResponse:
    deleted = rag.memory.delete(entry_id, user_id=current_user["user_id"])
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Memory entry '{entry_id}' not found.",
        )
    return MemoryActionResponse(message=f"Memory entry {entry_id} deleted.")