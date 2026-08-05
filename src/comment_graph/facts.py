"""Monotonic fact store with precedence-based merge and contradiction reporting.

A *fact* is a claim about an entity (subject) — e.g. ``op:N101[18]`` has
``description`` "calibrated temperature". Facts carry evidence, and every piece
of evidence has an ``EvidenceKind`` whose enum value is its precedence *tier*
(lower = stronger). Merges never silently overwrite a stronger claim.

Semantic change is measured on ``normalized_value`` (+ tier), never on prose, so
rewording a comment does not ripple through the graph but a genuine change of
meaning does.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

from .model import Confidence, EntityId


class EvidenceKind(Enum):
    """Evidence sources in precedence order (enum value == tier, lower stronger)."""

    NATIVE_COMMENT = 1     # operand/tag/rung comment authored in the project
    USER_DECISION = 2      # a decision supplied by the calling agent/user
    LOGIC_METADATA = 3     # module/IO metadata, datatypes, descriptions
    PRIOR_MEMORY = 4       # a previously-persisted decision (hash-guarded)
    INSTRUCTION_DOC = 5    # 561-instruction DB enrichment (never asserts direction)
    VECTOR_RETRIEVAL = 6   # semantic retrieval (off by default)
    MODEL_INFERENCE = 7    # an LLM/worker inference


class FactStatus(Enum):
    OBSERVED = "observed"        # taken directly from evidence
    INFERRED = "inferred"        # derived from a neighbour's fact
    UNRESOLVED = "unresolved"    # could not be determined
    SUPERSEDED = "superseded"    # replaced by a stronger fact


class MergeOutcome(Enum):
    CHANGED = "changed"              # value/tier changed (a semantic change)
    ENRICHED = "enriched"            # same meaning; evidence/confidence added
    REJECTED = "rejected"            # same tier, lost the deterministic tie-break
    CONTRADICTION = "contradiction"  # weaker tier disagreed; incumbent kept
    UNCHANGED = "unchanged"          # no-op


@dataclass(frozen=True)
class Evidence:
    kind: EvidenceKind
    detail: str = ""
    source: Optional[str] = None

    @property
    def id(self) -> str:
        return f"{self.kind.name}:{self.source or self.detail}"


@dataclass
class Fact:
    subject: EntityId
    predicate: str
    value: str
    normalized_value: str
    confidence: Confidence
    evidence_ids: List[str] = field(default_factory=list)
    producer_pass: int = 0
    status: FactStatus = FactStatus.OBSERVED
    rendered_candidate: str = ""
    precedence_tier: int = EvidenceKind.MODEL_INFERENCE.value

    def dominance(self) -> Tuple[int, int, str]:
        """Total order for tie-breaking: stronger tier, then higher confidence,
        then lexically-first value. Smaller tuple = dominant."""
        return (self.precedence_tier, -self.confidence.value, self.normalized_value)


@dataclass(frozen=True)
class FactUpdate:
    subject: EntityId
    predicate: str
    value: str
    normalized_value: str
    confidence: Confidence
    evidence: List[Evidence]
    status: FactStatus = FactStatus.OBSERVED
    rendered_candidate: str = ""

    @property
    def precedence_tier(self) -> int:
        return min((e.kind.value for e in self.evidence), default=EvidenceKind.MODEL_INFERENCE.value)


@dataclass(frozen=True)
class Contradiction:
    subject: EntityId
    predicate: str
    incumbent_value: str
    rejected_value: str
    reason: str


@dataclass
class MergeResult:
    outcome: MergeOutcome
    fact: Optional[Fact] = None
    semantic_changed: bool = False
    contradiction: Optional[Contradiction] = None
    superseded: Optional[Fact] = None


class FactStore:
    """Keyed store of the current best fact per (subject, predicate)."""

    def __init__(self) -> None:
        self._facts: Dict[Tuple[EntityId, str], Fact] = {}
        self.contradictions: List[Contradiction] = []
        self.superseded: List[Fact] = []

    def get(self, subject: EntityId, predicate: str) -> Optional[Fact]:
        return self._facts.get((subject, predicate))

    def facts(self) -> List[Fact]:
        return [self._facts[k] for k in sorted(self._facts, key=lambda kp: (str(kp[0]), kp[1]))]

    def merge(self, update: FactUpdate, pass_no: int) -> MergeResult:
        key = (update.subject, update.predicate)
        incumbent = self._facts.get(key)
        candidate = self._to_fact(update, pass_no)

        if incumbent is None:
            self._facts[key] = candidate
            return MergeResult(MergeOutcome.CHANGED, candidate, semantic_changed=True)

        same_value = incumbent.normalized_value == candidate.normalized_value
        same_tier = incumbent.precedence_tier == candidate.precedence_tier

        if same_value:
            return self._enrich(incumbent, candidate)

        if candidate.precedence_tier < incumbent.precedence_tier:
            # Stronger tier replaces the incumbent.
            return self._replace(key, incumbent, candidate)

        if candidate.precedence_tier > incumbent.precedence_tier:
            # Weaker tier disagreeing: keep incumbent, record a contradiction.
            contradiction = Contradiction(
                update.subject, update.predicate,
                incumbent.normalized_value, candidate.normalized_value,
                reason="weaker-tier disagreement",
            )
            self.contradictions.append(contradiction)
            return MergeResult(MergeOutcome.CONTRADICTION, incumbent, False, contradiction)

        # Same tier, different value: deterministic tie-break.
        if candidate.dominance() < incumbent.dominance():
            return self._replace(key, incumbent, candidate)
        return MergeResult(MergeOutcome.REJECTED, incumbent, False)

    # -- helpers ----------------------------------------------------------
    def _to_fact(self, update: FactUpdate, pass_no: int) -> Fact:
        return Fact(
            subject=update.subject,
            predicate=update.predicate,
            value=update.value,
            normalized_value=update.normalized_value,
            confidence=update.confidence,
            evidence_ids=[e.id for e in update.evidence],
            producer_pass=pass_no,
            status=update.status,
            rendered_candidate=update.rendered_candidate or update.value,
            precedence_tier=update.precedence_tier,
        )

    def _enrich(self, incumbent: Fact, candidate: Fact) -> MergeResult:
        # Merge evidence (dedup, stable order) and raise confidence.
        for eid in candidate.evidence_ids:
            if eid not in incumbent.evidence_ids:
                incumbent.evidence_ids.append(eid)
        if candidate.confidence.value > incumbent.confidence.value:
            incumbent.confidence = candidate.confidence
        # Adopt the stronger tier if the enriching evidence is stronger.
        incumbent.precedence_tier = min(incumbent.precedence_tier, candidate.precedence_tier)
        return MergeResult(MergeOutcome.ENRICHED, incumbent, semantic_changed=False)

    def _replace(self, key, incumbent: Fact, candidate: Fact) -> MergeResult:
        incumbent.status = FactStatus.SUPERSEDED
        self.superseded.append(incumbent)
        # Carry the incumbent's evidence forward so provenance is not lost.
        for eid in incumbent.evidence_ids:
            if eid not in candidate.evidence_ids:
                candidate.evidence_ids.append(eid)
        self._facts[key] = candidate
        return MergeResult(MergeOutcome.CHANGED, candidate, semantic_changed=True, superseded=incumbent)
