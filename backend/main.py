"""
main.py
-------
Medical RAG API — FastAPI application entry point.

Run:
    uvicorn main:app --reload --host 0.0.0.0 --port 8000
"""

import logging
import sys
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import settings

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


# ── Lifespan ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    logger.info("═" * 60)
    logger.info("🏥  Medical RAG API — starting up")
    logger.info("═" * 60)

    if not settings.gemini_api_key or settings.gemini_api_key == "your_gemini_api_key_here":
        logger.critical("GEMINI_API_KEY is not set.")
        raise RuntimeError("GEMINI_API_KEY missing")

    if not settings.groq_api_key or settings.groq_api_key == "your_groq_api_key_here":
        logger.critical("GROQ_API_KEY is not set.")
        raise RuntimeError("GROQ_API_KEY missing")

    if settings.jwt_secret == "change-me-in-production-use-a-long-random-secret":
        logger.warning(
            "⚠️  JWT_SECRET is using the default insecure value. "
            "Set a strong secret in your .env file before deploying!"
        )

    from database import init_db
    init_db()

    from services.rag_service import RAGService
    app.state.rag_service = RAGService()

    logger.info("✅  RAGService initialised — API is ready")
    if not settings.smtp_host:
        logger.info(
            "📧  SMTP not configured — OTPs will be printed to console (DEV MODE)"
        )
    logger.info("═" * 60)

    yield

    logger.info("🏥  Medical RAG API — shutting down gracefully")


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Medical RAG API",
    description=(
        "Production-ready Retrieval-Augmented Generation backend for medical documents.\n\n"
        "## Authentication\n"
        "All `/api/*` endpoints (except `/api/auth/*`) require a JWT Bearer token.\n\n"
        "**Flow:** `POST /api/auth/register` → check email for OTP "
        "→ `POST /api/auth/verify-otp` → `POST /api/auth/login` → use `access_token`\n\n"
        "## Features\n"
        "- **PDF upload** with Gemini Vision OCR\n"
        "- **FAISS vector search** with BioBERT medical embeddings\n"
        "- **SQLite persistence** for documents, memory, and chat sessions\n"
        "- **Multi-session chat** with per-session history\n"
        "- **Auto memory extraction** after every chat turn\n"
        "- **Full user isolation** — every resource is scoped to the authenticated user"
    ),
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── CORS ─────────────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# ── Routes ────────────────────────────────────────────────────────────────────

from api.routes import router          # noqa: E402
from api.auth_routes import auth_router  # noqa: E402

app.include_router(auth_router)  # /api/auth/* — public
app.include_router(router)       # /api/*      — JWT protected


# ── Health check ─────────────────────────────────────────────────────────────

@app.get("/health", tags=["System"], summary="Health check")
def health_check() -> JSONResponse:
    return JSONResponse(
        content={"status": "ok", "service": "Medical RAG API", "version": "2.0.0"}
    )


@app.get("/", tags=["System"], include_in_schema=False)
def root() -> JSONResponse:
    return JSONResponse(content={
        "message": "Medical RAG API is running. Visit /docs for the interactive API reference.",
        "docs": "/docs",
    })