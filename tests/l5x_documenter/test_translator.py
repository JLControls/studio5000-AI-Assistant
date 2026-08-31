"""
Tests for the bilingual translator module.

All tests run fully offline — deep_translator is mocked via sys.modules
injection, so no network is required.

Run with: python -m pytest tests/test_translator.py -q
(from the documenter directory)
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock
import pytest

# ---------------------------------------------------------------------------
# Ensure documenter dir is in sys.path so 'import translator' works
# ---------------------------------------------------------------------------

_TESTS_DIR = Path(__file__).parent.resolve()
_DOCUMENTER_DIR = _TESTS_DIR.parent
if str(_DOCUMENTER_DIR) not in sys.path:
    sys.path.insert(0, str(_DOCUMENTER_DIR))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_module_singleton():
    """Reset the module-level _translator singleton before/after each test."""
    import l5x_documenter.translator as t_mod
    t_mod._translator = None
    yield
    t_mod._translator = None


@pytest.fixture
def mock_google_translate(monkeypatch):
    """
    Inject a fake deep_translator module into sys.modules so the lazy
    'from deep_translator import GoogleTranslator' inside _mt_cached()
    resolves to a MagicMock — no network required.

    Returns (mock_gt_class, mock_gt_instance) so tests can configure
    return values and assert call counts.
    """
    mock_gt_instance = MagicMock()
    mock_gt_instance.translate.return_value = "mocked English"

    mock_gt_class = MagicMock(return_value=mock_gt_instance)

    mock_dt_module = MagicMock()
    mock_dt_module.GoogleTranslator = mock_gt_class

    monkeypatch.setitem(sys.modules, "deep_translator", mock_dt_module)
    return mock_gt_class, mock_gt_instance


# ---------------------------------------------------------------------------
# translate_text — offline cases
# ---------------------------------------------------------------------------

class TestTranslateTextOffline:

    def test_english_input_unchanged(self):
        """Plain English string → (text, text) with no modification."""
        from l5x_documenter.translator import translate_text
        result = translate_text("Motor running")
        assert result == ("Motor running", "Motor running")

    def test_parenthetical_english_unchanged(self):
        """English phrase with parenthetical numbers → (text, text)."""
        from l5x_documenter.translator import translate_text
        result = translate_text("The month (1 - 12)")
        assert result == ("The month (1 - 12)", "The month (1 - 12)")

    def test_falsy_input(self):
        """Empty string → ('', '') without error."""
        from l5x_documenter.translator import translate_text
        assert translate_text("") == ("", "")

    def test_exact_phrase_glossary_hit_single_word(self):
        """
        'motore' is in the glossary with en='motor'.
        Exact-phrase path (step 2) should return ('motor', 'motore').
        """
        from l5x_documenter.translator import translate_text
        en, it = translate_text("motore")
        assert en == "motor"
        assert it == "motore"

    def test_exact_phrase_glossary_hit_multi_word(self):
        """
        'in marcia' is in the glossary with en='running'.
        Exact-phrase path should return the curated translation.
        """
        from l5x_documenter.translator import translate_text
        en, it = translate_text("in marcia")
        assert en == "running"
        assert it == "in marcia"

    def test_partial_glossary_substitution(self):
        """
        Multi-word Italian string where one known term is substituted but
        the rest is kept.  Original Italian is preserved in the second element.
        'nastro' is in the glossary as 'conveyor'; 'corrente' is NOT.
        """
        from l5x_documenter.translator import translate_text
        en, it = translate_text("nastro corrente")
        assert it == "nastro corrente"        # original always preserved
        assert "conveyor" in en.lower()       # 'nastro' was substituted

    def test_use_online_false_mt_not_invoked(self, mock_google_translate):
        """
        use_online=False → MT is never called, even when Italian residual remains.
        'nastro à': nastro→conveyor, accented 'à' stays → residual Italian.
        """
        from l5x_documenter.translator import translate_text
        _, mock_gt_instance = mock_google_translate

        translate_text("nastro à", use_online=False)

        mock_gt_instance.translate.assert_not_called()


# ---------------------------------------------------------------------------
# translate_text — online / cache cases
# ---------------------------------------------------------------------------

class TestTranslateTextOnline:

    def test_use_online_true_mt_invoked(self, mock_google_translate, tmp_path):
        """
        use_online=True with residual Italian after glossary substitution
        → GoogleTranslator.translate() is called exactly once.
        'nastro à': nastro→conveyor, accented 'à' stays (looks_italian→True).
        """
        from l5x_documenter.translator import Translator
        _, mock_gt_instance = mock_google_translate
        mock_gt_instance.translate.return_value = "conveyor in English"

        t = Translator(cache_path=str(tmp_path / "cache.json"))
        en, it = t.translate_text("nastro à", use_online=True)

        assert it == "nastro à"                # original preserved
        mock_gt_instance.translate.assert_called_once()

    def test_mt_exception_non_fatal_fallback(self, mock_google_translate, tmp_path):
        """
        MT raising an exception → non-fatal; result falls back to the
        glossary-substituted partial (does NOT raise to the caller).
        """
        from l5x_documenter.translator import Translator
        _, mock_gt_instance = mock_google_translate
        mock_gt_instance.translate.side_effect = RuntimeError("network error")

        t = Translator(cache_path=str(tmp_path / "cache.json"))
        # Should not raise
        en, it = t.translate_text("nastro à", use_online=True)

        assert it == "nastro à"           # original preserved
        assert "conveyor" in en.lower()        # glossary partial returned

    def test_cache_mt_called_only_once(self, mock_google_translate, tmp_path):
        """
        Two identical online translation requests → underlying MT called exactly
        once; the second hit is served from the in-memory + on-disk cache.
        Cache file must be written after the first call.
        """
        from l5x_documenter.translator import Translator
        _, mock_gt_instance = mock_google_translate
        mock_gt_instance.translate.return_value = "conveyor in English"

        cache_file = str(tmp_path / "test_cache.json")
        t = Translator(cache_path=cache_file)

        text = "nastro à"
        t.translate_text(text, use_online=True)
        t.translate_text(text, use_online=True)

        assert mock_gt_instance.translate.call_count == 1
        assert os.path.exists(cache_file)


# ---------------------------------------------------------------------------
# translate_identifier
# ---------------------------------------------------------------------------

class TestTranslateIdentifier:

    def test_italian_name_returns_parens_form(self):
        """
        Italian identifier → {"it": name, "en": "name (EnglishVersion)"}.
        'Nastro1': nastro→conveyor → title → 'Conveyor'; '1' kept → 'Conveyor1'.
        """
        from l5x_documenter.translator import translate_identifier
        result = translate_identifier("Nastro1")
        assert result["it"] == "Nastro1"
        assert result["en"] == "Nastro1 (Conveyor1)"

    def test_english_name_passthrough_no_parens(self):
        """
        English identifier → {"it": name, "en": name} with NO parenthetical.
        'Logic' is not Italian.
        """
        from l5x_documenter.translator import translate_identifier
        result = translate_identifier("Logic")
        assert result["it"] == "Logic"
        assert result["en"] == "Logic"
