"""
config.py
---------
Centralised configuration for the Medical RAG API.
"""

from pydantic_settings import BaseSettings
from pydantic import Field
from pathlib import Path
from typing import Optional


class Settings(BaseSettings):
    # ── API Keys ─────────────────────────────────────────────────────────
    gemini_api_key: str = Field(..., env="GEMINI_API_KEY")
    groq_api_key: str = Field(..., env="GROQ_API_KEY")

    # Optional — required only for private/gated HuggingFace models
    hf_token: Optional[str] = Field(default=None, env="HF_TOKEN")

    # ── JWT ───────────────────────────────────────────────────────────────
    jwt_secret: str = Field(default="change-me-in-production-use-a-long-random-secret", env="JWT_SECRET")
    jwt_expire_minutes: int = Field(default=1440, env="JWT_EXPIRE_MINUTES")  # 24 hours

    # ── SMTP (for OTP emails) ─────────────────────────────────────────────
    # Leave blank to use DEV MODE: OTP is printed to console instead of emailed.
    smtp_host: Optional[str] = Field(default=None, env="SMTP_HOST")
    smtp_port: int = Field(default=587, env="SMTP_PORT")
    smtp_user: Optional[str] = Field(default=None, env="SMTP_USER")
    smtp_password: Optional[str] = Field(default=None, env="SMTP_PASSWORD")
    smtp_from: Optional[str] = Field(default=None, env="SMTP_FROM")

    # ── Model selection ──────────────────────────────────────────────────
    embed_model: str = "pritamdeka/BioBERT-mnli-snli-scinli-scitail-mednli-stsb"
    groq_model: str = "llama-3.3-70b-versatile"
    gemini_model: str = "gemini-3.5-flash"

    # ── RAG hyper-parameters ─────────────────────────────────────────────
    top_k: int = 5
    chunk_size: int = 300
    chunk_overlap: int = 50
    similarity_thresh: float = 0.35

    # ── Data directory ───────────────────────────────────────────────────
    data_dir: Path = Path("data")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "medical_rag.db"

    # ── CORS ─────────────────────────────────────────────────────────────
    allowed_origins: list[str] = ["*"]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()