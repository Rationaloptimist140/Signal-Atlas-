"""Post-generation guardrails: an LLM must never introduce figures that are not in the fact sheet."""

import re

from app.services.ai.schemas import AIEnrichment, AIStatement

_MONEY_RE = re.compile(r"(?:[$£€]\s?\d)|(?:\b\d[\d,.]*\s?(?:million|billion|trillion|bn|mn|m\b|k\b)\s*(?:usd|gbp|eur|dollars|pounds|euros)?)|(?:\b(?:arr|mrr|revenue|valuation|market size|tam)\b[^.]{0,40}\d)", re.IGNORECASE)
_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def numbers_in(text: str) -> set[str]:
    return {n.replace(",", "").rstrip(".") for n in _NUMBER_RE.findall(text)}


def _normalise(n: str) -> str:
    return n[:-2] if n.endswith(".0") else n


def allowed_numbers(facts: list[dict]) -> set[str]:
    allowed: set[str] = set()
    for fact in facts:
        for part in (str(fact.get("value", "")), str(fact.get("label", ""))):
            allowed |= {_normalise(n) for n in numbers_in(part)}
    return allowed


def check_statement(text: str, allowed: set[str]) -> str | None:
    """Return a rejection reason, or None when the statement introduces no new figures."""
    if _MONEY_RE.search(text):
        return "monetary_or_market_size_claim"
    for number in numbers_in(text):
        number = _normalise(number)
        if len(number.replace(".", "")) <= 1:  # single digits ("3 segments") are harmless
            continue
        if number not in allowed:
            return f"unverified_figure:{number}"
    return None


def apply_guardrails(enrichment: AIEnrichment, facts: list[dict]) -> tuple[AIEnrichment, dict]:
    """Drop statements with unverifiable figures and unknown references. Returns the cleaned enrichment and a report."""
    allowed = allowed_numbers(facts)
    fact_ids = {f["id"] for f in facts}
    removed: list[dict] = []

    def clean(items: list[AIStatement], section: str) -> list[AIStatement]:
        kept = []
        for item in items:
            reason = check_statement(item.text, allowed)
            if reason:
                removed.append({"section": section, "reason": reason})
                continue
            item.references = [r for r in item.references if r in fact_ids]
            kept.append(item)
        return kept

    enrichment.interpretations = clean(enrichment.interpretations, "interpretations")
    enrichment.hypotheses = clean(enrichment.hypotheses, "hypotheses")
    enrichment.commercial_use_cases = clean(enrichment.commercial_use_cases, "commercial_use_cases")
    summary_reason = check_statement(enrichment.executive_summary, allowed)
    summary_rejected = summary_reason is not None
    if summary_rejected:
        removed.append({"section": "executive_summary", "reason": summary_reason})
    steps = []
    for step in enrichment.recommended_next_steps:
        if check_statement(step, allowed):
            removed.append({"section": "recommended_next_steps", "reason": "unverified_figure"})
        else:
            steps.append(step[:400])
    enrichment.recommended_next_steps = steps
    return enrichment, {"statements_removed": len(removed), "removed": removed, "summary_rejected": summary_rejected}
