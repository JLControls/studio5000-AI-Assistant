"""
Tests for Task 5: per-file Italian-source detection + CLI wiring.

All tests run fully offline (use_online=False; no network — no deep-translator
calls are exercised by any fixture here).

Ported from documenter/tests/test_detection.py (pre-migration main.py) to the
l5x_documenter.pipeline API: process_single_file/process_directory are now
internal helpers behind the single public pipeline.document() entry point.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pytest

from l5x_documenter.pipeline import document, is_italian_source

_FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# 1. is_italian_source — path pattern matching
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    r"F:\Copia\Perry-Sanitation\ComboWasher-Colussi\plc\x.l5x",
    "/x/RackLoading-Vemac/plc/y.L5X",
    "foo/VEMAC/z.l5x",
    "foo/colussi/z.l5x",
    "F:/Copia/Line1/Machine-COLUSSI/plc/a.l5x",
])
def test_is_italian_source_true(path):
    assert is_italian_source(path) is True


@pytest.mark.parametrize("path", [
    "Perry-Ovens/Oven1-Alkar/plc/x.l5x",
    "F:/Copia/Laurens-DryCells/plc/DRY_1.l5x",
    "/some/normal/path/machine.l5x",
    "",
])
def test_is_italian_source_false(path):
    assert is_italian_source(path) is False


def test_is_italian_source_accepts_path_objects():
    assert is_italian_source(Path("foo/Bar-Vemac/plc/x.l5x")) is True
    assert is_italian_source(Path("foo/Bar-Alkar/plc/x.l5x")) is False


# ---------------------------------------------------------------------------
# 2. Override resolution (tri-state): override if not None, else auto-detect
# ---------------------------------------------------------------------------

def _resolve_bilingual(override: Optional[bool], path) -> bool:
    """Mirrors the resolution rule pipeline.document() applies per file."""
    return override if override is not None else is_italian_source(path)


def test_override_resolution():
    italian_path = r"F:\Copia\Perry-Sanitation\ComboWasher-Colussi\plc\x.l5x"
    english_path = "Perry-Ovens/Oven1-Alkar/plc/x.l5x"

    assert _resolve_bilingual(None, italian_path) is True
    assert _resolve_bilingual(None, english_path) is False
    assert _resolve_bilingual(False, italian_path) is False
    assert _resolve_bilingual(True, english_path) is True


# ---------------------------------------------------------------------------
# 3. GOLDEN: per-file auto-detection end-to-end via document() on a directory
# ---------------------------------------------------------------------------

def _find_generated(generated: list[Path], stem_prefix: str) -> Path:
    for p in generated:
        if p.name.startswith(stem_prefix):
            return p
    raise AssertionError(
        f"No generated file starting with {stem_prefix!r} in {[p.name for p in generated]}"
    )


def test_golden_per_file_auto_detection(tmp_path):
    output_dir = tmp_path / "out"

    result = document(
        _FIXTURES_DIR,
        output=output_dir,
        translate_override=None,
        verbose=False,
        use_online=False,
        # A directory run also writes index.html into the *source* directory
        # (workspace_root), not just `output`; suppress it here so the test
        # doesn't drop a generated file into the committed fixtures/ tree.
        no_index=True,
    )
    assert result["success"], result.get("error")
    generated = result["generated"]

    vemac_html = _find_generated(generated, "VemacDetectController")
    alkar_html = _find_generated(generated, "AlkarDetectController")

    vemac_content = vemac_html.read_text(encoding="utf-8")
    alkar_content = alkar_html.read_text(encoding="utf-8")

    # Vemac (Italian-integrator path) auto-detected bilingual
    assert 'class="i18n"' in vemac_content
    assert 'id="lang-toggle"' in vemac_content
    assert '<body data-lang="en"' in vemac_content

    # Alkar (non-Italian-integrator path) stays byte-clean English
    assert 'class="i18n"' not in alkar_content
    assert 'id="lang-toggle"' not in alkar_content
    assert '<body data-lang="en"' not in alkar_content


# ---------------------------------------------------------------------------
# 4. Manual override end-to-end (per file, via document() on a single file)
# ---------------------------------------------------------------------------

def test_override_false_forces_english_for_vemac(tmp_path):
    vemac_file = _FIXTURES_DIR / "Detect-Vemac" / "mini.l5x"
    output_dir = tmp_path / "vemac_off"

    result = document(
        vemac_file,
        output=output_dir,
        translate_override=False,
        verbose=False,
        use_online=False,
    )

    assert result["success"], result.get("error")
    content = result["generated"][0].read_text(encoding="utf-8")
    assert 'class="i18n"' not in content


def test_override_true_forces_bilingual_for_alkar(tmp_path):
    alkar_file = _FIXTURES_DIR / "Detect-Alkar" / "mini.l5x"
    output_dir = tmp_path / "alkar_on"

    result = document(
        alkar_file,
        output=output_dir,
        translate_override=True,
        verbose=False,
        use_online=False,
    )

    assert result["success"], result.get("error")
    content = result["generated"][0].read_text(encoding="utf-8")
    assert 'class="i18n"' in content
    assert 'id="lang-toggle"' in content
    assert '<body data-lang="en"' in content
