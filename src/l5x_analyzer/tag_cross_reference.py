"""Deterministic tag cross-reference extraction for exported L5X projects.

This module is intentionally structural.  It does not use FAISS, embeddings,
or natural-language queries.  A reference is emitted only when the operand can
be resolved against a declared controller/program tag (or a declared alias),
and coverage metadata makes skipped/unsupported logic visible to callers.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

from .aoi_logic_inspector import extract_ordered_parameters
from .rll_parser import find_calls


_PLACEHOLDERS = {"NA", "?"}
_IMPLICIT_AOI_PARAMS = {"EnableIn", "EnableOut"}
_ST_KEYWORDS = {
    "AND", "ARRAY", "AT", "BY", "CASE", "DO", "ELSE", "ELSIF", "END_CASE",
    "END_FOR", "END_IF", "END_REPEAT", "END_WHILE", "EXIT", "FOR", "FUNCTION",
    "IF", "NOT", "OF", "OR", "REPEAT", "RETURN", "THEN", "TO", "UNTIL",
    "VAR", "WHILE", "XOR",
}

# PLC identifiers can contain scoped-colon addresses, member paths, and array
# selectors.  The explicit Program:ProgramName.Tag form is handled before the
# general expression below so its qualifier is not mistaken for a tag.
_TAG_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9_])"
    r"(?:Program:[A-Za-z_][A-Za-z0-9_]*\.)?"
    r"[A-Za-z_][A-Za-z0-9_]*(?::[A-Za-z0-9_*]+)*"
    r"(?:\.(?:[A-Za-z_][A-Za-z0-9_]*|\d+)|\[\d+\])*"
)


@dataclass(frozen=True)
class _TagSymbol:
    name: str
    scope: str
    program: Optional[str]
    tag_type: str
    alias_for: Optional[str]


@dataclass(frozen=True)
class _ResolvedOperand:
    symbol: _TagSymbol
    member: str
    raw: str
    alias_target: Optional[str]

    @property
    def used_name(self) -> str:
        return self.symbol.name + self.member

    @property
    def terminal_target(self) -> str:
        return (self.alias_target or self.symbol.name) + self.member


class _SymbolTable:
    def __init__(self) -> None:
        self.controller: Dict[str, _TagSymbol] = {}
        self.programs: Dict[str, Dict[str, _TagSymbol]] = {}

    def add(self, symbol: _TagSymbol) -> None:
        if symbol.scope == "Controller":
            self.controller.setdefault(symbol.name, symbol)
        else:
            self.programs.setdefault(symbol.program or "", {}).setdefault(
                symbol.name, symbol
            )

    def candidates(self, name: str) -> List[_TagSymbol]:
        result: List[_TagSymbol] = []
        if name in self.controller:
            result.append(self.controller[name])
        for program in self.programs.values():
            if name in program:
                result.append(program[name])
        return result

    def resolve(self, token: str, program: Optional[str]) -> Optional[_ResolvedOperand]:
        root, member, explicit_program = _split_tag_path(token)
        selected: Optional[_TagSymbol] = None

        if explicit_program is not None:
            selected = self.programs.get(explicit_program, {}).get(root)
        elif program and root in self.programs.get(program, {}):
            selected = self.programs[program][root]
        else:
            selected = self.controller.get(root)

        if selected is None:
            return None

        alias_target = _resolve_alias_target(selected, self)
        return _ResolvedOperand(selected, member, token, alias_target)


def _split_tag_path(token: str) -> Tuple[str, str, Optional[str]]:
    """Return ``(base, member_suffix, explicit_program)`` for an operand."""
    explicit_program: Optional[str] = None
    body = token
    if token.startswith("Program:"):
        qualified = token[len("Program:"):]
        if "." in qualified:
            explicit_program, body = qualified.split(".", 1)

    match = re.match(r"^[A-Za-z_][A-Za-z0-9_]*(?::[A-Za-z0-9_*]+)*", body)
    if not match:
        return body, "", explicit_program
    return body[:match.end()], body[match.end():], explicit_program


def _resolve_alias_target(symbol: _TagSymbol, table: _SymbolTable) -> Optional[str]:
    """Resolve an alias chain without looping on malformed/cyclic exports."""
    if symbol.tag_type != "Alias" or not symbol.alias_for:
        return None

    current = symbol.alias_for
    visited = {symbol.name}
    while current:
        root, _member, _program = _split_tag_path(current)
        if root in visited:
            return current
        visited.add(root)
        program_symbols = table.programs.get(symbol.program or "", {})
        next_symbol = program_symbols.get(root) or table.controller.get(root)
        if next_symbol is None:
            for program in table.programs.values():
                next_symbol = program.get(root)
                if next_symbol is not None:
                    break
        if next_symbol is None or next_symbol.tag_type != "Alias" or not next_symbol.alias_for:
            return current
        current = next_symbol.alias_for
    return None


def _controller(root: ET.Element) -> Optional[ET.Element]:
    direct = root.find("Controller")
    return direct if direct is not None else root.find(".//Controller")


def _build_symbols(controller: ET.Element) -> _SymbolTable:
    table = _SymbolTable()

    tags = controller.find("Tags")
    if tags is not None:
        for tag in tags.findall("Tag"):
            table.add(_tag_symbol(tag, "Controller", None))

    programs = controller.findall("Programs/Program")
    for program in programs:
        name = program.get("Name")
        if not name:
            continue
        for tag in program.findall("Tags/Tag"):
            table.add(_tag_symbol(tag, "Program", name))
    return table


def _tag_symbol(tag: ET.Element, scope: str, program: Optional[str]) -> _TagSymbol:
    return _TagSymbol(
        name=tag.get("Name", ""),
        scope=scope,
        program=program,
        tag_type=tag.get("TagType", "Base"),
        alias_for=tag.get("AliasFor"),
    )


def _aoi_definitions(root: ET.Element) -> Dict[str, ET.Element]:
    return {
        aoi.get("Name").upper(): aoi
        for aoi in root.findall(".//AddOnInstructionDefinitions/AddOnInstructionDefinition")
        if aoi.get("Name")
    }


def _strip_strings(text: str) -> str:
    return re.sub(r'"(?:[^"\\]|\\.)*"', lambda m: " " * len(m.group(0)), text)


def _strip_comments(text: str) -> str:
    """Blank line and block comments while preserving source positions."""
    text = re.sub(r"//[^\r\n]*", lambda m: " " * len(m.group(0)), text)
    return re.sub(r"\(\*.*?\*\)|/\*.*?\*/", lambda m: " " * len(m.group(0)), text, flags=re.DOTALL)


def _tag_tokens(text: str) -> Iterator[Tuple[str, int, int]]:
    """Yield candidate PLC tokens with source spans, excluding literals."""
    clean = _strip_comments(_strip_strings(text))
    for match in _TAG_TOKEN_RE.finditer(clean):
        token = match.group(0)
        if token.upper() in _PLACEHOLDERS or token.upper() in _ST_KEYWORDS:
            continue
        yield token, match.start(), match.end()


def _role_for(mnemonic: str, operand_index: int, count: int) -> Optional[str]:
    """Return a conservative role for a built-in instruction operand."""
    name = mnemonic.upper()
    if name in {"XIC", "XIO", "EQU", "NEQ", "LES", "LEQ", "GRT", "GEQ", "LIM", "MEQ"}:
        return "READ_SOURCE"
    if name in {"OTE", "OTL", "OTU", "CLR"}:
        return "WRITE_DESTINATION"
    if name in {"ONS", "OSR", "OSF"}:
        return "READ_WRITE"
    if name in {"TON", "TOF", "RTO", "CTU", "CTD", "RES"}:
        return "READ_WRITE" if operand_index == 0 else "READ_SOURCE"
    if name in {"MOV", "BTD", "CPT", "ADD", "SUB", "MUL", "DIV", "MOD", "NEG", "ABS", "SQR", "SQRT", "TRUNC", "FRD", "TOD", "SWPB", "SCP", "SCPL", "SCL", "FLL", "MVM", "GSV"}:
        return "WRITE_DESTINATION" if operand_index == count - 1 else "READ_SOURCE"
    if name in {"COP", "CPS"}:
        if operand_index == 1:
            return "WRITE_DESTINATION"
        return "READ_SOURCE"
    if name in {"JSR", "SBR", "SSV", "FAL", "FSC"}:
        return "READ_SOURCE"
    if name in {"NOP", "JMP", "LBL", "RET", "TND", "AFI", "XIC", "XIO"} and count == 0:
        return None
    return None


def _known_instruction(mnemonic: str) -> bool:
    return _role_for(mnemonic, 0, 1) is not None or mnemonic.upper() in {
        "NOP", "JMP", "LBL", "RET", "TND", "AFI", "SBR"
    }


def _direction_for_usage(usage: str) -> str:
    usage = (usage or "").lower()
    if usage == "input":
        return "READ_SOURCE"
    if usage == "output":
        return "WRITE_DESTINATION"
    if usage == "inout":
        return "READ_WRITE"
    return "READ_SOURCE"


def _query_symbol(table: _SymbolTable, tag_name: str, program_scope: Optional[str]) -> Tuple[Optional[_TagSymbol], str, Optional[str]]:
    root, member, explicit_program = _split_tag_path(tag_name)
    selected_program = explicit_program or program_scope
    controller_scope = bool(selected_program and selected_program.lower() == "controller")

    if controller_scope:
        # ``Controller`` is an explicit scope, not the absence of a scope.  A
        # controller tag and a same-named program tag may legally coexist.
        return table.controller.get(root), member, "Controller"

    if selected_program:
        # A controller-scope tag can be queried while restricting the walk to a
        # particular program.  Prefer a program-local definition when present,
        # otherwise resolve the controller symbol and apply the program filter
        # to the location walk.
        return (
            table.programs.get(selected_program, {}).get(root)
            or table.controller.get(root),
            member,
            selected_program,
        )

    candidates = table.candidates(root)
    if len(candidates) == 1:
        return candidates[0], member, None
    if not candidates:
        return None, member, None
    return None, member, "ambiguous"


def _member_matches(query_member: str, occurrence_member: str) -> bool:
    return not query_member or occurrence_member == query_member or occurrence_member.startswith(query_member + ".")


def _matches_query(
    resolved: _ResolvedOperand,
    query_symbol: _TagSymbol,
    query_member: str,
) -> bool:
    if resolved.symbol.name == query_symbol.name and resolved.symbol.scope == query_symbol.scope and resolved.symbol.program == query_symbol.program:
        return _member_matches(query_member, resolved.member)

    # A base-tag query should also find an alias used in logic when that alias
    # resolves to the queried base.  The raw alias remains in the evidence row.
    alias_target = resolved.alias_target
    if alias_target:
        target_root, target_member, _ = _split_tag_path(alias_target)
        return target_root == query_symbol.name and _member_matches(
            query_member, target_member + resolved.member
        )
    return False


def _base_occurrence(
    resolved: _ResolvedOperand,
    program: str,
    routine: str,
    instruction: str,
    operand_index: int,
    role: str,
    rung_number: Optional[int],
    instruction_index: int,
    raw_operand: str,
) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "tag_name": resolved.symbol.name,
        "scope": resolved.symbol.scope,
        "tag_program": resolved.symbol.program,
        "program": program,
        "routine": routine,
        "rung_number": rung_number,
        "rung": rung_number,
        "instruction": instruction,
        "instruction_index": instruction_index,
        "operand_index": operand_index,
        "operand_position": operand_index,
        "operand": raw_operand,
        "raw_operand": raw_operand,
        "resolved_tag": resolved.used_name,
        "resolved_target": resolved.terminal_target,
        "role": role,
    }
    if resolved.symbol.tag_type == "Alias":
        row["alias_for"] = resolved.symbol.alias_for
        row["alias_target"] = resolved.alias_target
    return row


def _rll_rows(
    text: str,
    program: str,
    routine: str,
    rung_number: int,
    table: _SymbolTable,
    aois: Dict[str, ET.Element],
    warnings: List[str],
) -> Iterator[Tuple[_ResolvedOperand, Dict[str, Any]]]:
    calls = find_calls(_strip_comments(_strip_strings(text)))
    for instruction_index, (mnemonic, operands, _source) in enumerate(calls):
        upper = mnemonic.upper()
        aoi = aois.get(upper)
        if aoi is not None:
            params = [
                p for p in extract_ordered_parameters(aoi)
                if p["required"] and p["name"] not in _IMPLICIT_AOI_PARAMS
            ]
            for operand_index, operand in enumerate(operands):
                if operand.upper() in _PLACEHOLDERS:
                    continue
                resolved = table.resolve(operand, program)
                if resolved is None:
                    continue
                if operand_index == 0:
                    param_name = "__instance__"
                    usage = "InOut"
                    direction = "READ_WRITE"
                elif operand_index - 1 < len(params):
                    param = params[operand_index - 1]
                    param_name = param["name"]
                    usage = param["usage"]
                    direction = _direction_for_usage(usage)
                else:
                    param_name = "__extra__"
                    usage = "Unknown"
                    direction = "READ_SOURCE"
                    warnings.append(
                        f"AOI {mnemonic} in {program}/{routine} rung {rung_number} has an extra operand at index {operand_index}."
                    )
                row = _base_occurrence(
                    resolved, program, routine, mnemonic, operand_index, "AOI_ARG",
                    rung_number, instruction_index, operand,
                )
                row.update({
                    "param_name": param_name,
                    "usage": usage,
                    "direction": direction,
                })
                yield resolved, row
            if len(operands) - 1 != len(params):
                warnings.append(
                    f"AOI {mnemonic} in {program}/{routine} rung {rung_number} has {max(0, len(operands) - 1)} arguments for {len(params)} required parameters."
                )
            continue

        if not _known_instruction(mnemonic):
            warnings.append(
                f"Unsupported RLL instruction '{mnemonic}' in {program}/{routine} rung {rung_number}; tag roles are unknown."
            )

        for operand_index, operand in enumerate(operands):
            role = _role_for(mnemonic, operand_index, len(operands)) or "UNKNOWN"
            for token, _start, _end in _tag_tokens(operand):
                resolved = table.resolve(token, program)
                if resolved is None:
                    continue
                yield resolved, _base_occurrence(
                    resolved, program, routine, mnemonic, operand_index, role,
                    rung_number, instruction_index, operand,
                )


def _st_rows(
    text: str,
    program: str,
    routine: str,
    line_number: int,
    table: _SymbolTable,
) -> Iterator[Tuple[_ResolvedOperand, Dict[str, Any]]]:
    assignment = re.search(r":=", text)
    for token, start, _end in _tag_tokens(text):
        resolved = table.resolve(token, program)
        if resolved is None:
            continue
        if assignment and start < assignment.start():
            role = "WRITE_DESTINATION"
        else:
            role = "READ_SOURCE"
        yield resolved, _base_occurrence(
            resolved, program, routine, "ST", 0, role,
            line_number, 0, text.strip(),
        )


def _coverage() -> Dict[str, Any]:
    return {
        "complete": True,
        "routines_scanned": 0,
        "routines_skipped": [],
        "warnings": [],
    }


def find_tag_references(
    l5x_file_path: str | Path,
    tag_name: str,
    program_scope: Optional[str] = None,
) -> Dict[str, Any]:
    """Return exact read/write/AOI references for ``tag_name`` in an L5X.

    ``program_scope`` is a program name, or ``Controller`` for a controller
    scoped query.  Ambiguous definitions are rejected explicitly.  A successful
    zero-reference response is still accompanied by ``coverage`` so callers can
    distinguish an unused tag from an encrypted or otherwise uninspectable
    project.
    """
    try:
        root = ET.parse(str(l5x_file_path)).getroot()
    except Exception as exc:
        return {"success": False, "error": f"Failed to parse L5X '{l5x_file_path}': {exc}"}

    controller = _controller(root)
    if controller is None:
        return {"success": False, "error": "No <Controller> element found in L5X."}

    table = _build_symbols(controller)
    query_symbol, query_member, query_status = _query_symbol(table, tag_name, program_scope)
    if query_status == "ambiguous":
        locations = [
            "controller" if c.scope == "Controller" else f"program '{c.program}'"
            for c in table.candidates(_split_tag_path(tag_name)[0])
        ]
        return {
            "success": False,
            "error": f"Tag '{tag_name}' is ambiguous — defined in {', '.join(locations)}. Pass program_scope to disambiguate.",
        }
    if query_symbol is None:
        scope_note = f" in program '{program_scope}'" if program_scope and program_scope.lower() != "controller" else ""
        return {"success": False, "error": f"Tag '{tag_name}' not found{scope_note}."}

    coverage = _coverage()
    aois = _aoi_definitions(root)
    references: List[Dict[str, Any]] = []

    for program_elem in controller.findall("Programs/Program"):
        program = program_elem.get("Name")
        if not program or (program_scope and program_scope.lower() != "controller" and program != program_scope):
            continue
        routines_parent = program_elem.find("Routines")
        if routines_parent is None:
            continue

        for routine_elem in routines_parent.findall("Routine"):
            routine = routine_elem.get("Name", "Unknown")
            routine_type = (routine_elem.get("Type") or "RLL").upper()
            coverage["routines_scanned"] += 1
            if routine_type == "RLL":
                rll = routine_elem.find("RLLContent")
                if rll is None:
                    coverage["complete"] = False
                    coverage["routines_skipped"].append({"program": program, "routine": routine, "reason": "missing RLLContent"})
                    continue
                for rung in rll.findall("Rung"):
                    try:
                        rung_number = int(rung.get("Number", "0"))
                    except ValueError:
                        rung_number = None
                    text_elem = rung.find("Text")
                    text = (text_elem.text or "") if text_elem is not None else ""
                    for resolved, row in _rll_rows(text, program, routine, rung_number, table, aois, coverage["warnings"]):
                        if _matches_query(resolved, query_symbol, query_member):
                            references.append(row)
            elif routine_type in {"ST", "STRUCTURED_TEXT", "STRUCTUREDTEXT"}:
                st_content = routine_elem.find("STContent")
                lines = st_content.findall(".//Line") if st_content is not None else []
                if not lines:
                    lines = routine_elem.findall(".//Line")
                if not lines and st_content is not None:
                    lines = [st_content]
                if not lines:
                    coverage["complete"] = False
                    coverage["routines_skipped"].append({"program": program, "routine": routine, "reason": "missing ST lines"})
                    continue
                for fallback, line in enumerate(lines):
                    try:
                        line_number = int(line.get("Number", str(fallback)))
                    except ValueError:
                        line_number = fallback
                    text = "".join(line.itertext()) if line.tag == "STContent" else (line.text or "")
                    for resolved, row in _st_rows(text, program, routine, line_number, table):
                        if _matches_query(resolved, query_symbol, query_member):
                            references.append(row)
            else:
                coverage["complete"] = False
                coverage["routines_skipped"].append({"program": program, "routine": routine, "reason": f"unsupported routine type {routine_type}"})

        for encoded in routines_parent.findall("EncodedData"):
            if encoded.get("EncodedType") != "Routine":
                continue
            coverage["complete"] = False
            coverage["routines_skipped"].append({
                "program": program,
                "routine": encoded.get("Name", "Unknown"),
                "reason": "encrypted routine logic is not inspectable",
            })

    summary = {
        "reads": sum(r["role"] == "READ_SOURCE" for r in references),
        "writes": sum(r["role"] == "WRITE_DESTINATION" for r in references),
        "read_write": sum(r["role"] == "READ_WRITE" for r in references),
        "aoi_args": sum(r["role"] == "AOI_ARG" for r in references),
        "unknown": sum(r["role"] == "UNKNOWN" for r in references),
        "total": len(references),
    }
    coverage["complete"] = coverage["complete"] and not coverage["warnings"]
    return {
        "success": True,
        "tag": tag_name,
        "scope": query_symbol.scope,
        # Preserve the caller's filter separately from the tag's declaration
        # scope.  This matters for controller tags queried within one program.
        "program_scope": program_scope,
        "tag_program": query_symbol.program,
        "references": references,
        "summary": summary,
        "coverage": coverage,
    }
