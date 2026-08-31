"""Tests for the l5x_documenter MCP integration adapter.

Covers the two async entry points (``generate_plc_documentation``,
``split_l5x``) that back the ``generate_plc_documentation`` / ``split_l5x``
MCP tools: success shapes (output paths + summary counts, no file contents)
and bad-path error shapes. Follows the ``asyncio.run(coro)`` pattern used by
``tests/ignition_exporter/test_generate.py`` for the sibling
``*_mcp_integration.py`` adapter.
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from l5x_documenter.l5x_documenter_mcp_integration import L5XDocumenterMCPIntegration

_FIXTURES_DIR = Path(__file__).parent / "fixtures"
_ALKAR_L5X = _FIXTURES_DIR / "Detect-Alkar" / "mini.l5x"
_VEMAC_L5X = _FIXTURES_DIR / "Detect-Vemac" / "mini.l5x"


def _run(coro):
    return asyncio.run(coro)


def _engine() -> L5XDocumenterMCPIntegration:
    return L5XDocumenterMCPIntegration()


# ---------------------------------------------------------------------------
# generate_plc_documentation -- success shapes
# ---------------------------------------------------------------------------

def test_generate_plc_documentation_single_file(tmp_path):
    out_dir = tmp_path / "docs"
    result = _run(_engine().generate_plc_documentation(
        str(_ALKAR_L5X), output_dir=str(out_dir),
    ))

    assert result["success"] is True
    assert result["mode"] == "document"
    assert result["documents_generated"] == 1
    assert len(result["generated"]) == 1

    generated_path = Path(result["generated"][0])
    assert generated_path.exists()
    assert generated_path.name == "AlkarDetectController_Documentation.html"
    # Path only, never file contents, in the result payload.
    assert "AlkarDetectController_Documentation.html" not in str(result.get("generated_content", ""))


def test_generate_plc_documentation_translate_override_passthrough(tmp_path):
    """translate=True forces bilingual output even for a non-Colussi/Vemac path."""
    out_dir = tmp_path / "docs_bilingual"
    result = _run(_engine().generate_plc_documentation(
        str(_ALKAR_L5X), output_dir=str(out_dir), translate=True,
    ))

    assert result["success"] is True
    content = Path(result["generated"][0]).read_text(encoding="utf-8")
    assert 'id="lang-toggle"' in content


def test_generate_plc_documentation_directory_auto_detect(tmp_path):
    """Directory mode auto-detects per file from source path (no override).

    Copies the two Detect-* fixture dirs into tmp_path first: directory-mode
    document() also writes an index.html into the *source* directory (there's
    no no_index knob on this adapter), which must never land in the committed
    fixtures/ tree.
    """
    source_dir = tmp_path / "source"
    shutil.copytree(_FIXTURES_DIR / "Detect-Alkar", source_dir / "Detect-Alkar")
    shutil.copytree(_FIXTURES_DIR / "Detect-Vemac", source_dir / "Detect-Vemac")

    out_dir = tmp_path / "docs_dir"
    result = _run(_engine().generate_plc_documentation(
        str(source_dir), output_dir=str(out_dir),
    ))

    assert result["success"] is True
    assert result["documents_generated"] >= 2
    names = {Path(p).name for p in result["generated"]}
    assert "AlkarDetectController_Documentation.html" in names
    assert "VemacDetectController_Documentation.html" in names


# ---------------------------------------------------------------------------
# generate_plc_documentation -- bad-path / validation error shapes
# ---------------------------------------------------------------------------

def test_generate_plc_documentation_missing_input(tmp_path):
    missing = tmp_path / "does_not_exist.l5x"
    result = _run(_engine().generate_plc_documentation(str(missing)))

    assert result["success"] is False
    assert "error" in result
    assert "not found" in result["error"].lower()


def test_generate_plc_documentation_full_pipeline_requires_acd(tmp_path):
    result = _run(_engine().generate_plc_documentation(
        str(_ALKAR_L5X), full_pipeline=True,
    ))

    assert result["success"] is False
    assert "error" in result
    assert ".ACD" in result["error"] or "acd" in result["error"].lower()


def test_generate_plc_documentation_full_pipeline_reports_ignored_params(tmp_path):
    """A non-existent .acd input still validates full_pipeline's own precondition
    (is-ACD check) before touching the filesystem again for existence, so the
    missing-file check must fire first and ignored_params must never be reported
    for a request that failed outright."""
    missing_acd = tmp_path / "missing.acd"
    result = _run(_engine().generate_plc_documentation(
        str(missing_acd), full_pipeline=True, output_dir=str(tmp_path / "out"),
    ))

    assert result["success"] is False
    assert "not found" in result["error"].lower()
    assert "ignored_params" not in result


def test_generate_plc_documentation_non_l5x_file_rejected(tmp_path):
    bogus = tmp_path / "notes.txt"
    bogus.write_text("hello", encoding="utf-8")

    result = _run(_engine().generate_plc_documentation(str(bogus)))

    assert result["success"] is False
    assert "error" in result


# ---------------------------------------------------------------------------
# split_l5x -- success shape + counts from the index
# ---------------------------------------------------------------------------

def test_split_l5x_success_counts(tmp_path):
    out_dir = tmp_path / "split_out"
    result = _run(_engine().split_l5x(str(_ALKAR_L5X), output_dir=str(out_dir)))

    assert result["success"] is True
    assert Path(result["out_dir"]) == out_dir
    assert out_dir.exists()
    assert (out_dir / "_index.json").exists()
    assert (out_dir / "_tags.csv").exists()
    assert (out_dir / "_cross_references.json").exists()

    assert result["controller"] == "AlkarDetectController"
    assert result["programs"] == 1
    assert result["routines"] == 1
    assert result["aois"] == 0
    assert result["tags_indexed"] >= 0  # only tags actually referenced in rung text are xref'd


def test_split_l5x_default_output_dir(tmp_path):
    """No output_dir -> l5x_individual/ next to the source L5X (copied into tmp_path
    first so the test never writes under the committed fixtures/ tree)."""
    scratch_l5x = tmp_path / "mini.l5x"
    scratch_l5x.write_text(_ALKAR_L5X.read_text(encoding="utf-8"), encoding="utf-8")

    result = _run(_engine().split_l5x(str(scratch_l5x)))

    assert result["success"] is True
    expected_out = tmp_path / "l5x_individual"
    assert Path(result["out_dir"]) == expected_out
    assert expected_out.exists()


# ---------------------------------------------------------------------------
# split_l5x -- bad-path error shape
# ---------------------------------------------------------------------------

def test_split_l5x_missing_input(tmp_path):
    missing = tmp_path / "does_not_exist.l5x"
    result = _run(_engine().split_l5x(str(missing)))

    assert result["success"] is False
    assert "error" in result
    assert "not found" in result["error"].lower()
    assert "out_dir" not in result
