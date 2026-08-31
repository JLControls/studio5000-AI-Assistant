"""
build_seed_glossary.py — Reproducible seed-glossary builder.

Merges two sources into ``i18n/it_en_glossary.json``:

1. ``F:/Copia/Dev/Translation/scripts/5b_terminology.json``
   Schema: ``{ "<italian>": {"confidence": float, "translation": "<english>"} }``
   (181 entries, human-curated phrases)

2. ``ITALIAN_AUTOMATION_DICT`` defined below
   (single-word automation terms, assigned confidence 0.99)
   Previously this dict lived in translator.py; it was relocated here in
   Task 2 when translator.py switched to loading the glossary from
   i18n/it_en_glossary.json instead of the embedded dict.

Merge rules
-----------
* Keys are normalised: ``key.lower().strip()``.
* On key conflict keep the higher confidence value; tie → keep 5b_terminology entry.
* All non-conflicting keys are kept.

Output schema: ``{ "<italian>": {"en": "<english>", "confidence": float} }``
Output file:   ``i18n/it_en_glossary.json``  (UTF-8, sorted keys, indent 2)

Usage
-----
    python i18n/build_seed_glossary.py          # (re)generate the glossary
"""

from __future__ import annotations

import json
import os
import sys

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_DOCUMENTER_DIR = os.path.dirname(_SCRIPT_DIR)

# The ONLY place in the pipeline that references the external curated file.
_TERMINOLOGY_PATH = "F:/Copia/Dev/Translation/scripts/5b_terminology.json"

_OUTPUT_PATH = os.path.join(_SCRIPT_DIR, "it_en_glossary.json")

# ---------------------------------------------------------------------------
# Seed dictionary (formerly ITALIAN_AUTOMATION_DICT in translator.py)
# ---------------------------------------------------------------------------

ITALIAN_AUTOMATION_DICT: dict[str, str] = {
    # Machine parts
    "motore": "motor",
    "pompa": "pump",
    "valvola": "valve",
    "cilindro": "cylinder",
    "nastro": "conveyor",
    "trasportatore": "conveyor",
    "rullo": "roller",
    "encoder": "encoder",
    "sensore": "sensor",
    "finecorsa": "limit switch",
    "fotocellula": "photocell",
    "prossimità": "proximity",
    "pressione": "pressure",
    "temperatura": "temperature",
    "livello": "level",
    "flusso": "flow",
    "velocità": "speed",
    "posizione": "position",

    # States
    "acceso": "on",
    "spento": "off",
    "avviato": "started",
    "fermato": "stopped",
    "in marcia": "running",
    "fermo": "stopped",
    "allarme": "alarm",
    "errore": "error",
    "guasto": "fault",
    "pronto": "ready",
    "occupato": "busy",
    "libero": "free",
    "aperto": "open",
    "chiuso": "closed",
    "alto": "high",
    "basso": "low",

    # Actions
    "avvio": "start",
    "avvia": "start",
    "arresto": "stop",
    "ferma": "stop",
    "reset": "reset",
    "azzeramento": "reset",
    "abilitazione": "enable",
    "abilita": "enable",
    "disabilita": "disable",
    "seleziona": "select",
    "conferma": "confirm",
    "annulla": "cancel",

    # Control
    "automatico": "automatic",
    "auto": "auto",
    "manuale": "manual",
    "locale": "local",
    "remoto": "remote",
    "ciclo": "cycle",
    "sequenza": "sequence",
    "passo": "step",
    "fase": "phase",
    "ritardo": "delay",
    "tempo": "time",
    "contatore": "counter",
    "timer": "timer",

    # Equipment
    "macchina": "machine",
    "linea": "line",
    "stazione": "station",
    "zona": "zone",
    "area": "area",
    "ingresso": "input",
    "uscita": "output",
    "pannello": "panel",
    "quadro": "cabinet",
    "plc": "plc",

    # Specific to salami/meat processing
    "salami": "salami",
    "salame": "salami",
    "isola": "island",
    "scarico": "unload",
    "carico": "load",
    "taglio": "cut",
    "affettatura": "slicing",
    "confezionamento": "packaging",
    "pesatura": "weighing",
    "dosaggio": "dosing",

    # Program structure
    "principale": "main",
    "gestione": "management",
    "controllo": "control",
    "diagnostica": "diagnostic",
    "comunicazione": "communication",
    "inizializzazione": "initialization",
    "sicurezza": "safety",
}


# ---------------------------------------------------------------------------
# Core merge logic
# ---------------------------------------------------------------------------

def _normalise(key: str) -> str:
    return key.lower().strip()


def build_glossary(
    terminology_path: str = _TERMINOLOGY_PATH,
    output_path: str = _OUTPUT_PATH,
) -> dict:
    """Build and write the merged glossary.  Returns the merged dict."""

    glossary: dict[str, dict] = {}

    # --- Source 1: 5b_terminology.json ---
    with open(terminology_path, encoding="utf-8") as fh:
        raw = json.load(fh)

    for italian, data in raw.items():
        key = _normalise(italian)
        conf = float(data["confidence"])
        trans = data["translation"]
        if not trans:
            continue
        glossary[key] = {"en": trans, "confidence": conf}

    # --- Source 2: ITALIAN_AUTOMATION_DICT (confidence 0.99) ---
    for italian, english in ITALIAN_AUTOMATION_DICT.items():
        key = _normalise(italian)
        if not english:
            continue
        if key in glossary:
            existing_conf = glossary[key]["confidence"]
            if 0.99 > existing_conf:
                # Dict entry has higher confidence → replace
                glossary[key] = {"en": english, "confidence": 0.99}
            # tie or existing is higher → keep existing (5b_terminology wins on tie)
        else:
            glossary[key] = {"en": english, "confidence": 0.99}

    # --- Sort and write ---
    sorted_glossary = dict(sorted(glossary.items()))

    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(sorted_glossary, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    return sorted_glossary


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    result = build_glossary()
    print(f"Wrote {len(result)} entries to {_OUTPUT_PATH}")
