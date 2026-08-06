#!/usr/bin/env python3
"""Signal-type -> Tag Historian recommendation matrix.

The shared "brain" behind both ``suggest_historian_config`` (tool #4) and the
historian defaults applied by ``generate_ignition_tags`` (tool #2). Encodes the
industrial SCADA best-practice matrix from the Ignition tag-properties reference.

Correction #1 constraint: a **value** deadband is only ever returned as *advisory*
output (``recommended_value_deadband``). It is never written into a generated tag
-- the builder writes only ``historyEnabled``/``historyProvider``/``historyMaxAge``/
``historyTimeDeadband``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from tag_analyzer.tag_chunk import detect_function_from_description


@dataclass(frozen=True)
class HistorianRule:
    signal_type: str
    history_enabled: bool
    time_deadband_sec: int
    # Advisory only -- percent of engineering span, never written to a tag.
    value_deadband_pct: Optional[float]
    eng_unit_hint: str
    rationale: str


# Canonical signal types and their historian recommendations.
HISTORIAN_MATRIX: Dict[str, HistorianRule] = {
    "level": HistorianRule("level", True, 15, 0.5, "in", "Continuous tank level PV."),
    "pressure": HistorianRule("pressure", True, 10, 0.5, "PSI", "Continuous header pressure PV."),
    "temperature": HistorianRule("temperature", True, 15, 0.2, "degF", "Continuous process temperature PV."),
    "flow": HistorianRule("flow", True, 10, 1.0, "GPM", "Continuous flow-rate PV."),
    "speed": HistorianRule("speed", True, 15, 0.5, "Hz", "VFD speed feedback / command."),
    "energy": HistorianRule("energy", True, 30, 10.0, "BTU", "Utility energy / totalizer accumulation."),
    "alarm": HistorianRule("alarm", True, 0, None, "", "Discrete alarm/status -- log on change."),
    "status": HistorianRule("status", True, 0, None, "", "Discrete status/contact -- log on change."),
    "static": HistorianRule("static", False, 0, None, "", "Static spec/geometry/setpoint -- no history."),
}

# Keyword -> canonical signal type. Checked against tag name + description. Order
# matters: more specific / higher-priority signals are listed first.
_KEYWORD_SIGNALS = [
    ("static", ("setpoint", "_set_", "_sc", "scale range", "geometry", "diameter",
                "offset", "constant", "gpi", "_gpm_sc", "spec")),
    ("alarm", ("alarm", "alm", "fault", "flt", "_fail", "estop", "e-stop", "trip")),
    ("energy", ("btu", "totalizer", "totalize", "kwh", "energy", "hour counter", "hrctr")),
    ("level", ("level", "height", "_l_", "tank")),
    ("pressure", ("pressure", "pres", "psi", "_hdr_pres")),
    ("temperature", ("temperature", "temp", "degf", "thermo")),
    ("flow", ("flow", "gpm", "lpm")),
    ("speed", ("speed", "_hz", "rpm", "vfd", "cmd_hz", "running")),
    ("status", ("aux", "disc", "status", "running", "auto", "switch", "contact", "_din_")),
]

# Function strings from detect_function_from_description -> canonical signal type.
_FUNCTION_SIGNALS = {
    "level sensor": "level",
    "pressure sensor": "pressure",
    "temperature sensor": "temperature",
    "flow sensor": "flow",
    "speed feedback": "speed",
    "vfd control": "speed",
    "emergency stop": "alarm",
    "safety input": "alarm",
    "photoeye": "status",
    "proximity sensor": "status",
    "disconnect": "status",
}


def classify_signal_type(signal_type: Optional[str] = None, tag_name: str = "",
                         description: str = "") -> str:
    """Resolve a canonical signal type from an explicit hint or name/description."""
    if signal_type:
        key = signal_type.strip().lower()
        if key in HISTORIAN_MATRIX:
            return key
        # Allow common synonyms to fold into canonical keys.
        for canon in HISTORIAN_MATRIX:
            if canon in key:
                return canon

    text = f"{tag_name} {description}".lower()
    for canon, keywords in _KEYWORD_SIGNALS:
        if any(k in text for k in keywords):
            return canon

    func = detect_function_from_description(description, tag_name).lower()
    if func in _FUNCTION_SIGNALS:
        return _FUNCTION_SIGNALS[func]

    # Unknown continuous-looking signals default to status (log on change); a bare
    # name with no signal cues stays "status" rather than silently disabling.
    return "status"


def suggest_historian_config(signal_type: Optional[str] = None,
                             tag_name: Optional[str] = None,
                             description: Optional[str] = None,
                             eng_low: Optional[float] = None,
                             eng_high: Optional[float] = None) -> Dict[str, object]:
    """Recommend historian settings for a signal (tool #4).

    ``recommended_value_deadband`` is advisory only and is never written into a
    generated tag.
    """
    resolved = classify_signal_type(signal_type, tag_name or "", description or "")
    rule = HISTORIAN_MATRIX[resolved]

    value_deadband: Optional[float] = None
    deadband_note = "Value deadband is advisory only and is never written to a tag."
    if rule.value_deadband_pct is not None:
        if eng_low is not None and eng_high is not None:
            span = abs(float(eng_high) - float(eng_low))
            value_deadband = round(span * rule.value_deadband_pct / 100.0, 4)
            deadband_note = (f"Advisory: ~{rule.value_deadband_pct}% of the "
                             f"{span:g} span. Not written to the tag.")
        else:
            value_deadband = rule.value_deadband_pct
            deadband_note = (f"Advisory: {rule.value_deadband_pct}% of engineering "
                             "span (supply eng_low/eng_high for an absolute value). "
                             "Not written to the tag.")

    return {
        "success": True,
        "signal_type": resolved,
        "history_enabled": rule.history_enabled,
        "history_time_deadband": rule.time_deadband_sec,
        "history_time_deadband_units": "SEC",
        "eng_unit_hint": rule.eng_unit_hint,
        "recommended_value_deadband": value_deadband,
        "value_deadband_note": deadband_note,
        "rationale": rule.rationale,
    }


def history_defaults_for(tag_name: str = "", description: str = "",
                         signal_type: Optional[str] = None) -> Dict[str, object]:
    """Historian defaults for the generator (tool #2): enabled flag + time deadband."""
    resolved = classify_signal_type(signal_type, tag_name, description)
    rule = HISTORIAN_MATRIX[resolved]
    return {
        "signal_type": resolved,
        "history": rule.history_enabled,
        "time_deadband": rule.time_deadband_sec,
    }
