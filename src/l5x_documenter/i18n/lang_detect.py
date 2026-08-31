"""
lang_detect.py — Shared Italian-detection heuristic.

Dependency-free (stdlib only).  Imported by harvest_glossary.py (this task)
and by translator.py (Task 2).

Public API
----------
looks_italian(text: str) -> bool
    Returns True if *text* appears to be Italian.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Compiled patterns
# ---------------------------------------------------------------------------

# Strong single-character signals: Italian-specific accented vowels.
# (ü / ñ / ç etc. belong to other languages and are NOT included.)
_ACCENTED = re.compile(r'[àèéìòùÀÈÉÌÒÙ]')

# Italian word endings that are rare or absent in English
_ZIONE = re.compile(r'\b\w{2,}zione\b', re.IGNORECASE)   # comunicazione, gestione…
_AGGIO = re.compile(r'\b\w{2,}aggio\b', re.IGNORECASE)   # cablaggio, fissaggio…
_ITA   = re.compile(r'\b\w{2,}ità\b',   re.IGNORECASE)   # disponibilità, velocità…

# Italian-only articles (unambiguous — not shared with English or Spanish)
_ARTICLES = re.compile(
    r'\b(il|lo|gli|delle|degli|della|dello|dell|dal|dalla|negli|nelle|negli)\b',
    re.IGNORECASE,
)
# Italian-specific prepositions / contractions (avoid 'in'/'per' — they appear in English)
_PREPS = re.compile(
    r'\b(di|da|su|del|nei|nel|tra|fra|con)\b',
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Known Italian automation / PLC words (domain-specific lexicon).
# Drawn from ITALIAN_AUTOMATION_DICT + 5b_terminology + common Italian terms.
# Keep this list as the canonical offline signal source — no JSON dependency.
# ---------------------------------------------------------------------------
_ITALIAN_WORDS: frozenset[str] = frozenset({
    # Machine parts
    "motore", "motori", "pompa", "pompe", "valvola", "valvole",
    "cilindro", "cilindri", "nastro", "trasportatore", "rullo",
    "encoder", "sensore", "sensori", "finecorsa", "fotocellula",
    "pressione", "temperatura", "livello", "flusso", "velocita",
    "posizione", "prossimita",
    # States
    "acceso", "spento", "avviato", "fermato", "allarme", "errore",
    "guasto", "pronto", "occupato", "libero", "aperto", "chiuso",
    "alto", "basso", "marcia", "fermo",
    # Actions
    "avvio", "avvia", "arresto", "ferma", "azzeramento", "abilitazione",
    "abilita", "disabilita", "seleziona", "conferma", "annulla",
    # Control
    "automatico", "automatica", "manuale", "locale", "remoto",
    "ciclo", "sequenza", "passo", "fase", "ritardo", "tempo", "contatore",
    # Equipment / layout
    "macchina", "linea", "stazione", "zona", "ingresso", "uscita",
    "pannello", "quadro", "principale", "gestione", "controllo",
    "diagnostica", "comunicazione", "inizializzazione", "sicurezza",
    # Food-processing domain
    "salami", "salame", "isola", "scarico", "carico", "taglio",
    "affettatura", "confezionamento", "pesatura", "dosaggio",
    # From 5b_terminology
    "barriera", "accesso", "attesa", "carrello", "emergenza",
    "consenso", "consensi", "conferme", "azionamento", "disponibile",
    "bloccaggi", "bastoni", "agv", "abilitazione", "avanzamento",
    "chiusura", "apertura", "produzione",
    # Common Italian words that appear in technical contexts
    "stato", "modo", "segnale", "segnali", "comando", "comandi",
    "ricetta", "parametro", "parametri", "asse", "assi",
    "pezzo", "pezzi", "prodotto", "prodotti", "lotto",
    "impianto", "sistema", "operatore", "operazione", "operazioni",
    "movimento", "posizionamento", "abilitato", "disabilitato",
    "attivo", "inattivo", "funzione", "programma", "routine",
    "lubrificazione", "raffreddamento", "riscaldamento",
    "elettrico", "elettrica", "pneumatico", "pneumatica",
    "idraulico", "idraulica", "meccanico", "meccanica",
    "velocita", "accelerazione", "decelerazione", "coppia",
    "pressione", "temperatura", "umidita", "portata",
    "conteggio", "registro", "indirizzo", "valore", "limite",
    "allarmi", "errori", "guasti", "anomalia", "anomalie",
    "sostituzione", "manutenzione", "calibrazione",
    "consenso", "bloccaggio", "sblocco", "ripristino",
})


def looks_italian(text: str) -> bool:
    """Return True if *text* appears to be Italian.

    Signals checked (in order of strength):
    1. Italian-specific accented characters (à è é ì ò ù).
    2. Word endings typical of Italian: -zione, -aggio, -ità.
    3. Presence of known Italian automation/PLC vocabulary.
    4. Two or more unambiguous Italian articles / prepositions.

    Must reliably return False for plainly-English strings such as
    ``"Logic"``, ``"Continuous"``, ``"The month (1 - 12)"``.
    """
    if not text or not text.strip():
        return False

    # --- Strong single signals ---
    if _ACCENTED.search(text):
        return True
    if _ZIONE.search(text):
        return True
    if _AGGIO.search(text):
        return True
    if _ITA.search(text):
        return True

    # --- Lexicon match (medium strength) ---
    words = {w.lower() for w in re.findall(r'[A-Za-zàèéìòùÀÈÉÌÒÙ]+', text)}
    if words & _ITALIAN_WORDS:
        return True

    # --- Structural signals: require two distinct hits to avoid English false positives ---
    score = 0
    if _ARTICLES.search(text):
        score += 1
    if _PREPS.search(text):
        score += 1
    return score >= 2
