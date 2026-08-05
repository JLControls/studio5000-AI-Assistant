"""Workers turn an entity + its context into fact updates or assistance requests.

The default ``DeterministicWorker`` uses **no LLM**. It walks the precedence
ladder (native comment -> metadata -> FEEDS propagation) and, when deterministic
paths are exhausted on *genuine* ambiguity, it refuses to fabricate: it emits an
``AssistanceRequest`` naming the entity, the ambiguity, the evidence gathered,
and a suggested model level for a later LLM callback worker.

Workers read only an immutable ``WorkerContext`` snapshot and never touch the
``FactStore`` — that is what makes gather-then-sorted-merge deterministic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Protocol, Tuple

from .model import Confidence, EntityId
from .facts import (
    Evidence,
    EvidenceKind,
    Fact,
    FactStatus,
    FactUpdate,
)


class ModelLevel(Enum):
    HAIKU = "haiku"
    SONNET = "sonnet"
    OPUS = "opus"


def _normalize(text: str) -> str:
    """Semantic key for a description: lowercased, whitespace/punct-collapsed."""
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def suggest_model_level(
    candidate_count: int,
    neighbor_count: int,
    in_cycle: bool,
    tier1_conflict: bool,
) -> ModelLevel:
    """Pure heuristic mapping ambiguity shape to a model tier.

    OPUS for the hardest cases (a cycle, a native-comment conflict, or a large
    neighbourhood); HAIKU only for a single mechanical reword; SONNET otherwise.
    """
    if in_cycle or tier1_conflict or neighbor_count >= 8:
        return ModelLevel.OPUS
    if candidate_count == 1 and neighbor_count <= 1:
        return ModelLevel.HAIKU
    return ModelLevel.SONNET


@dataclass(frozen=True)
class WorkerContext:
    """Immutable snapshot handed to a worker. Never references the FactStore."""

    entity: EntityId
    predicate: str = "description"
    native_comment: Optional[str] = None
    metadata: Optional[str] = None
    neighbor_facts: Tuple[Fact, ...] = ()
    unresolved_instruction: bool = False
    in_cycle: bool = False


@dataclass(frozen=True)
class AssistanceRequest:
    entity_id: EntityId
    predicate: str
    ambiguity: str
    evidence: Tuple[str, ...]
    candidate_values: Tuple[str, ...]
    suggested_model_level: ModelLevel
    rationale: str

    def to_dict(self) -> dict:
        return {
            "entity": str(self.entity_id),
            "predicate": self.predicate,
            "ambiguity": self.ambiguity,
            "evidence": list(self.evidence),
            "candidate_values": list(self.candidate_values),
            "suggested_model_level": self.suggested_model_level.value,
            "rationale": self.rationale,
        }


@dataclass
class WorkerResult:
    fact_updates: List[FactUpdate] = field(default_factory=list)
    assistance_requests: List[AssistanceRequest] = field(default_factory=list)


class Worker(Protocol):
    def analyze(self, ctx: WorkerContext) -> WorkerResult:  # pragma: no cover - protocol
        ...


class DeterministicWorker:
    """Default, no-LLM worker. Derives everything possible from evidence."""

    def analyze(self, ctx: WorkerContext) -> WorkerResult:
        # 1. Native comment on the entity itself: strongest, HIGH, observed.
        if ctx.native_comment and ctx.native_comment.strip():
            return self._fact(
                ctx, ctx.native_comment.strip(), Confidence.HIGH,
                FactStatus.OBSERVED, EvidenceKind.NATIVE_COMMENT, source="native",
            )

        # 2. Module / IO / datatype metadata.
        if ctx.metadata and ctx.metadata.strip():
            return self._fact(
                ctx, ctx.metadata.strip(), Confidence.MEDIUM,
                FactStatus.OBSERVED, EvidenceKind.LOGIC_METADATA, source="metadata",
            )

        # 3. Propagate a stable neighbour fact along FEEDS, one step lower.
        usable = [
            f for f in ctx.neighbor_facts
            if f.confidence is not Confidence.LOW
            and f.status not in (FactStatus.UNRESOLVED, FactStatus.SUPERSEDED)
        ]
        distinct = sorted({f.normalized_value for f in usable})
        tier1_values = {
            f.normalized_value for f in ctx.neighbor_facts
            if f.precedence_tier == EvidenceKind.NATIVE_COMMENT.value
        }
        tier1_conflict = len(tier1_values) >= 2

        if ctx.unresolved_instruction or tier1_conflict or len(distinct) >= 2:
            return self._escalate(ctx, distinct, tier1_conflict)

        if len(distinct) == 1:
            source = max(usable, key=lambda f: f.confidence.value)
            return self._fact(
                ctx, source.value, source.confidence.stepped_down(),
                FactStatus.INFERRED, EvidenceKind.LOGIC_METADATA,
                source=f"feeds:{source.subject}",
            )

        # Nothing usable at all -> ask for help rather than invent a comment.
        return self._escalate(ctx, distinct, tier1_conflict)

    # -- helpers ----------------------------------------------------------
    def _fact(self, ctx, value, confidence, status, kind, source):
        update = FactUpdate(
            subject=ctx.entity,
            predicate=ctx.predicate,
            value=value,
            normalized_value=_normalize(value),
            confidence=confidence,
            evidence=[Evidence(kind=kind, detail=value, source=source)],
            status=status,
            rendered_candidate=value,
        )
        return WorkerResult(fact_updates=[update])

    def _escalate(self, ctx, distinct, tier1_conflict):
        level = suggest_model_level(
            candidate_count=len(distinct),
            neighbor_count=len(ctx.neighbor_facts),
            in_cycle=ctx.in_cycle,
            tier1_conflict=tier1_conflict,
        )
        if ctx.unresolved_instruction:
            ambiguity = "role depends on an instruction with no known direction"
        elif tier1_conflict:
            ambiguity = "conflicting native comments among neighbours"
        elif len(distinct) >= 2:
            ambiguity = "multiple incompatible inferred meanings from neighbours"
        else:
            ambiguity = "no direct comment, metadata, or stable neighbour fact"
        evidence = tuple(
            f"{f.subject}={f.value} ({f.confidence.name})" for f in ctx.neighbor_facts
        )
        req = AssistanceRequest(
            entity_id=ctx.entity,
            predicate=ctx.predicate,
            ambiguity=ambiguity,
            evidence=evidence,
            candidate_values=tuple(distinct),
            suggested_model_level=level,
            rationale=(
                "DeterministicWorker exhausted evidence-based paths without a "
                "single confident interpretation; escalating instead of fabricating."
            ),
        )
        return WorkerResult(assistance_requests=[req])


class CallbackWorker:
    """Optional injectable worker that defers ambiguous entities to a callback.

    ``callback(ctx) -> Optional[FactUpdate]`` is expected to be an LLM/agent call.
    Deterministic paths run first; the callback is only consulted when the
    deterministic worker would escalate. Returning ``None`` re-raises the
    original assistance request. This is I/O-bound and safe under asyncio.
    """

    def __init__(self, callback, deterministic: Optional[DeterministicWorker] = None):
        self._callback = callback
        self._deterministic = deterministic or DeterministicWorker()

    def analyze(self, ctx: WorkerContext) -> WorkerResult:
        base = self._deterministic.analyze(ctx)
        if not base.assistance_requests:
            return base
        update = self._callback(ctx)
        if update is None:
            return base
        return WorkerResult(fact_updates=[update])
