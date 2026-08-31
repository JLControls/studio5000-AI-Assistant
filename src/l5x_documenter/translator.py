"""
Translation Module (bilingual edition)

Provides *non-destructive* Italian↔English translation services.
Every public function returns BOTH the English translation and the
original Italian so callers (html_generator) can emit togglable
bilingual HTML.

Public API
----------
translate_text(text, use_online=False) -> tuple[str, str]
    Returns (english, italian).

translate_identifier(name, use_online=False) -> dict
    Returns {"it": name, "en": display}.

get_translator(use_online=False) -> Translator
    Returns the module-level singleton.
"""

from __future__ import annotations

import json
import os
import re
import warnings
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Shared language detector — import once, no duplicate
# ---------------------------------------------------------------------------

_HERE = Path(__file__).parent

from .i18n.lang_detect import looks_italian

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_GLOSSARY_PATH: Path = _HERE / "i18n" / "it_en_glossary.json"

# The MT cache is a *runtime* artifact — an installed package must not write
# into its own package directory. It lives in an OS-conventional per-user
# cache location instead: $PLC_DOCGEN_CACHE_DIR if set, else
# %LOCALAPPDATA%\plc-docgen\cache on Windows, else ~/.cache/plc-docgen
# (POSIX fallback). The directory is created on first write.
#
# A read-only, packaged seed cache may still ship at i18n/translation_cache.json
# inside the package (a curated snapshot committed to source) — when present
# and the user cache file doesn't exist yet, it seeds the new cache on first
# load (see Translator.__init__). The packaged file itself is never written to.


def _default_cache_dir() -> Path:
    """Resolve the per-user MT cache directory (see module docstring above)."""
    env = os.environ.get("PLC_DOCGEN_CACHE_DIR")
    if env:
        return Path(env)

    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        return Path(local_appdata) / "plc-docgen" / "cache"

    return Path.home() / ".cache" / "plc-docgen"


_DEFAULT_CACHE_PATH: Path = _default_cache_dir() / "translation_cache.json"
_PACKAGED_SEED_CACHE_PATH: Path = _HERE / "i18n" / "translation_cache.json"

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_glossary(path: Path = _GLOSSARY_PATH) -> dict[str, dict]:
    """Load the curated glossary. Missing file → warn + return empty dict."""
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        warnings.warn(f"Glossary not found at {path}. Using empty glossary.")
        return {}


def _load_cache(path: Path | str) -> dict[str, str]:
    """Load the persistent MT cache. Missing or corrupt file → empty dict."""
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _sorted_glossary_keys(glossary: dict[str, dict]) -> list[str]:
    """
    Return keys sorted by word-count (desc) then length (desc).
    Multi-word / longer phrases are matched first to avoid partial-word
    replacements clobbering a longer phrase.
    """
    return sorted(
        glossary.keys(),
        key=lambda k: (len(k.split()), len(k)),
        reverse=True,
    )


# Regex to split camelCase / PascalCase / underscore identifiers,
# including digit runs and accented Latin characters.
_IDENTIFIER_SPLIT_RE = re.compile(
    r"[A-Z]?[a-z\xc0-\xff]+"   # word starting with optional uppercase
    r"|[A-Z]+(?=[A-Z]|$)"       # run of uppercase letters
    r"|\d+",                     # digit run
    re.UNICODE,
)


def _split_identifier(identifier: str) -> list[str]:
    """Split a camelCase / PascalCase / underscore / digit-suffix identifier."""
    parts: list[str] = []
    for segment in identifier.split("_"):
        words = _IDENTIFIER_SPLIT_RE.findall(segment)
        parts.extend(words if words else [segment])
    return parts


# ---------------------------------------------------------------------------
# Translator class
# ---------------------------------------------------------------------------


