"""Unit tests for FactStore merge/precedence/contradiction (Checkpoint 3)."""

from comment_graph.model import Confidence, operand_entity
from comment_graph.facts import (
    EvidenceKind,
    Evidence,
    FactStatus,
    FactUpdate,
    FactStore,
    MergeOutcome,
)

SUBJ = operand_entity("N101[18]")
PRED = "description"


def _update(value, normalized, kind, confidence=Confidence.HIGH, source=None):
    return FactUpdate(
        subject=SUBJ,
        predicate=PRED,
        value=value,
        normalized_value=normalized,
        confidence=confidence,
        evidence=[Evidence(kind=kind, detail=value, source=source)],
        status=FactStatus.OBSERVED,
        rendered_candidate=value,
    )


class TestNewFact:
    def test_first_fact_is_a_semantic_change(self):
        store = FactStore()
        res = store.merge(_update("temp", "temp", EvidenceKind.NATIVE_COMMENT), pass_no=1)
        assert res.outcome is MergeOutcome.CHANGED
        assert res.semantic_changed is True
        assert store.get(SUBJ, PRED).normalized_value == "temp"


class TestEnrichment:
    def test_same_tier_same_value_enriches_without_semantic_change(self):
        store = FactStore()
        store.merge(_update("temp", "temp", EvidenceKind.LOGIC_METADATA, Confidence.MEDIUM, source="datatype"), 1)
        res = store.merge(_update("temp", "temp", EvidenceKind.LOGIC_METADATA, Confidence.HIGH, source="module"), 2)
        assert res.outcome is MergeOutcome.ENRICHED
        assert res.semantic_changed is False
        # confidence raised, two distinct pieces of evidence retained
        fact = store.get(SUBJ, PRED)
        assert fact.confidence is Confidence.HIGH
        assert len(fact.evidence_ids) == 2

    def test_prose_only_difference_is_not_semantic(self):
        store = FactStore()
        store.merge(_update("Thawing Room RTD", "temp", EvidenceKind.NATIVE_COMMENT), 1)
        res = store.merge(_update("thawing room rtd", "temp", EvidenceKind.NATIVE_COMMENT), 2)
        assert res.semantic_changed is False
        assert res.outcome is MergeOutcome.ENRICHED


class TestPrecedence:
    def test_stronger_tier_replaces_and_supersedes(self):
        store = FactStore()
        store.merge(_update("guess", "guess", EvidenceKind.MODEL_INFERENCE), 1)
        res = store.merge(_update("temp", "temp", EvidenceKind.NATIVE_COMMENT), 2)
        assert res.outcome is MergeOutcome.CHANGED
        assert res.semantic_changed is True
        assert res.superseded is not None
        assert res.superseded.status is FactStatus.SUPERSEDED
        assert store.get(SUBJ, PRED).normalized_value == "temp"

    def test_weaker_tier_same_value_enriches(self):
        store = FactStore()
        store.merge(_update("temp", "temp", EvidenceKind.NATIVE_COMMENT), 1)
        res = store.merge(_update("temp", "temp", EvidenceKind.MODEL_INFERENCE), 2)
        assert res.outcome is MergeOutcome.ENRICHED
        assert res.semantic_changed is False


class TestContradiction:
    def test_weaker_tier_different_value_is_contradiction_incumbent_kept(self):
        store = FactStore()
        store.merge(_update("temp", "temp", EvidenceKind.NATIVE_COMMENT), 1)
        res = store.merge(_update("pressure", "pressure", EvidenceKind.MODEL_INFERENCE), 2)
        assert res.outcome is MergeOutcome.CONTRADICTION
        assert res.contradiction is not None
        assert store.get(SUBJ, PRED).normalized_value == "temp"  # incumbent kept
        assert res.semantic_changed is False


class TestSameTierTieBreak:
    def test_higher_confidence_wins(self):
        store = FactStore()
        store.merge(_update("a", "a", EvidenceKind.LOGIC_METADATA, Confidence.LOW), 1)
        res = store.merge(_update("b", "b", EvidenceKind.LOGIC_METADATA, Confidence.HIGH), 2)
        assert res.outcome is MergeOutcome.CHANGED
        assert store.get(SUBJ, PRED).normalized_value == "b"

    def test_equal_confidence_tiebreak_is_order_independent(self):
        # Whichever order "a" and "b" arrive, lexical tie-break must pick "a".
        s1 = FactStore()
        s1.merge(_update("a", "a", EvidenceKind.LOGIC_METADATA, Confidence.MEDIUM), 1)
        s1.merge(_update("b", "b", EvidenceKind.LOGIC_METADATA, Confidence.MEDIUM), 2)

        s2 = FactStore()
        s2.merge(_update("b", "b", EvidenceKind.LOGIC_METADATA, Confidence.MEDIUM), 1)
        s2.merge(_update("a", "a", EvidenceKind.LOGIC_METADATA, Confidence.MEDIUM), 2)

        assert s1.get(SUBJ, PRED).normalized_value == s2.get(SUBJ, PRED).normalized_value == "a"

    def test_losing_update_is_rejected(self):
        store = FactStore()
        store.merge(_update("a", "a", EvidenceKind.LOGIC_METADATA, Confidence.MEDIUM), 1)
        res = store.merge(_update("b", "b", EvidenceKind.LOGIC_METADATA, Confidence.MEDIUM), 2)
        assert res.outcome is MergeOutcome.REJECTED


class TestEvidencePrecedenceOrdering:
    def test_tier_values_follow_spec_order(self):
        assert EvidenceKind.NATIVE_COMMENT.value < EvidenceKind.USER_DECISION.value
        assert EvidenceKind.USER_DECISION.value < EvidenceKind.LOGIC_METADATA.value
        assert EvidenceKind.LOGIC_METADATA.value < EvidenceKind.PRIOR_MEMORY.value
        assert EvidenceKind.PRIOR_MEMORY.value < EvidenceKind.INSTRUCTION_DOC.value
        assert EvidenceKind.INSTRUCTION_DOC.value < EvidenceKind.VECTOR_RETRIEVAL.value
        assert EvidenceKind.VECTOR_RETRIEVAL.value < EvidenceKind.MODEL_INFERENCE.value
