"""
services/groq_service.py
------------------------
Groq LLM client providing two capabilities:

1. answer()         — Dual-context RAG response generation.
                       Grounds the answer in FAISS-retrieved chunks AND
                       the patient's longitudinal memory. Returns structured JSON.

2. extract_memory() — Post-exchange autonomous memory extraction.
                       The LLM reads the conversation turn and returns only
                       clinically significant facts worth persisting.
"""

import json
import logging
import re
from typing import List, Optional, Dict

from groq import Groq

from config import settings

logger = logging.getLogger(__name__)


class GroqService:
    """
    Thin wrapper around the Groq API (LLaMA-3 70B).

    All prompts enforce JSON output so the FastAPI layer can parse and
    re-expose them as strongly typed Pydantic models.
    """

    # ── System Prompts ────────────────────────────────────────────────────

    ANSWER_SYSTEM_PROMPT = """You are a highly knowledgeable and empathetic medical assistant AI.
Your role is to answer patient questions using the information in the CONTEXT CHUNKS,
PATIENT MEMORY, and INDEXED DOCUMENTS sections provided in the user message.

STRICT HALLUCINATION MITIGATION RULES:
1. Never fabricate drug names, dosages, lab values, or diagnoses.
2. Always cite which source chunk you drew information from (e.g., [Source: report.pdf]).
3. If information seems contradictory across documents, highlight the discrepancy.
4. Always remind the patient to consult a qualified physician for clinical decisions.

HANDLING MISSING INFORMATION — CRITICAL:
When the answer is NOT found in the context or memory, do NOT say "I cannot find this".
Instead, give a CONTEXTUALLY AWARE response that:
  a) Acknowledges which documents WERE uploaded and what they cover.
  b) Explains specifically why that metric/value is absent.
  c) Tells the patient what kind of test or document would contain this information.
  d) Offers to record it if the patient provides the value — use exactly:
     "If you have this value from a recent test, you can tell me and I will save it
     to your health record for future reference."

You MUST respond with a valid JSON object — no markdown, no preamble — with this schema:
{
  "answer": "<your full response to the patient>",
  "sources_cited": ["<source name 1>", ...],
  "confidence": "<high|medium|low>",
  "disclaimer": "<clinical disclaimer if applicable, else null>"
}"""

    MEMORY_EXTRACT_SYSTEM_PROMPT = """You are a medical record-keeping AI.
Given a conversation exchange between a patient and a medical assistant,
identify facts that are clinically significant and should be remembered long-term.

Extract ONLY facts that fall into these categories:
PRESCRIPTION, DIAGNOSIS, ALLERGY, SURGERY, LAB_RESULT,
MEDICAL_COURSE_COMPLETED, VACCINATION, VITAL_STATS, FOLLOW_UP

Do NOT extract:
- Generic medical knowledge or explanations
- Questions the patient asked
- Advice or recommendations (only confirmed facts)

Return a JSON array — no preamble, no markdown fences. Each element must have:
  { "category": "<CATEGORY>", "fact": "<concise fact, max 30 words>" }

If nothing is worth persisting, return an empty array: []
Return ONLY valid JSON."""

    def __init__(self):
        self.client = Groq(api_key=settings.groq_api_key)
        self.model = settings.groq_model
        logger.info("GroqService initialised (model=%s)", self.model)

    # ── RAG answer generation ─────────────────────────────────────────────

    def answer(
        self,
        query: str,
        retrieved_chunks: List[Dict],
        patient_memory: str,
        indexed_docs: Optional[List[str]] = None,
    ) -> Dict:
        """
        Generate a grounded RAG answer.

        Returns a dict with keys: answer, sources_cited, confidence, disclaimer.
        Falls back to a safe error dict on JSON parse failure.
        """
        # Format retrieved context with source attribution
        if retrieved_chunks:
            context_block = "\n\n".join(
                f"[Source: {c['source']} | Relevance: {c['similarity_score']}]\n{c['text']}"
                for c in retrieved_chunks
            )
        else:
            context_block = "No relevant chunks were retrieved above the similarity threshold."

        docs_list = (
            "\n".join(f"  - {d}" for d in (indexed_docs or []))
            or "  (no documents indexed)"
        )

        user_message = f"""PATIENT MEMORY (longitudinal health record):
---
{patient_memory}
---

INDEXED DOCUMENTS (all files currently in the knowledge base):
---
{docs_list}
---

CONTEXT CHUNKS (retrieved passages most relevant to the question):
---
{context_block}
---

PATIENT QUESTION: {query}"""

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": self.ANSWER_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=0.2,
            max_tokens=1024,
        )

        raw = response.choices[0].message.content.strip()
        raw = re.sub(r"^```json\s*|^```\s*|```$", "", raw, flags=re.MULTILINE).strip()

        try:
            result = json.loads(raw)
            # Ensure required keys are present
            return {
                "answer": result.get("answer", raw),
                "sources_cited": result.get("sources_cited", []),
                "confidence": result.get("confidence", "medium"),
                "disclaimer": result.get("disclaimer"),
            }
        except json.JSONDecodeError:
            logger.warning("GroqService answer JSON parse failed — returning raw text")
            return {
                "answer": raw,
                "sources_cited": [],
                "confidence": "medium",
                "disclaimer": "Please consult a qualified physician for clinical decisions.",
            }

    # ── Memory extraction ─────────────────────────────────────────────────

    def extract_memory(self, query: str, answer: str) -> List[Dict]:
        """
        After each exchange, the LLM autonomously identifies patient facts
        worth persisting.  Returns a list of {category, fact} dicts.
        """
        exchange = f"Patient asked: {query}\n\nAssistant answered: {answer}"

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": self.MEMORY_EXTRACT_SYSTEM_PROMPT},
                {"role": "user", "content": exchange},
            ],
            temperature=0.0,
            max_tokens=512,
        )

        raw = response.choices[0].message.content.strip()
        raw = re.sub(r"^```json\s*|^```\s*|```$", "", raw, flags=re.MULTILINE).strip()

        try:
            entries = json.loads(raw)
            return entries if isinstance(entries, list) else []
        except json.JSONDecodeError:
            logger.warning("Memory extraction JSON parse failed — raw: %s", raw[:200])
            return []
