"""
harvest_glossary.py — Maintenance CLI for harvesting new Italian glossary candidates.

Usage
-----
    python i18n/harvest_glossary.py <folder> [<folder> ...] [--online]

Recursively scans *.l5x files under each <folder> and extracts Italian-looking
tokens not already present in ``it_en_glossary.json``.  Writes new candidates to
``i18n/glossary_candidates.json``.

NEVER writes to ``it_en_glossary.json`` — that file is human-curated.

Output schema
-------------
    {
      "<italian_token>": {
        "en":         "<english or empty string>",
        "frequency":  <int>,     # total occurrences across all files
        "confidence": <float>,   # 0.0 (no online translation available)
        "files":      <int>      # number of distinct L5X files the token appeared in
      },
      ...
    }
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup — allow running as `python i18n/harvest_glossary.py` from the
# documenter directory, or as a module from anywhere.
# ---------------------------------------------------------------------------
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_DOCUMENTER_DIR = os.path.dirname(_SCRIPT_DIR)

if _DOCUMENTER_DIR not in sys.path:
    sys.path.insert(0, _DOCUMENTER_DIR)

from i18n.lang_detect import looks_italian  # noqa: E402

_GLOSSARY_PATH = os.path.join(_SCRIPT_DIR, "it_en_glossary.json")
_OUTPUT_PATH = os.path.join(_SCRIPT_DIR, "glossary_candidates.json")

# Minimum token length to consider (filters noise like "il", "di", "da")
_MIN_LEN = 4

# Element types whose Name attribute should be split into word-parts
_NAMED_ELEMENTS = {"Program", "Routine", "AddOnInstructionDefinition", "Tag"}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_element_text(elem: ET.Element) -> str:
    """Return text content, handling ``<LocalizedComment>`` / ``<LocalizedDescription>`` wrappers."""
    # Direct CDATA text
    if elem.text and elem.text.strip():
        return elem.text.strip()
    # Localised wrapper (e.g. <LocalizedComment Lang="en-US"><![CDATA[…]]></LocalizedComment>)
    for child in elem:
        tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        if tag.startswith("Localized"):
            if child.text and child.text.strip():
                return child.text.strip()
    return ""


def _split_identifier(name: str) -> list[str]:
    """Split a CamelCase / PascalCase / underscore identifier into word parts."""
    # Step 1 — split on underscores
    parts: list[str] = []
    for segment in name.split("_"):
        if not segment:
            continue
        # Step 2 — insert boundary between a lowercase letter and the following uppercase
        spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", segment)
        # Step 3 — insert boundary between a run of uppercase and a titlecase continuation
        spaced = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", spaced)
        parts.extend(w for w in spaced.split() if w)
    return parts


def _tokenise_text(text: str) -> list[str]:
    """Extract alphabetic tokens (including Italian accented chars) from free text."""
    return re.findall(r"[A-Za-zàèéìòùÀÈÉÌÒÙ]+", text)


def extract_tokens_from_l5x(path: str) -> list[str]:
    """
    Extract candidate token strings from a single L5X file.

    Returns a flat list of normalised (lower-cased) tokens.
    """
    try:
        tree = ET.parse(path)
    except ET.ParseError:
        return []

    root = tree.getroot()
    tokens: list[str] = []

    # --- Free-text sources: <Description> and <Comment> CDATA ---
    for tag_name in ("Description", "Comment"):
        for elem in root.iter(tag_name):
            text = _get_element_text(elem)
            if text:
                tokens.extend(w.lower() for w in _tokenise_text(text))

    # --- Identifier sources: Name="..." attributes ---
    for elem in root.iter():
        local_tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if local_tag in _NAMED_ELEMENTS:
            name = elem.get("Name", "")
            if name:
                for word in _split_identifier(name):
                    tokens.append(word.lower())

    return tokens


def find_l5x_files(folders: list[str]) -> list[Path]:
    """Recursively find all *.l5x files (case-insensitive) under the given folders."""
    found: list[Path] = []
    for folder in folders:
        p = Path(folder)
        if not p.is_dir():
            continue
        found.extend(p.rglob("*.l5x"))
        found.extend(p.rglob("*.L5X"))
    # Deduplicate (case-sensitive path, handles Windows)
    seen: set[str] = set()
    unique: list[Path] = []
    for f in found:
        key = str(f).lower()
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return unique


def load_glossary(path: str = _GLOSSARY_PATH) -> set[str]:
    """Return the set of normalised (lower-cased) keys from it_en_glossary.json."""
    if not os.path.exists(path):
        return set()
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return set(data.keys())


def _try_translate_online(tokens: list[str]) -> dict[str, str]:
    """Attempt online translation via deep_translator.  Returns {} on any failure."""
    try:
        from deep_translator import GoogleTranslator
        translator = GoogleTranslator(source="it", target="en")
        result: dict[str, str] = {}
        for token in tokens:
            try:
                result[token] = translator.translate(token) or ""
            except Exception:
                result[token] = ""
        return result
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Main harvest logic
# ---------------------------------------------------------------------------

def harvest(
    folders: list[str],
    online: bool = False,
    glossary_path: str = _GLOSSARY_PATH,
    output_path: str = _OUTPUT_PATH,
) -> tuple[dict, int]:
    """
    Run the harvest over *folders*.  Returns a tuple of (candidates_dict, num_l5x_files).

    Never touches *glossary_path* (read-only).
    Writes results to *output_path*.
    """
    l5x_files = find_l5x_files(folders)

    glossary_keys = load_glossary(glossary_path)

    # token → total frequency
    freq: Counter[str] = Counter()
    # token → set of file paths it was seen in
    file_sets: defaultdict[str, set[str]] = defaultdict(set)

    for filepath in l5x_files:
        tokens = extract_tokens_from_l5x(str(filepath))
        seen_in_file: set[str] = set()
        for tok in tokens:
            if len(tok) < _MIN_LEN:
                continue
            freq[tok] += 1
            seen_in_file.add(tok)
        for tok in seen_in_file:
            file_sets[tok].add(str(filepath))

    # Filter: drop glossary entries and non-Italian tokens
    candidates: dict[str, dict] = {}
    for token, count in freq.items():
        if token in glossary_keys:
            continue
        if not looks_italian(token):
            continue
        candidates[token] = {
            "en": "",
            "frequency": count,
            "confidence": 0.0,
            "files": len(file_sets[token]),
        }

    # Optional online translation
    if online and candidates:
        translations = _try_translate_online(list(candidates.keys()))
        for token, en in translations.items():
            if token in candidates and en:
                candidates[token]["en"] = en
                candidates[token]["confidence"] = 0.5  # machine-translated, unverified

    # Sort by frequency descending for readability
    sorted_candidates = dict(
        sorted(candidates.items(), key=lambda kv: -kv[1]["frequency"])
    )

    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(sorted_candidates, fh, ensure_ascii=False, indent=2)

    return sorted_candidates, len(l5x_files)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Harvest Italian glossary candidates from L5X files."
    )
    parser.add_argument(
        "folders",
        nargs="+",
        metavar="FOLDER",
        help="One or more root folders to scan recursively for *.l5x files.",
    )
    parser.add_argument(
        "--online",
        action="store_true",
        help="Translate candidates via GoogleTranslator (requires deep-translator).",
    )
    args = parser.parse_args()

    result, n_files = harvest(args.folders, online=args.online)

    print(
        f"Scanned {n_files} L5X file(s). "
        f"Wrote {len(result)} candidate(s) to {_OUTPUT_PATH}"
    )


if __name__ == "__main__":
    main()
