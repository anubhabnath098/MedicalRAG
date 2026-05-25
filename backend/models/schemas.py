"""
models/schemas.py
-----------------
All Pydantic request / response schemas for the Medical RAG API.
v2: Adds User and Auth schemas.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional
from pydantic import BaseModel, EmailStr, Field, field_validator
import uuid


# ── Shared helpers ────────────────────────────────────────────────────────────

def new_uuid() -> str:
    return str(uuid.uuid4())


# ═══════════════════════════════════════════════════════════════════════════════
# AUTH / USER schemas
# ═══════════════════════════════════════════════════════════════════════════════

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, description="Minimum 8 characters")

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit.")
        if not any(c.isalpha() for c in v):
            raise ValueError("Password must contain at least one letter.")
        return v

class UpdateSessionRequest(BaseModel):
    title: str = Field(min_length=1, max_length=100)

class VerifyOTPRequest(BaseModel):
    email: EmailStr
    otp: str = Field(min_length=6, max_length=6, description="6-digit OTP from email")


class ResendOTPRequest(BaseModel):
    email: EmailStr


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    email: str


class AuthMessageResponse(BaseModel):
    message: str


class UserOut(BaseModel):
    user_id: str
    email: str


# ═══════════════════════════════════════════════════════════════════════════════
# DOCUMENT schemas
# ═══════════════════════════════════════════════════════════════════════════════

class DocumentSummary(BaseModel):
    core_content: str
    doctor_concerned: str
    date_time: str
    document_type: str


class DocumentRecord(BaseModel):
    id: str = Field(default_factory=new_uuid)
    filename: str
    uploaded_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    chunk_count: int
    char_count: int
    summary: DocumentSummary
    faiss_indices: List[int] = Field(default_factory=list)


class UploadResponse(BaseModel):
    success: bool = True
    document_id: str
    filename: str
    chunk_count: int
    summary: DocumentSummary
    message: str = "Document successfully processed and indexed."


class DeleteDocumentResponse(BaseModel):
    success: bool = True
    document_id: str
    message: str


class DocumentListResponse(BaseModel):
    documents: List[DocumentRecord]
    total: int


# ═══════════════════════════════════════════════════════════════════════════════
# MEMORY schemas
# ═══════════════════════════════════════════════════════════════════════════════

MEMORY_CATEGORIES = [
    "PRESCRIPTION",
    "DIAGNOSIS",
    "ALLERGY",
    "SURGERY",
    "LAB_RESULT",
    "MEDICAL_COURSE_COMPLETED",
    "VACCINATION",
    "VITAL_STATS",
    "FOLLOW_UP",
    "GENERAL",
]


class MemoryEntry(BaseModel):
    id: str = Field(default_factory=new_uuid)
    category: str
    fact: str
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: Optional[str] = None
    source: str = Field(default="manual")


class MemoryResponse(BaseModel):
    entries: List[MemoryEntry]
    total: int


class AddMemoryRequest(BaseModel):
    category: str
    fact: str


class UpdateMemoryRequest(BaseModel):
    category: Optional[str] = None
    fact: Optional[str] = None


class MemoryActionResponse(BaseModel):
    success: bool = True
    entry: Optional[MemoryEntry] = None
    message: str


# ═══════════════════════════════════════════════════════════════════════════════
# CHAT SESSION schemas
# ═══════════════════════════════════════════════════════════════════════════════

class ChatSession(BaseModel):
    """Lightweight session record — no history payload."""
    id: str = Field(default_factory=new_uuid)
    title: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class CreateSessionRequest(BaseModel):
    title: Optional[str] = Field(
        default=None,
        description="Optional human-readable title for the session.",
    )


class ChatSessionListResponse(BaseModel):
    sessions: List[ChatSession]
    total: int


# ═══════════════════════════════════════════════════════════════════════════════
# CHAT schemas
# ═══════════════════════════════════════════════════════════════════════════════

class RetrievedChunk(BaseModel):
    source: str
    text: str
    similarity_score: float


class ChatRequest(BaseModel):
    session_id: str = Field(description="Session ID returned by POST /api/chat/sessions")
    query: str = Field(min_length=1, description="The patient's question or message")


class ChatHistoryEntry(BaseModel):
    id: str = Field(default_factory=new_uuid)
    session_id: str = ""
    role: str = Field(description="'user' or 'assistant'")
    content: str
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    metadata: Optional[dict[str, Any]] = None


class ChatResponse(BaseModel):
    success: bool = True
    session_id: str
    query: str
    answer: str
    retrieved_chunks: List[RetrievedChunk] = Field(default_factory=list)
    chunks_retrieved: int
    new_memory_entries: List[MemoryEntry] = Field(default_factory=list)
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


class ChatSessionDetailResponse(BaseModel):
    """Full session including its conversation history."""
    session: ChatSession
    history: List[ChatHistoryEntry]
    total_turns: int


# ═══════════════════════════════════════════════════════════════════════════════
# GENERIC error schema
# ═══════════════════════════════════════════════════════════════════════════════

class ErrorResponse(BaseModel):
    success: bool = False
    error: str
    detail: Optional[str] = None