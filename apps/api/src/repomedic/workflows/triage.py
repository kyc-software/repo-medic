"""Bounded LangGraph workflow: parallel prediction/retrieval, then two agent roles."""

from typing import Any, TypedDict
from uuid import UUID

import mlflow
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from mlflow.entities import SpanType
from pydantic import TypeAdapter

from repomedic.application.ports import (
    Investigator,
    Predictor,
    ResolutionWriter,
    Retriever,
    WorkflowResult,
)
from repomedic.domain.models import (
    EvidenceItem,
    IssueSubmission,
    PredictionBundle,
    ResolutionBrief,
    ReviewDecision,
)
from repomedic.domain.policy import ReviewPolicy

DECISION_ADAPTER: TypeAdapter[ReviewDecision] = TypeAdapter(ReviewDecision)
EVIDENCE_ADAPTER: TypeAdapter[tuple[EvidenceItem, ...]] = TypeAdapter(tuple[EvidenceItem, ...])


class GraphState(TypedDict, total=False):
    submission: dict[str, object]
    prediction: dict[str, object]
    evidence: list[dict[str, object]]
    brief: dict[str, object]
    review_reasons: tuple[str, ...]
    decision: dict[str, object]


GRAPH_STATE_ADAPTER: TypeAdapter[GraphState] = TypeAdapter(GraphState)


class LangGraphTriageWorkflow:
    def __init__(
        self,
        predictor: Predictor,
        retriever: Retriever,
        investigator: Investigator,
        writer: ResolutionWriter,
        checkpointer: BaseCheckpointSaver[Any] | bool | None = None,
        review_policy: ReviewPolicy | None = None,
        trace_enabled: bool = False,
    ) -> None:
        policy = review_policy or ReviewPolicy()

        async def predict(state: GraphState) -> GraphState:
            submission = IssueSubmission.model_validate(state["submission"])
            prediction = await predictor.predict(submission)
            return {"prediction": prediction.model_dump(mode="json")}

        async def retrieve(state: GraphState) -> GraphState:
            submission = IssueSubmission.model_validate(state["submission"])
            evidence = await retriever.retrieve(submission)
            return {"evidence": [item.model_dump(mode="json") for item in evidence]}

        async def investigate(state: GraphState) -> GraphState:
            submission = IssueSubmission.model_validate(state["submission"])
            evidence = EVIDENCE_ADAPTER.validate_python(state["evidence"])
            investigated = await investigator.investigate(submission, evidence)
            return {"evidence": [item.model_dump(mode="json") for item in investigated]}

        async def draft(state: GraphState) -> GraphState:
            submission = IssueSubmission.model_validate(state["submission"])
            prediction = PredictionBundle.model_validate(state["prediction"])
            evidence = EVIDENCE_ADAPTER.validate_python(state["evidence"])
            brief = await writer.draft(submission, prediction, evidence)
            return {"brief": brief.model_dump(mode="json")}

        def review_policy_node(state: GraphState) -> GraphState:
            prediction = PredictionBundle.model_validate(state["prediction"])
            evidence = EVIDENCE_ADAPTER.validate_python(state["evidence"])
            brief = ResolutionBrief.model_validate(state["brief"])
            return {"review_reasons": policy.reasons(prediction, evidence, brief)}

        def human_review(state: GraphState) -> GraphState:
            raw_decision = interrupt(
                {
                    "review_reasons": state["review_reasons"],
                    "draft": state["brief"],
                }
            )
            decision = DECISION_ADAPTER.validate_python(raw_decision)
            return {"decision": DECISION_ADAPTER.dump_python(decision, mode="json")}

        def route_review(state: GraphState) -> str:
            return "human_review" if state["review_reasons"] else END

        graph = StateGraph(GraphState)
        graph.add_node("predict", predict)
        graph.add_node("retrieve", retrieve)
        graph.add_node("investigate", investigate)
        graph.add_node("draft", draft)
        graph.add_node("review_policy", review_policy_node)
        graph.add_node("human_review", human_review)
        graph.add_edge(START, "predict")
        graph.add_edge(START, "retrieve")
        graph.add_edge(["predict", "retrieve"], "investigate")
        graph.add_edge("investigate", "draft")
        graph.add_edge("draft", "review_policy")
        graph.add_conditional_edges("review_policy", route_review, ["human_review", END])
        graph.add_edge("human_review", END)
        self._graph = graph.compile(checkpointer=checkpointer or InMemorySaver())
        self._trace_enabled = trace_enabled

    async def run(self, run_id: UUID, submission: IssueSubmission) -> WorkflowResult:
        if self._trace_enabled:
            with mlflow.start_span(name="repomedic.langgraph", span_type=SpanType.CHAIN) as span:
                span.set_inputs({"run_id": str(run_id), "submission": submission.model_dump()})
                result = await self._run(run_id, submission)
                span.set_outputs(self._trace_output(result))
                return result
        return await self._run(run_id, submission)

    async def _run(self, run_id: UUID, submission: IssueSubmission) -> WorkflowResult:
        result = await self._graph.ainvoke(
            {"submission": submission.model_dump(mode="json")},
            config={"configurable": {"thread_id": str(run_id)}},
        )
        return self._result(GRAPH_STATE_ADAPTER.validate_python(result))

    async def resume(self, run_id: UUID, decision: ReviewDecision) -> WorkflowResult:
        if self._trace_enabled:
            with mlflow.start_span(
                name="repomedic.langgraph.resume", span_type=SpanType.CHAIN
            ) as span:
                span.set_inputs({"run_id": str(run_id), "decision": decision.model_dump()})
                result = await self._resume(run_id, decision)
                span.set_outputs(self._trace_output(result))
                return result
        return await self._resume(run_id, decision)

    async def _resume(self, run_id: UUID, decision: ReviewDecision) -> WorkflowResult:
        result = await self._graph.ainvoke(
            Command(resume=DECISION_ADAPTER.dump_python(decision, mode="json")),
            config={"configurable": {"thread_id": str(run_id)}},
        )
        return self._result(GRAPH_STATE_ADAPTER.validate_python(result))

    @staticmethod
    def _trace_output(result: WorkflowResult) -> dict[str, object]:
        return {
            "prediction": result.prediction.model_dump(mode="json"),
            "evidence_source_ids": [item.source_id for item in result.evidence],
            "citation_ids": list(result.brief.citation_ids),
            "review_reasons": list(result.review_reasons),
        }

    @staticmethod
    def _result(result: GraphState) -> WorkflowResult:
        return WorkflowResult(
            prediction=PredictionBundle.model_validate(result["prediction"]),
            evidence=EVIDENCE_ADAPTER.validate_python(result["evidence"]),
            brief=ResolutionBrief.model_validate(result["brief"]),
            review_reasons=result.get("review_reasons", ()),
        )
