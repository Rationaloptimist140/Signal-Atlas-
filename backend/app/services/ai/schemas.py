"""Validated structure for LLM enrichment. The LLM may only add interpretations and hypotheses."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AIStatement(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: str = Field(min_length=10, max_length=700)
    confidence: Literal["low", "medium", "high"] = "low"
    references: list[str] = Field(default_factory=list, max_length=8, description="IDs of the facts this statement rests on, e.g. F3")


class AIEnrichment(BaseModel):
    model_config = ConfigDict(extra="ignore")

    executive_summary: str = Field(min_length=20, max_length=1500)
    interpretations: list[AIStatement] = Field(default_factory=list, max_length=8)
    hypotheses: list[AIStatement] = Field(default_factory=list, max_length=8)
    commercial_use_cases: list[AIStatement] = Field(default_factory=list, max_length=6)
    recommended_next_steps: list[str] = Field(default_factory=list, max_length=6)
