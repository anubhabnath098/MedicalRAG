"""
services/gemini_service.py
--------------------------
Gemini-powered service for:

1. PDF OCR  — send the raw PDF bytes to Gemini Vision and get back clean text.
              This is the primary extraction path for handwritten prescriptions,
              scanned lab reports, and mixed-content medical PDFs.

2. Document Summarisation — given extracted text, produce a structured JSON
   summary covering: core content, doctor concerned, and document date/time.

The PDF bytes are NEVER written to permanent storage; they exist only in memory
during the API call lifetime.
"""

import json
import logging
import re
from typing import Optional

import google.generativeai as genai
from google.generativeai.types import GenerationConfig
import base64

from config import settings
from models.schemas import DocumentSummary

logger = logging.getLogger(__name__)


class GeminiService:
    """
    Thin async-compatible wrapper around the Gemini generative API.

    Note: google-generativeai's Python SDK is synchronous as of v0.8.x.
    We run it inside FastAPI's `run_in_executor` at the route level to
    avoid blocking the event loop.
    """

    # ── Prompts ────────────────────────────────────────────────────────────

    OCR_PROMPT = """You are a medical document OCR and transcription specialist.
The attached file is a medical PDF document. It may contain:
- Typed or handwritten clinical notes
- Prescriptions with drug names, dosages, and instructions
- Lab results with reference ranges
- Discharge summaries or consultation notes

Your task:
1. Extract ALL text from this document with maximum fidelity.
2. Preserve structure: headings, lists, tables (as plain text), and page breaks.
3. For handwritten text, make your best-effort transcription and mark uncertain
   words with [?].
4. Do NOT summarise — return the complete raw text.

Return only the extracted text, with no preamble or commentary."""

    SUMMARISE_PROMPT = """You are a medical record-keeping AI.
Given the following medical document text, produce a concise structured summary.

Return ONLY a valid JSON object with exactly these keys:
{{
  "core_content": "<STRICTLY 1-2 sentences, max 50 words, summarising main findings or prescriptions>",
  "doctor_concerned": "<name and specialty of the primary physician; 'Not mentioned' if absent>",
  "date_time": "<date/time of the medical event or report; 'Not mentioned' if absent>",
  "document_type": "<one of: Prescription, Lab Report, Consultation Note, Discharge Summary, Vaccination Record, Other>"
}}

No markdown, no preamble, no trailing text — pure JSON only.

DOCUMENT TEXT:
{text}"""

    def __init__(self):
        genai.configure(api_key=settings.gemini_api_key)
        self.model = genai.GenerativeModel(settings.gemini_model)
        logger.info("GeminiService initialised (model=%s)", settings.gemini_model)

    # ── OCR ───────────────────────────────────────────────────────────────

    def extract_text_from_pdf(self, pdf_bytes: bytes, filename: str) -> str:
        """
        Upload PDF bytes to Gemini and return the extracted text.

        Parameters
        ----------
        pdf_bytes : Raw bytes of the PDF (in-memory only, never written to disk).
        filename  : Original filename, used only for logging.

        Returns
        -------
        Extracted text string.
        """
        logger.info("Starting Gemini OCR for file: %s (%d bytes)", filename, len(pdf_bytes))

        # The Gemini SDK accepts inline binary data via the Part API
        pdf_part = {
            "inline_data": {
                "mime_type": "application/pdf",
                "data": base64.b64encode(pdf_bytes).decode("utf-8"),
            }
        }

        response = self.model.generate_content(
            [self.OCR_PROMPT, pdf_part],
            generation_config=GenerationConfig(temperature=0.1, max_output_tokens=8192),
        )

        extracted = response.text.strip()
        logger.info(
            "Gemini OCR complete for %s — extracted %d characters",
            filename,
            len(extracted),
        )
        return extracted

    # ── Summarisation ─────────────────────────────────────────────────────

    def summarise_document(self, text: str) -> DocumentSummary:
        prompt = self.SUMMARISE_PROMPT.format(text=text[:6000])

        response = self.model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(
                temperature=0.1,
                max_output_tokens=2048,
                response_mime_type="application/json",  # forces valid JSON output
            ),
        )

        if not response.parts:
            raise ValueError("Gemini returned no content during summarisation.")

        try:
            data = json.loads(response.text)
            return DocumentSummary(
                core_content=data.get("core_content", "Unable to extract summary."),
                doctor_concerned=data.get("doctor_concerned", "Not mentioned"),
                date_time=data.get("date_time", "Not mentioned"),
                document_type=data.get("document_type", "Other"),
            )
        except (json.JSONDecodeError, KeyError) as exc:
            logger.warning("Gemini summary JSON parse failed: %s — raw: %s", exc, response.text[:200])
            return DocumentSummary(
                core_content="Summary unavailable.",
                doctor_concerned="Not mentioned",
                date_time="Not mentioned",
                document_type="Other",
            )
