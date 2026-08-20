"""Two bounded OpenAI roles: evidence-gap investigator and cited brief writer."""

import json

from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict, Field

from repomedic.adapters.retrieval import ChromaRetriever
from repomedic.domain.models import (
    EvidenceItem,
    IssueSubmission,
    PredictionBundle,
    ResolutionBrief,
)


class InvestigationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    targeted_query: str | None = Field(
        description=(
            "One narrow missing-evidence query, or null when current evidence is sufficient."
        )
    )


class OpenAIInvestigator:
    def __init__(self, client: AsyncOpenAI, model: str, retriever: ChromaRetriever) -> None:
        self._client = client
        self._model = model
        self._retriever = retriever

    async def investigate(
        self, submission: IssueSubmission, evidence: tuple[EvidenceItem, ...]
    ) -> tuple[EvidenceItem, ...]:
        response = await self._client.responses.parse(
            model=self._model,
            input=[
                {
                    "role": "system",
                    "content": (
                        "You inspect evidence coverage for one scikit-learn issue. "
                        "Request at most one narrow retrieval query. Never draft a resolution."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "issue": submission.model_dump(mode="json"),
                            "evidence": [item.model_dump(mode="json") for item in evidence],
                        }
                    ),
                },
            ],
            text_format=InvestigationDecision,
        )
        decision = response.output_parsed
        if decision is None or decision.targeted_query is None:
            return evidence
        extra = await self._retriever.retrieve_text(decision.targeted_query, limit=3)
        merged = {item.source_id: item for item in (*evidence, *extra)}
        return tuple(merged.values())


class OpenAIResolutionWriter:
    def __init__(self, client: AsyncOpenAI, model: str) -> None:
        self._client = client
        self._model = model

    async def draft(
        self,
        submission: IssueSubmission,
        prediction: PredictionBundle,
        evidence: tuple[EvidenceItem, ...],
    ) -> ResolutionBrief:
        response = await self._client.responses.parse(
            model=self._model,
            input=[
                {
                    "role": "system",
                    "content": (
                        "Write a concise triage brief. Every technical claim and "
                        "investigation step must cite source_id values from supplied "
                        "evidence. Do not invent citations."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "issue": submission.model_dump(mode="json"),
                            "prediction": prediction.model_dump(mode="json"),
                            "evidence": [item.model_dump(mode="json") for item in evidence],
                        }
                    ),
                },
            ],
            text_format=ResolutionBrief,
        )
        if response.output_parsed is None:
            raise RuntimeError("OpenAI response did not contain a structured brief")
        return response.output_parsed
