"""
Test for a latent bug fix in ladder_to_dot.py: ModelGenerator._desc() must
truncate long descriptions the same way for plain strings and for bilingual
{en, it} dicts.

Bug: the original code did ``if len(desc) > 64: desc = desc[:61] + '…'``.
When ``desc`` is a bilingual dict (e.g. {"en": ..., "it": ...}), ``len(desc)``
is the number of keys (2), never > 64, so the truncation silently never
fires for bilingual descriptions, however long the strings inside are.

Fix: when desc is a dict, truncate each string value independently with the
exact same 64-char rule, preserving the dict shape. Plain-string behavior
must stay byte-identical to before.
"""

from __future__ import annotations

import sys
from pathlib import Path

_TESTS_DIR = Path(__file__).parent.resolve()
_DOCUMENTER_DIR = _TESTS_DIR.parent
if str(_DOCUMENTER_DIR) not in sys.path:
    sys.path.insert(0, str(_DOCUMENTER_DIR))

from l5x_documenter.ladder_to_dot import ModelGenerator  # noqa: E402

_LONG_EN = "E" * 70
_LONG_IT = "I" * 80
_SHORT_EN = "short english"
_SHORT_IT = "breve italiano"


def _expected_truncated(s: str) -> str:
    return s[:61] + "…" if len(s) > 64 else s


def test_desc_truncates_plain_string_unchanged():
    """Plain-string truncation stays byte-identical to the pre-fix behavior."""
    gen = ModelGenerator(tag_descriptions={"LongTag": _LONG_EN})
    result = gen._desc("LongTag")
    assert isinstance(result, str)
    assert result == _LONG_EN[:61] + "…"
    assert len(result) == 62


def test_desc_plain_string_short_untouched():
    gen = ModelGenerator(tag_descriptions={"ShortTag": _SHORT_EN})
    result = gen._desc("ShortTag")
    assert result == _SHORT_EN


def test_desc_truncates_bilingual_dict_independently():
    """Each language side of a bilingual dict is truncated by the same
    64-char rule, independently, and the dict shape is preserved."""
    gen = ModelGenerator(tag_descriptions={
        "BilingualTag": {"en": _LONG_EN, "it": _LONG_IT},
    })
    result = gen._desc("BilingualTag")
    assert isinstance(result, dict)
    assert set(result.keys()) == {"en", "it"}
    assert result["en"] == _LONG_EN[:61] + "…"
    assert result["it"] == _LONG_IT[:61] + "…"
    assert len(result["en"]) == 62
    assert len(result["it"]) == 62


def test_desc_bilingual_dict_short_untouched():
    gen = ModelGenerator(tag_descriptions={
        "ShortBilingualTag": {"en": _SHORT_EN, "it": _SHORT_IT},
    })
    result = gen._desc("ShortBilingualTag")
    assert result == {"en": _SHORT_EN, "it": _SHORT_IT}


def test_desc_bilingual_dict_mixed_lengths():
    """One side long, one side short: only the long side is truncated."""
    gen = ModelGenerator(tag_descriptions={
        "MixedTag": {"en": _LONG_EN, "it": _SHORT_IT},
    })
    result = gen._desc("MixedTag")
    assert result == {"en": _LONG_EN[:61] + "…", "it": _SHORT_IT}


def test_desc_empty_or_missing_tag_returns_empty_string():
    gen = ModelGenerator(tag_descriptions={"Foo": "bar"})
    assert gen._desc("") == ""
    assert gen._desc("NotThere") == ""
