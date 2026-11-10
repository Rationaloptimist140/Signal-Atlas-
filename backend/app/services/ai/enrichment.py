"""LLM enrichment of a deterministic report, with schema validation and numeric guardrails."""

import json

from pydantic import ValidationError

from app.logging_config import get_logger
from app.services.ai.guardrails import apply_guardrails
from app.services.ai.providers import LLMError, LLMProvider
from app.services.ai.schemas import AIEnrichment

log = get_logger("ai")

SYSTEM_PROMPT = """You are an analyst for SIGNAL ATLAS, an open-source technology intelligence platform.
You receive a FACT SHEET of verified facts and calculated metrics about open-source repositories. Each fact has an id.

Rules you must follow:
1. Use ONLY the facts provided. Never state a number, statistic, date, revenue, valuation, funding amount or market size that is not in the fact sheet.
2. Never claim an opportunity is validated or proven. Popularity is not evidence of commercial demand.
3. "interpretations" explain what the facts suggest. "hypotheses" are untested commercial ideas. Keep them clearly distinct.
4. Cite the fact ids each statement relies on in "references".
5. Be specific and useful to a founder or investor; avoid generic advice.
6. Respond with a single JSON object only, matching this shape:
{"executive_summary": str, "interpretations": [{"text": str, "confidence": "low|medium|high", "references": [str]}],
 "hypotheses": [{"text": str, "confidence": "low|medium|high", "references": [str]}],
 "commercial_use_cases": [{"text": str, "confidence": "low|medium|high", "references": [str]}],
 "recommended_next_steps": [str]}"""


def build_user_prompt(report_type: str, subject_title: str, facts: list[dict], rules_summary: str) -> str:
    sheet = "\n".join(f"[{f['id']}] ({f['kind']}) {f['label']}: {f['value']}" for f in facts)
    return (
        f"REPORT TYPE: {report_type}\nSUBJECT: {subject_title}\n\nFACT SHEET:\n{sheet}\n\n"
        f"RULE-BASED SUMMARY (for context, do not repeat verbatim):\n{rules_summary}\n\n"
        "Write the JSON analysis now."
    )


async def enrich(provider: LLMProvider, report_type: str, subject_title: str, facts: list[dict], rules_summary: str) -> tuple[AIEnrichment, dict]:
    """Call the provider (one retry on malformed output) and return guarded, validated enrichment."""
    user = build_user_prompt(report_type, subject_title, facts, rules_summary)
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            raw = await provider.complete_json(SYSTEM_PROMPT, user)
            enrichment = AIEnrichment.model_validate(raw)
            cleaned, guard_report = apply_guardrails(enrichment, facts)
            guard_report["attempts"] = attempt + 1
            return cleaned, guard_report
        except (LLMError, ValidationError) as exc:
            last_error = exc
            log.warning("ai_enrichment_invalid", attempt=attempt + 1, error=type(exc).__name__)
            user += "\n\nYour previous reply was invalid. Reply with ONLY the JSON object described in the rules."
    raise LLMError(f"AI enrichment failed validation: {type(last_error).__name__}: {json.dumps(str(last_error))[:300]}")
