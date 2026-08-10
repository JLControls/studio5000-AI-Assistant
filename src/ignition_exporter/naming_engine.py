"""Deterministic, side-effect-free PLC tag presentation rules for Ignition."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
import json
from pathlib import Path
import re
from types import MappingProxyType


@dataclass(frozen=True)
class NamingProfile:
    display_root: str
    tokens: Mapping[str, str]
    phrases: tuple[tuple[str, str], ...]
    member_suffixes: Mapping[str, str | None]
    aliases: frozenset[str]
    test_markers: frozenset[str]
    explicit: Mapping[str, Mapping[str, str | None]]


@dataclass(frozen=True)
class Presentation:
    plc_tag: str
    name: str
    folder: str
    documentation: str
    tooltip: str
    is_test: bool
    unknown_tokens: tuple[str, ...]


_PHRASES = (
    ("Cmd_Hz", "Command Speed"), ("Disc_On", "Disconnect On"),
    ("Disc_Off", "Disconnect Off"), ("Suc_Lo", "Suction Low"),
    ("Suc_Hi", "Suction High"), ("Temp_Hi", "Temperature High"),
    ("Temp_Lo", "Temperature Low"), ("Temp_Diff", "Temperature Differential"),
    ("Temp_Off", "Temperature Offset"), ("Pres_Lo", "Pressure Low"),
    ("Pres_Hi", "Pressure High"), ("Hdr_Pres", "Header Pressure"),
    ("Suc_Pres", "Suction Pressure"), ("MU_Pres", "Make-Up Pressure"),
    ("Flow_Cur_Ttl", "Flow Total"), ("Flow_GPM", "Flow"),
    ("Lo_L", "Low Level"), ("Hi_L", "High Level"),
    ("Auto_Rest", "Auto Mode Rest"), ("Lim_Close", "Limit Close"),
    ("Lim_Open", "Limit Open"), ("Aux_Closure", "Aux Contact Closure"),
    ("OverPump", "Over-Pump"), ("HrCtr", "Hour Counter"),
    ("Run_Stat", "Run Status"),
)

_TOKENS = {
    "HWT1": "Hot Water Tank", "dHWT1": "Hot Water Tank", "HW1": "Hot Water",
    "HR1": "HR1", "VC1": "VC1", "CW": "Cold Water", "HP": "High Pressure",
    "LP": "Low Pressure", "Lp": "Low Pressure", "P1": "Pump 1", "P2": "Pump 2",
    "P": "Pump", "HtC1": "Heat Circulator", "HtC": "Heat Circulator",
    "Disch": "Discharge", "Recirc": "Recirculation", "Rec": "Recirc", "MU": "Make-Up",
    "FGR": "Flue Gas Recirc", "Disc": "Disconnect", "Htr": "Heater",
    "Blwr1": "Blower 1", "Blwr": "Blower", "Gas": "Gas", "Air": "Air",
    "Brn": "Burner", "Flm": "Flame", "Stk": "Stack", "StK": "Stack",
    "Inlet": "Inlet", "Outlet": "Outlet", "Mod": "Modulating", "V1": "Valve 1",
    "V": "Valve", "AC1": "Air Compressor 1", "AC": "Air Compressor", "SS": "Soft Start",
    "Lctrl1": "Level Control 1", "Nozzle": "Nozzle", "WWall": "Water Wall",
    "Reg": "Regulator", "SG": "Safety Gas", "Main": "Main", "Fresh": "Fresh",
    "FrW": "Firewall", "24vdc": "24VDC", "24vdc1": "24VDC", "Running": "Running",
    "Aux": "Aux Contact", "Auto": "Auto Mode", "Man": "Manual", "Cmd": "Command",
    "Set": "Setpoint", "SP": "Setpoint", "Run": "Run", "Jog": "Jog", "Res": "Reset",
    "Slnc": "Silence", "En": "Enable", "EN": "Enable", "Enable": "Enable",
    "Dis": "Disable", "On": "On", "Off": "Off", "Hz": "Speed", "HZ": "Speed",
    "hZ": "Speed", "Pres": "Pressure", "Temp": "Temperature", "Flow": "Flow",
    "Lvl": "Level", "Hdr": "Header", "Suc": "Suction", "Lo": "Low", "Hi": "High",
    "Min": "Min", "Max": "Max", "Lim": "Limit", "Diff": "Differential",
    "Offset": "Offset", "Rep": "Report", "Warn": "Warning", "Del": "Delay",
    "Estop": "E-Stop", "VFD": "VFD", "Vfd": "VFD", "Flt": "Fault", "Fault": "Fault",
    "Fail": "Fail", "Horn": "Horn", "Lamp": "Lamp", "Emg": "Emergency", "Avg": "Average",
    "Full": "Full", "Sleep": "Sleep", "Wake": "Wake", "Lead": "Lead", "Lag": "Lag",
    "Interlock": "Interlock", "Intlk": "Interlock", "HOA": "HOA", "Cyc": "Cycle",
    "FB": "Feedback", "Trans": "Transition", "GPM": "GPM", "PSI": "PSI", "psi": "PSI",
    "Deg": "Deg", "Gal": "Gal", "L": "Level", "Ttl": "Total", "Tot": "Total",
    "TOT": "Flow Totalizer", "Total": "Total", "Cur": "Current", "Hours": "Hours",
    "Hr": "Hour", "Height": "Height", "Specific": "Specific", "Gravity": "Gravity",
    "Model": "Model", "Data1": "Read", "WData1": "Write", "Comms": "Comms",
    "Comms1": "Comms", "Comm": "Comms", "IP": "IP", "FireRt": "Fire Rate",
    "AvgRt": "Average Rate", "EmgRt": "Emergency Rate", "Calc": "Calculated",
    "Round": "Round", "Rollover": "Rollover", "Per": "Per", "Only": "Only", "Not": "Not",
    "Latch": "Latch", "Ext": "External", "Rest": "Rest", "Fld": "Field", "Sw": "Switch",
    "Sc": "Scaled", "mBTUhr": "MBTU/hr", "mBTU": "MBTU", "Proc": "Process",
    "Ret": "Return", "Panel": "Panel", "PLC": "PLC", "HMI": "HMI", "Test": "Test",
    "AO1": "Analog Output", "hZ1": "Speed", "hZ_Comms1": "Speed", "Speed": "Speed",
    "Open": "Open", "Closure": "Closure", "LckOut": "Lockout", "Dec": "Decrease",
    "Inc": "Increase", "Pumped": "Pumped", "Initial": "Initial", "StandAlone": "Standalone",
    "DualBurner": "Dual Burner", "LeadLag": "Lead-Lag", "R": "Rate", "Job": "Job",
    "Project": "Project", "ACFM": "ACFM", "Lim1": "Limit 1", "Lim2": "Limit 2",
    "Ambient": "Ambient", "Pilot": "Pilot", "Comb": "Combustion", "Bypass": "Bypass",
    "Close": "Close", "Mode": "Mode", "Psi": "PSI", "Trend": "Trend", "LoLo": "Low Low",
    "FGR1": "Flue Gas Recirc", "Offscale": "Off-Scale", "Fls": "Fault",
}

_MEMBER_SUFFIXES = {
    "Gal": "Level Gal", "L": "Level", "RUNNING": "Running", "Flow_GPM": "Flow",
    "Flow_Cur_Ttl": "Flow Total", "Run_Stat": "Run Status", "Hours": "Hours",
    "Min": "Minutes", "Input_Gas_psi": "Pressure", "mBTUhr": "MBTU/hr",
    "Total_mBTU": "Total MBTU", "ACC": "Accumulator", "DN": None, "PRE": None,
    "ScaledVal": None,
}

_ALIASES = frozenset({"AliasDIn", "AliasDOut", "AliasAIn", "AliasAOut", "AliasDin", "AliasAin"})
_TEST_MARKERS = frozenset({"Test", "Tes4", "Test2", "Test3", "TESTbtu", "testhr"})
_CASE_FIXES = {"COm": "Com", "Comm": "Com", "Lp": "LP", "lp": "LP", "hZ": "Hz", "HZ": "Hz", "hz": "Hz", "AliasDin": "AliasDIn", "AliasAin": "AliasAIn", "lamp": "Lamp", "fail": "Fail", "d": "", "D": ""}
_ALIAS_QUALIFIERS = {"AliasAIn": "Analog Input", "AliasAOut": "Analog Output", "AliasDIn": "Digital Input", "AliasDOut": "Digital Output", "AliasDin": "Digital Input", "AliasAin": "Analog Input"}


def _freeze_profile(display_root: str, tokens: Mapping[str, str], phrases: tuple[tuple[str, str], ...], member_suffixes: Mapping[str, str | None], aliases: frozenset[str], test_markers: frozenset[str], explicit: Mapping[str, Mapping[str, str | None]]) -> NamingProfile:
    return NamingProfile(display_root, MappingProxyType(dict(tokens)), tuple(phrases), MappingProxyType(dict(member_suffixes)), frozenset(aliases), frozenset(test_markers), MappingProxyType({key: MappingProxyType(dict(value)) for key, value in explicit.items()}))


_BUILT_IN_PROFILE = _freeze_profile("Boiler", _TOKENS, _PHRASES, _MEMBER_SUFFIXES, _ALIASES, _TEST_MARKERS, {})


def _require_string_mapping(value: object, field: str, allow_none: bool = False) -> dict[str, str | None]:
    if not isinstance(value, dict) or any(not isinstance(key, str) or (item is not None and not isinstance(item, str)) or (item is None and not allow_none) for key, item in value.items()):
        raise ValueError(f"{field} must be an object with string values")
    return dict(value)


def load_naming_profile(path: str | None = None) -> tuple[NamingProfile, str]:
    """Load a validated profile overlay without mutating built-in vocabulary."""
    if path is None:
        return _BUILT_IN_PROFILE, "built-in"
    profile_path = Path(path).expanduser().resolve()
    if not profile_path.is_file():
        raise ValueError(f"profile path does not exist: {profile_path}")
    try:
        raw = json.loads(profile_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"profile JSON is invalid: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError("profile must be a JSON object")
    unknown_fields = set(raw) - {"display_root", "tokens", "phrases", "member_suffixes", "aliases", "test_markers", "explicit"}
    if unknown_fields:
        raise ValueError(f"profile contains unknown field: {sorted(unknown_fields)[0]}")
    display_root = raw.get("display_root", _BUILT_IN_PROFILE.display_root)
    if not isinstance(display_root, str):
        raise ValueError("display_root must be a string")
    tokens = dict(_BUILT_IN_PROFILE.tokens)
    if "tokens" in raw:
        tokens.update(_require_string_mapping(raw["tokens"], "tokens"))
    members = dict(_BUILT_IN_PROFILE.member_suffixes)
    if "member_suffixes" in raw:
        members.update(_require_string_mapping(raw["member_suffixes"], "member_suffixes", allow_none=True))
    phrases = list(_BUILT_IN_PROFILE.phrases)
    if "phrases" in raw:
        replacements = _require_string_mapping(raw["phrases"], "phrases")
        phrases = [(pattern, replacement) for pattern, replacement in phrases if pattern not in replacements]
        phrases.extend((pattern, replacement) for pattern, replacement in replacements.items() if replacement is not None)
    aliases = _merge_string_set(raw, "aliases", _BUILT_IN_PROFILE.aliases)
    test_markers = _merge_string_set(raw, "test_markers", _BUILT_IN_PROFILE.test_markers)
    explicit: dict[str, Mapping[str, str | None]] = {}
    if "explicit" in raw:
        if not isinstance(raw["explicit"], dict):
            raise ValueError("explicit must be an object")
        for tag, override in raw["explicit"].items():
            if not isinstance(tag, str) or not isinstance(override, dict) or set(override) - {"name", "folder"}:
                raise ValueError("explicit must map tags to name/folder objects")
            if any(value is not None and not isinstance(value, str) for value in override.values()):
                raise ValueError("explicit must map tags to string or null values")
            explicit[tag] = dict(override)
    return _freeze_profile(display_root, tokens, tuple(phrases), members, aliases, test_markers, explicit), str(profile_path)


def _merge_string_set(raw: Mapping[str, object], field: str, default: frozenset[str]) -> frozenset[str]:
    if field not in raw:
        return default
    value = raw[field]
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{field} must be a list of strings")
    return default | frozenset(value)


def _split_member(plc_tag: str) -> tuple[str, str | None]:
    normalized = re.sub(r"^Program:[^.]+\.", "", plc_tag)
    return tuple(normalized.split(".", 1)) if "." in normalized else (normalized, None)  # type: ignore[return-value]


def _strip_prefixes(name: str, markers: frozenset[str]) -> tuple[str, bool]:
    is_test = bool(re.search(r"(?i)(test|tes\d|testbtu)", name))
    while True:
        matched = next((prefix for prefix in ("d_", "D_", "Test_", "TESTbtu_", "testhr_") if name.startswith(prefix)), None)
        if matched is None:
            return name, is_test
        is_test = is_test or matched.rstrip("_") in markers or matched in {"d_", "D_"}
        name = name[len(matched):]


def _normal_token(token: str) -> str:
    return _CASE_FIXES.get(token, token)


def _expand_words(tokens: list[str], profile: NamingProfile, unknown: list[str]) -> list[str]:
    joined = "_".join(tokens)
    phrase_values = set()
    for pattern, replacement in profile.phrases:
        if "_" not in pattern:
            continue
        joined = joined.replace(pattern, replacement)
        phrase_values.add(replacement)
    words: list[str] = []
    for token in joined.split("_"):
        if not token or re.fullmatch(r"SCP\d+|\d+", token):
            continue
        if token.startswith("Auto Mode"):
            words.append(token)
        elif token in profile.tokens:
            words.append(profile.tokens[token])
        elif token in phrase_values:
            words.append(token)
        else:
            words.append(token)
            unknown.append(token)
    return [word for word in words if word not in {"Comms", "Running"}]


def _member_words(member: str, profile: NamingProfile, unknown: list[str]) -> list[str]:
    if member in profile.member_suffixes:
        value = profile.member_suffixes[member]
        return [] if value is None else [value]
    return _expand_words([_normal_token(token) for token in re.split(r"[_.]", member)], profile, unknown)


def _build_name(base: str, member: str | None, profile: NamingProfile) -> tuple[str, bool, tuple[str, ...]]:
    clean, is_test = _strip_prefixes(base, profile.test_markers)
    totalizer = re.fullmatch(r"TOT_(\d+)", clean)
    if totalizer:
        member_name = {"Flow": "Flow", "Tot": "Total", "ACC": "Accumulator", "DN": "Done"}.get(member or "", member or "")
        return f"Flow Totalizer {int(totalizer.group(1))} {member_name}".strip(), is_test, ()
    tokens = [_normal_token(token) for token in clean.split("_") if _normal_token(token)]
    program = tokens.pop(0) if tokens and tokens[0] in {"Com", "Htr1"} else None
    is_alias = any(token in profile.aliases for token in tokens)
    tokens = [token for token in tokens if token not in profile.aliases]
    prefix = ""
    if "AlmStat" in tokens:
        prefix, tokens = "Alarm Status ", [token for token in tokens if token != "AlmStat"]
    elif "Alm" in tokens:
        prefix, tokens = "Alarm ", [token for token in tokens if token != "Alm"]
    is_command = "Cmd" in tokens or "Set" in tokens
    adjusted = []
    for token in tokens:
        if token == "Auto":
            adjusted.append("Auto Mode Field Switch" if is_alias else "Auto Mode" if is_command else "Auto Mode Status")
        else:
            adjusted.append(token)
    unknown: list[str] = []
    words = _expand_words(adjusted, profile, unknown)
    if member:
        words.extend(_member_words(member, profile, unknown))
    name = ("Heater " if program == "Htr1" else "") + prefix + " ".join(words)
    name = re.sub(r"\s+", " ", name).strip().replace("Setpoint Setpoint", "Setpoint")
    if not name:
        scaled = re.search(r"SCP(\d+)", base)
        name = f"Scaled Point {scaled.group(1)}" if scaled else clean.replace("_", " ").strip()
    return name, is_test, tuple(dict.fromkeys(unknown))


def _folder(base: str, member: str | None, is_test: bool, profile: NamingProfile) -> str:
    root = profile.display_root
    if is_test:
        return f"{root}/Diagnostics/Test"
    clean, _ = _strip_prefixes(base, profile.test_markers)
    signature = clean + ("_" + member if member else "")
    tokens = {_normal_token(token) for token in re.split(r"[_.]", signature) if token}
    program = "Htr1" if clean.startswith("Htr1") else "Com" if clean.startswith("Com") else None
    pump = "Pump 1" if "P1" in tokens else "Pump 2" if "P2" in tokens else None
    flow_pressure = "Flow" if "Flow" in tokens else "Pressure" if tokens & {"Pres", "Hdr", "Suc", "En"} else None
    if re.match(r"^TOT_\d", clean): return f"{root}/Flow Totalizers"
    if re.match(r"^SCP\d", clean) or re.match(r"^Com_SCP\d", base): return f"{root}/Analog Scaling"
    if clean in {"Job_Specific", "Project_Specific", "Pump_Specific"}: return f"{root}/Config"
    if "MU" in tokens: return f"{root}/Heater/Make-Up"
    if "HtC1" in tokens: return f"{root}/Hot Water Tank/Circulator"
    if program != "Htr1" and (tokens & {"Estop", "VFD", "Vfd", "AC1", "Horn"} or "FrW" in clean or {"Alm", "Res"} <= tokens or {"Alm", "Slnc"} <= tokens): return f"{root}/Panel Alarms"
    if "CW" in tokens: return "/".join(part for part in (root, "Cold Water System", pump or flow_pressure) if part)
    if tokens & {"HP", "LP"} and tokens & {"HW1", "HWT1"}:
        pressure = "High Pressure" if "HP" in tokens else "Low Pressure"
        return "/".join(part for part in (root, "Hot Water System", pressure, pump or flow_pressure) if part)
    if tokens & {"HWT1", "dHWT1"}:
        if tokens & {"Mod", "V1"}: return f"{root}/Hot Water Tank/Modulating Valve"
        if "Temp" in tokens: return f"{root}/Hot Water Tank/Temperature"
        if tokens & {"L", "Gal", "Lvl"}: return f"{root}/Hot Water Tank/Level"
        return f"{root}/Hot Water Tank"
    if program == "Htr1" or tokens & {"Htr1", "HtC", "Disch", "Recirc", "Rec", "FGR", "Blwr1", "Blwr", "Gas", "Air", "Stk", "StK", "Brn", "Flm", "Inlet", "Outlet", "Nozzle", "WWall", "SG"}:
        if "Gas" in tokens: return f"{root}/Heater/Combustion/Gas"
        if "Air" in tokens: return f"{root}/Heater/Combustion/Air"
        if tokens & {"Blwr1", "Blwr"}: return f"{root}/Heater/Combustion/Blower 1"
        if "FGR" in tokens: return f"{root}/Heater/Combustion/FGR"
        if tokens & {"Stk", "StK", "Inlet", "Outlet", "Brn", "Flm", "Nozzle", "WWall", "SG"}: return f"{root}/Heater/Combustion"
        if "Rep" in tokens: return f"{root}/Heater/Report"
        if "Disch" in tokens: return f"{root}/Heater/Discharge {pump or 'Pump 1'}"
        if tokens & {"Recirc", "Rec"}: return f"{root}/Heater/Recirculation Pump 1"
        if tokens & {"L", "Gal", "Lvl"}: return f"{root}/Heater/Level"
        return f"{root}/Heater"
    if tokens & {"HR1", "VC1"}: return f"{root}/Energy Reporting"
    return f"{root}/System" if program == "Com" else f"{root}/Unassigned"


def build_presentation(plc_tag: str, comment: str, profile: NamingProfile) -> Presentation:
    """Build a human-friendly presentation while preserving the PLC reference."""
    base, member = _split_member(plc_tag)
    name, is_test, unknown_tokens = _build_name(base, member, profile)
    folder = _folder(base, member, is_test, profile)
    override = profile.explicit.get(plc_tag, {})
    name = override.get("name") or name
    folder = override.get("folder") or folder
    return Presentation(plc_tag, name, folder, comment.strip() or name, name, is_test, unknown_tokens)


def _alias_qualifier(plc_tag: str) -> str | None:
    base, _ = _split_member(plc_tag)
    for alias, qualifier in _ALIAS_QUALIFIERS.items():
        if re.search(rf"(^|_){re.escape(alias)}(_|$)", base):
            return qualifier
    return None


def disambiguate_presentations(items: Sequence[Presentation]) -> list[Presentation]:
    """Return copies with unique names per folder in stable PLC-reference order."""
    result = list(items)
    groups: dict[tuple[str, str], list[int]] = defaultdict(list)
    for index, item in enumerate(result): groups[(item.folder, item.name)].append(index)
    for indexes in groups.values():
        if len(indexes) > 1:
            for index in indexes:
                qualifier = _alias_qualifier(result[index].plc_tag)
                if qualifier and qualifier not in result[index].name:
                    name = f"{result[index].name} ({qualifier})"
                    result[index] = replace(result[index], name=name, tooltip=name)
    seen: dict[tuple[str, str], int] = defaultdict(int)
    for index in sorted(range(len(result)), key=lambda item: result[item].plc_tag):
        item = result[index]; key = (item.folder, item.name); seen[key] += 1
        if seen[key] > 1:
            name = f"{item.name} {seen[key]}"
            result[index] = replace(item, name=name, tooltip=name)
    return result
