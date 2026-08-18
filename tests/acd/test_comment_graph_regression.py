"""End-to-end comment-graph regression on the real THAWROOM fixture (Ckpt 7).

Native ``.L5X`` is authoritative. The fixture is large (574K) and gitignored; we
parse it once here and never write to it.
"""

import asyncio
import tempfile
import unittest
from pathlib import Path

from comment_graph.builder import ModelBuilder
from comment_graph.model import operand_entity
from comment_graph.edges import Relation
from comment_graph.config import AnalysisRequest, ConvergenceStatus
from comment_graph.orchestrator import analyze_comment_graph

FIXTURE = Path(__file__).parent / "ModernTHAWROOM021722.L5X"
if not FIXTURE.exists():
    _nested = Path(__file__).parent / "ModernTHAWROOM021722" / "ModernTHAWROOM021722.L5X"
    if _nested.exists():
        FIXTURE = _nested

ACD_FIXTURE = Path(__file__).parent / "ModernTHAWROOM021722.ACD"
if not ACD_FIXTURE.exists():
    _nested_acd = Path(__file__).parent / "ModernTHAWROOM021722" / "ModernTHAWROOM021722.ACD"
    if _nested_acd.exists():
        ACD_FIXTURE = _nested_acd


@unittest.skipUnless(FIXTURE.exists(), "native L5X fixture not present")
class ThawroomCommentGraphRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = ModelBuilder().build(FIXTURE)
        cls.result = asyncio.run(
            analyze_comment_graph(AnalysisRequest(file_path=str(FIXTURE)))
        )

    def test_graph_has_n18_read_and_n101_write_feeds(self):
        g = self.build.graph
        n18, n101 = operand_entity("N18[1]"), operand_entity("N101[18]")
        self.assertTrue(g.has_node(n18))
        self.assertTrue(g.has_node(n101))
        # N18[1] feeds N101[18] (ADD(N18[1],1,N101[18]))
        feeds = [
            e for e in g.edges()
            if e.relation is Relation.FEEDS and e.src == n18 and e.dst == n101
        ]
        self.assertTrue(feeds, "expected FEEDS N18[1] -> N101[18]")
        # N101[18] is written; N18[1] is read.
        writes = [e for e in g.in_edges(n101) if e.relation is Relation.WRITES]
        reads = [e for e in g.in_edges(n18) if e.relation is Relation.READS]
        self.assertTrue(writes, "expected WRITES into N101[18]")
        self.assertTrue(reads, "expected READS into N18[1]")

    def test_native_comment_propagates_to_uncommented_module_input(self):
        # MOVE(ENETBRIDGE...Ch00.Data, N18[1]) then ADD(N18[1],1,N101[18]).
        # N18[1] carries a native "Scaled Input Temperature" comment (HIGH). The
        # uncommented module input Ch00.Data that FEEDS N18[1] must inherit that
        # meaning as an INFERRED (stepped-down) proposal — the plan's core case.
        decision = next(
            (d for d in self.result.decisions
             if d["NAME"] == "ENETBRIDGE_5069:1:I.Ch00.Data"),
            None,
        )
        self.assertIsNotNone(decision, "uncommented module input should gain a proposal")
        self.assertIn("temperature", decision["PROPOSED_DESCRIPTION"].lower())
        self.assertEqual(decision["STATUS"], "inferred")
        self.assertEqual(decision["CONFIDENCE"], "MEDIUM")  # stepped down from HIGH

    def test_ambiguous_operands_escalate_not_fabricate(self):
        # A well-commented project still has genuinely ambiguous operands; the
        # deterministic worker must ask for help rather than invent comments.
        self.assertTrue(self.result.assistance_requests)
        levels = {r["suggested_model_level"] for r in self.result.assistance_requests}
        self.assertTrue(levels <= {"haiku", "sonnet", "opus"})

    def test_result_reports_history_and_provenance(self):
        self.assertIsInstance(self.result.convergence_status, ConvergenceStatus)
        self.assertTrue(self.result.pass_history)
        prov = self.result.provenance
        self.assertEqual(prov["source_kind"], "native_l5x")
        self.assertTrue(prov["graph_digest"])
        self.assertTrue(prov["source_artifact_hash"])

    def test_decisions_exclude_natively_commented_operands(self):
        # N101[18] already has a native comment, so it must NOT appear as a
        # proposed decision (it is an observation, not a proposal).
        names = {d["NAME"] for d in self.result.decisions}
        self.assertNotIn("N101[18]", names)


@unittest.skipUnless(FIXTURE.exists(), "native L5X fixture not present")
class ThawroomDeliverables(unittest.TestCase):
    def test_generate_deliverables_from_converged_state(self):
        out_dir = tempfile.mkdtemp()
        mem = str(Path(tempfile.mkdtemp()) / "memory.json")
        result = asyncio.run(
            analyze_comment_graph(
                AnalysisRequest(
                    file_path=str(FIXTURE),
                    generate_deliverables=True,
                    output_dir=out_dir,
                    memory_file_path=mem,
                )
            )
        )
        deliverables = result.deliverables
        # Only converged decisions are rendered.
        self.assertEqual(deliverables["decisions"], len(result.decisions))
        self.assertTrue((Path(out_dir) / "Comment_Delta.CSV").exists())
        self.assertTrue((Path(out_dir) / "comment_review_report.html").exists())
        # Memory record carries the stale-reuse guards additively.
        memory = deliverables["memory"]
        self.assertTrue(memory["source_artifact_hash"])
        self.assertTrue(memory["graph_digest"])
        self.assertEqual(memory["convergence_status"], result.convergence_status.value)


@unittest.skipUnless(ACD_FIXTURE.exists(), "ACD fixture not present")
class ThawroomAcdPath(unittest.TestCase):
    def test_acd_conversion_path_retains_provenance(self):
        try:
            result = asyncio.run(
                analyze_comment_graph(AnalysisRequest(file_path=str(ACD_FIXTURE)))
            )
        except Exception as exc:  # vendored parser unavailable in some envs
            self.skipTest(f"ACD conversion unavailable: {exc}")
        self.assertEqual(result.provenance["source_kind"], "converted_acd")
        # Converted L5X is never labelled lossless: conversion note is retained.
        self.assertIn("conversion_warnings", result.provenance)
        self.assertTrue(result.decisions)


if __name__ == "__main__":
    unittest.main()
