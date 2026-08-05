"""Unit tests for DeterministicWorker + escalation tiering (Checkpoint 4)."""

from comment_graph.model import Confidence, operand_entity
from comment_graph.facts import Fact, FactStatus, EvidenceKind
from comment_graph.worker import (
    WorkerContext,
    DeterministicWorker,
    ModelLevel,
    suggest_model_level,
)

ENTITY = operand_entity("N18[1]")


def _neighbor_fact(value, normalized, confidence, tier, status=FactStatus.OBSERVED):
    return Fact(
        subject=operand_entity("N101[18]"),
        predicate="description",
        value=value,
        normalized_value=normalized,
        confidence=confidence,
        precedence_tier=tier,
        status=status,
    )


class TestNativeComment:
    def test_native_comment_becomes_observed_high_fact(self):
        ctx = WorkerContext(entity=ENTITY, native_comment="calibrated temperature")
        result = DeterministicWorker().analyze(ctx)
        assert len(result.fact_updates) == 1
        update = result.fact_updates[0]
        assert update.value == "calibrated temperature"
        assert update.confidence is Confidence.HIGH
        assert update.status is FactStatus.OBSERVED
        assert update.evidence[0].kind is EvidenceKind.NATIVE_COMMENT
        assert result.assistance_requests == []


class TestMetadata:
    def test_metadata_becomes_medium_fact_when_no_comment(self):
        ctx = WorkerContext(entity=ENTITY, metadata="RTD input channel")
        result = DeterministicWorker().analyze(ctx)
        update = result.fact_updates[0]
        assert update.confidence is Confidence.MEDIUM
        assert update.evidence[0].kind is EvidenceKind.LOGIC_METADATA


class TestPropagation:
    def test_single_stable_neighbor_infers_stepped_down(self):
        neighbor = _neighbor_fact(
            "calibrated temperature", "calibrated temperature",
            Confidence.HIGH, EvidenceKind.NATIVE_COMMENT.value,
        )
        ctx = WorkerContext(entity=ENTITY, neighbor_facts=(neighbor,))
        result = DeterministicWorker().analyze(ctx)
        assert len(result.fact_updates) == 1
        update = result.fact_updates[0]
        assert update.status is FactStatus.INFERRED
        assert update.confidence is Confidence.MEDIUM  # stepped down from HIGH
        assert result.assistance_requests == []


class TestEscalation:
    def test_two_incompatible_neighbors_escalate(self):
        n1 = _neighbor_fact("temperature", "temperature", Confidence.HIGH, EvidenceKind.LOGIC_METADATA.value)
        n2 = _neighbor_fact("pressure", "pressure", Confidence.HIGH, EvidenceKind.LOGIC_METADATA.value)
        ctx = WorkerContext(entity=ENTITY, neighbor_facts=(n1, n2))
        result = DeterministicWorker().analyze(ctx)
        assert result.fact_updates == []
        assert len(result.assistance_requests) == 1
        req = result.assistance_requests[0]
        assert set(req.candidate_values) == {"temperature", "pressure"}
        assert req.suggested_model_level is ModelLevel.SONNET

    def test_unresolved_instruction_escalates(self):
        ctx = WorkerContext(entity=ENTITY, unresolved_instruction=True)
        result = DeterministicWorker().analyze(ctx)
        assert len(result.assistance_requests) == 1

    def test_only_low_confidence_neighbors_escalate(self):
        low = _neighbor_fact("maybe temp", "maybe temp", Confidence.LOW, EvidenceKind.MODEL_INFERENCE.value)
        ctx = WorkerContext(entity=ENTITY, neighbor_facts=(low,))
        result = DeterministicWorker().analyze(ctx)
        assert result.fact_updates == []
        assert len(result.assistance_requests) == 1

    def test_tier1_conflict_escalates_to_opus(self):
        n1 = _neighbor_fact("temp A", "temp a", Confidence.HIGH, EvidenceKind.NATIVE_COMMENT.value)
        n2 = _neighbor_fact("temp B", "temp b", Confidence.HIGH, EvidenceKind.NATIVE_COMMENT.value)
        ctx = WorkerContext(entity=ENTITY, neighbor_facts=(n1, n2))
        result = DeterministicWorker().analyze(ctx)
        assert result.assistance_requests[0].suggested_model_level is ModelLevel.OPUS


class TestSuggestModelLevel:
    def test_haiku_for_single_mechanical_reword(self):
        assert suggest_model_level(1, 0, in_cycle=False, tier1_conflict=False) is ModelLevel.HAIKU

    def test_sonnet_for_multiple_candidates(self):
        assert suggest_model_level(3, 2, in_cycle=False, tier1_conflict=False) is ModelLevel.SONNET

    def test_sonnet_for_no_local_evidence(self):
        assert suggest_model_level(0, 0, in_cycle=False, tier1_conflict=False) is ModelLevel.SONNET

    def test_opus_when_in_cycle(self):
        assert suggest_model_level(1, 1, in_cycle=True, tier1_conflict=False) is ModelLevel.OPUS

    def test_opus_on_tier1_conflict(self):
        assert suggest_model_level(2, 2, in_cycle=False, tier1_conflict=True) is ModelLevel.OPUS

    def test_opus_for_large_neighborhood(self):
        assert suggest_model_level(1, 8, in_cycle=False, tier1_conflict=False) is ModelLevel.OPUS