class Translator:
    """
    Non-destructive bilingual translator.

    Loads the curated glossary and a persistent MT cache once at init.
    Both translate_text() and translate_identifier() return *both* languages.
    """

    def __init__(self, cache_path: str | Path | None = None) -> None:
        self._glossary: dict[str, dict] = _load_glossary()
        self._sorted_keys: list[str] = _sorted_glossary_keys(self._glossary)
        # Pre-compile substitution patterns for performance
        self._patterns: list[tuple[re.Pattern, str]] = [
            (
                re.compile(r"\b" + re.escape(key) + r"\b", re.IGNORECASE),
                self._glossary[key]["en"],
            )
            for key in self._sorted_keys
        ]
        using_default_cache = cache_path is None
        self._cache_path: Path = (
            Path(cache_path) if cache_path is not None else _DEFAULT_CACHE_PATH
        )
        if using_default_cache and not self._cache_path.exists() and _PACKAGED_SEED_CACHE_PATH.exists():
            # First run on this machine: no per-user cache yet, but a
            # curated, read-only cache ships inside the package — seed the
            # new user cache from it. The packaged file itself is never
            # written to; the first _save_cache() call below writes the
            # seeded content out to _cache_path.
            self._cache: dict[str, str] = _load_cache(_PACKAGED_SEED_CACHE_PATH)
        else:
            self._cache: dict[str, str] = _load_cache(self._cache_path)

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def translate_text(self, text: str, use_online: bool = False) -> tuple[str, str]:
        """
        Return (english, italian).

        Algorithm:
        1. Falsy or not Italian → pass-through (text, text).
        2. Exact-phrase glossary hit → (curated_en, original).
        3. Longest-match glossary substitution → partial.
        4. Residual Italian + use_online → MT(partial); else english = partial.
        MT errors are caught and non-fatal → fall back to partial.
        """
        if not text or not looks_italian(text):
            return (text, text)

        it = text

        # Step 2: exact phrase match
        key = text.strip().lower()
        if key in self._glossary:
            return (self._glossary[key]["en"], it)

        # Step 3: longest-match glossary substitution
        partial = self._glossary_substitute(text)

        # Step 4: optionally machine-translate residual Italian
        english = partial
        if looks_italian(partial) and use_online:
            try:
                english = self._mt_cached(partial)
            except Exception:
                english = partial  # non-fatal fallback

        return (english, it)

    def translate_identifier(self, name: str, use_online: bool = False) -> dict:
        """
        Return {"it": name, "en": display}.

        English / non-Italian identifiers → {"it": name, "en": name} (no parens).
        Italian identifiers: split into word-parts, look up each in glossary,
        join + title-case → {"it": name, "en": "name (EnglishVersion)"}.
        Identifiers are glossary-only; MT is never applied per-word.
        """
        if not looks_italian(name):
            return {"it": name, "en": name}

        parts = _split_identifier(name)
        translated: list[str] = []
        for part in parts:
            low = part.lower()
            if low in self._glossary:
                translated.append(self._glossary[low]["en"].title())
            else:
                translated.append(part)

        english = "".join(translated)
        return {"it": name, "en": f"{name} ({english})"}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _glossary_substitute(self, text: str) -> str:
        """Apply pre-sorted longest-match glossary substitution."""
        result = text
        for pattern, replacement in self._patterns:
            result = pattern.sub(replacement, result)
        return result

    def _mt_cached(self, text: str) -> str:
        """
        Translate via Google Translate with write-through persistent cache.
        Raises on failure — caller must handle exceptions.
        """
        if text in self._cache:
            return self._cache[text]

        from deep_translator import GoogleTranslator  # lazy import

        translated = GoogleTranslator(source="it", target="en").translate(text)
        self._cache[text] = translated
        self._save_cache()
        return translated

    def _save_cache(self) -> None:
        """Write cache to disk (atomic rename, best-effort)."""
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._cache_path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self._cache, fh, ensure_ascii=False, indent=2)
                fh.write("\n")
            tmp.replace(self._cache_path)
        except Exception:
            pass  # cache write failure is non-fatal


# ---------------------------------------------------------------------------
# Module-level singleton + convenience functions
# ---------------------------------------------------------------------------

_translator: Optional[Translator] = None


def get_translator(use_online: bool = False) -> Translator:
    """Get or create the module-level Translator singleton."""
    global _translator
    if _translator is None:
        _translator = Translator()
    return _translator


def translate_text(text: str, use_online: bool = False) -> tuple[str, str]:
    """
    Return (english, italian).

    Convenience wrapper around the module singleton.
    """
    return get_translator().translate_text(text, use_online=use_online)


def translate_identifier(name: str, use_online: bool = False) -> dict:
    """
    Return {"it": name, "en": display}.

    Convenience wrapper around the module singleton.
    """
    return get_translator().translate_identifier(name, use_online=use_online)
