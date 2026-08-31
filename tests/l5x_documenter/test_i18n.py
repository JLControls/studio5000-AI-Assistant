"""
Tests for i18n module: lang_detect, seed glossary, and harvest tool.

Run with: python -m pytest tests/test_i18n.py -q
(from the documenter directory, using the .venv Python)
"""

import json
import os
import sys
import subprocess
import pytest

import l5x_documenter
from l5x_documenter.i18n.lang_detect import looks_italian  # noqa: E402

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
# The package directory (src/l5x_documenter), not the tests directory's
# parent — the test file lives at tests/l5x_documenter/, one level away from
# the package it exercises.
_DOCUMENTER_DIR = os.path.dirname(os.path.abspath(l5x_documenter.__file__))

_GLOSSARY_PATH = os.path.join(_DOCUMENTER_DIR, "i18n", "it_en_glossary.json")
_FIXTURE_PATH = os.path.join(_TESTS_DIR, "fixtures", "italian_snippet.l5x")
_FIXTURE_DIR = os.path.dirname(_FIXTURE_PATH)
_CANDIDATES_PATH = os.path.join(_DOCUMENTER_DIR, "i18n", "glossary_candidates.json")
_HARVEST_SCRIPT = os.path.join(_DOCUMENTER_DIR, "i18n", "harvest_glossary.py")


# ---------------------------------------------------------------------------
# looks_italian
# ---------------------------------------------------------------------------

class TestLooksItalian:
    """Positive and negative test cases for the Italian-detection heuristic."""

    def test_multi_word_italian_phrase(self):
        """Full Italian phrase with known words → True."""
        assert looks_italian("barriera sicurezza accesso stazione") is True

    def test_nastro_trasportatore(self):
        """Two-word Italian phrase → True."""
        assert looks_italian("nastro trasportatore") is True

    def test_accented_text(self):
        """Text with Italian accented characters → True."""
        assert looks_italian("velocità di rotazione") is True

    def test_zione_ending(self):
        """Word ending in -zione (Italian suffix) → True."""
        assert looks_italian("comunicazione seriale") is True

    def test_aggio_ending(self):
        """Word ending in -aggio → True."""
        assert looks_italian("cablaggio elettrico") is True

    def test_ita_ending(self):
        """Word ending in -ità → True."""
        assert looks_italian("disponibilità del sistema") is True

    def test_logic_false(self):
        """Plain English word → False."""
        assert looks_italian("Logic") is False

    def test_continuous_false(self):
        """English word that starts like Italian → False."""
        assert looks_italian("Continuous") is False

    def test_month_false(self):
        """English phrase with numbers → False."""
        assert looks_italian("The month (1 - 12)") is False

    def test_datetime_structure_false(self):
        """English technical description → False."""
        assert looks_italian("Structure for the DateTime") is False

    def test_empty_string_false(self):
        """Empty input → False."""
        assert looks_italian("") is False

    def test_pure_number_false(self):
        """Pure numeric string → False."""
        assert looks_italian("123") is False


# ---------------------------------------------------------------------------
# Seed glossary
# ---------------------------------------------------------------------------

class TestSeedGlossary:
    """Validate the committed it_en_glossary.json."""

    def _load(self):
        assert os.path.exists(_GLOSSARY_PATH), (
            f"it_en_glossary.json not found at {_GLOSSARY_PATH}. "
            "Run: python i18n/build_seed_glossary.py"
        )
        with open(_GLOSSARY_PATH, encoding="utf-8") as fh:
            return json.load(fh)

    def test_glossary_loads(self):
        """File exists and parses as JSON."""
        glossary = self._load()
        assert isinstance(glossary, dict)

    def test_glossary_has_over_200_entries(self):
        """Merged glossary must have >200 entries (181 + ~86 with overlap)."""
        glossary = self._load()
        assert len(glossary) > 200, f"Only {len(glossary)} entries found"

    def test_all_entries_have_nonempty_en(self):
        """Every entry must have a non-empty 'en' translation."""
        glossary = self._load()
        empty = [k for k, v in glossary.items() if not v.get("en")]
        assert empty == [], f"Entries with empty 'en': {empty[:5]}"

    def test_all_entries_have_numeric_confidence(self):
        """Every entry must have a numeric 'confidence' field."""
        glossary = self._load()
        bad = [k for k, v in glossary.items()
               if not isinstance(v.get("confidence"), (int, float))]
        assert bad == [], f"Entries with non-numeric confidence: {bad[:5]}"

    def test_known_automation_dict_entry_present(self):
        """Key from ITALIAN_AUTOMATION_DICT must be in the glossary."""
        glossary = self._load()
        assert "motore" in glossary, "'motore' missing from glossary"
        assert "nastro" in glossary, "'nastro' missing from glossary"

    def test_keys_are_lowercase(self):
        """All glossary keys should be lowercase-stripped (normalization rule)."""
        glossary = self._load()
        bad = [k for k in glossary if k != k.lower().strip()]
        assert bad == [], f"Non-lowercase keys found: {bad[:5]}"


# ---------------------------------------------------------------------------
# Harvest extraction (offline, uses fixture L5X)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def harvest_candidates():
    """Run harvest_glossary.py against the fixture dir and return candidates dict."""
    assert os.path.exists(_FIXTURE_PATH), f"Fixture not found: {_FIXTURE_PATH}"
    result = subprocess.run(
        [sys.executable, _HARVEST_SCRIPT, _FIXTURE_DIR],
        cwd=_DOCUMENTER_DIR,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"harvest_glossary.py exited with code {result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert os.path.exists(_CANDIDATES_PATH), (
        f"glossary_candidates.json not written to {_CANDIDATES_PATH}"
    )
    with open(_CANDIDATES_PATH, encoding="utf-8") as fh:
        return json.load(fh)


class TestHarvestExtraction:
    """Verify the harvest tool produces correct candidates from the fixture L5X."""

    def test_fixture_exists(self):
        """Fixture file must exist."""
        assert os.path.exists(_FIXTURE_PATH)

    def test_lubrificazione_is_candidate(self, harvest_candidates):
        """'lubrificazione' is Italian, not in glossary → must appear as candidate."""
        assert "lubrificazione" in harvest_candidates, (
            f"'lubrificazione' missing. Candidates: {list(harvest_candidates.keys())}"
        )

    def test_nastro_excluded_from_candidates(self, harvest_candidates):
        """'nastro' is in the glossary → must NOT appear as candidate."""
        assert "nastro" not in harvest_candidates, (
            "'nastro' should be excluded (already in glossary)"
        )

    def test_motor_excluded_from_candidates(self, harvest_candidates):
        """'motor' is English → looks_italian returns False → must not appear."""
        assert "motor" not in harvest_candidates, (
            "'motor' should be excluded (not Italian)"
        )

    def test_running_excluded(self, harvest_candidates):
        """English word 'running' must not appear."""
        assert "running" not in harvest_candidates

    def test_candidate_schema(self, harvest_candidates):
        """Every candidate entry must have the required schema fields."""
        for key, val in harvest_candidates.items():
            assert "en" in val, f"Candidate {key!r} missing 'en'"
            assert "frequency" in val, f"Candidate {key!r} missing 'frequency'"
            assert "confidence" in val, f"Candidate {key!r} missing 'confidence'"
            assert "files" in val, f"Candidate {key!r} missing 'files'"
            assert isinstance(val["frequency"], int), f"Candidate {key!r} frequency not int"
            assert isinstance(val["files"], int), f"Candidate {key!r} files not int"
