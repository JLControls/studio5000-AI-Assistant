"""Shared, conservative instruction semantics for offline PLC analysis.

The table in this module is the single source of truth for operand direction
across cross-reference, write detection, comment-graph, and validation code.
Selectors are zero-based operand indices; ``-1`` means the final supplied
operand.  An instruction may have a control operand that is both read and
written without being a data destination, such as the instance operand of a
timer or one-shot instruction.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping, Optional


class OperandRole(str, Enum):
    """Stable JSON-safe roles for instruction operands."""

    READ_SOURCE = "READ_SOURCE"
    WRITE_DESTINATION = "WRITE_DESTINATION"
    READ_WRITE_CONTROL = "READ_WRITE_CONTROL"
    AOI_INPUT = "AOI_INPUT"
    AOI_OUTPUT = "AOI_OUTPUT"
    AOI_INOUT = "AOI_INOUT"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class InstructionSemantics:
    """Operand selectors for one instruction mnemonic."""

    read_operands: tuple[int, ...] = ()
    write_operands: tuple[int, ...] = ()
    control_operands: tuple[int, ...] = ()

    @property
    def is_destructive(self) -> bool:
        return bool(self.write_operands or self.control_operands)


def _semantics(
    *,
    read: tuple[int, ...] = (),
    write: tuple[int, ...] = (),
    control: tuple[int, ...] = (),
) -> InstructionSemantics:
    return InstructionSemantics(
        read_operands=read,
        write_operands=write,
        control_operands=control,
    )


# This set retains the verifier's accepted instruction vocabulary.  Direction
# is intentionally separate: a known instruction without a safe operand rule
# is still known, but its operands remain unresolved by graph analysis.
COMMON_INSTRUCTIONS = frozenset({
    # Basic instructions
    "XIC", "XIO", "OTE", "OTL", "OTU", "ONS", "OSR", "OSF",
    # Timer and counter instructions
    "TON", "TOF", "RTO", "CTU", "CTD", "CTC", "TONR", "TOFR", "UPDN",
    # Math and comparison instructions
    "ADD", "SUB", "MUL", "DIV", "MOD", "SQR", "SQRT", "NEG", "ABS",
    "MIN", "MAX", "LIM", "MUX", "EQU", "NEQ", "LES", "LEQ", "GRT",
    "GEQ", "MEQ", "EQ", "NE", "LT", "LE", "GT", "GE",
    # Logical instructions
    "AND", "OR", "XOR", "NOT", "BAND", "BOR", "BXOR",
    # Move and conversion instructions
    "MOV", "MOVE", "MVM", "SWPB", "CLR", "TOD", "FRD", "DEG", "RAD",
    # File/array and data movement instructions
    "COP", "CPS", "FLL", "BTD", "BTDT", "AVE", "SRT", "STD", "SIZE",
    # Program control
    "JMP", "LBL", "JSR", "RET", "SBR", "FOR", "NXT", "BRK", "MCR",
    "END", "TND", "UID", "UIE", "AFI", "NOP",
    # System, message, PID, and advanced instruction vocabulary
    "GSV", "SSV", "IOT", "MSG", "PID", "PIDE", "ALMA", "ALMD", "DEDT",
    "DERV", "HMIBC", "HPF", "INTG", "LPF", "MAAT", "MAFR", "MAHD",
    "MAHO", "MAOC", "MAPC", "MAST", "MATC", "MAXC", "MDAC", "MDCC",
    "MDOC", "MDSF", "MRHD", "MRAT", "MRCC", "MRCS", "MRST", "MSET",
    "MTLF", "MTTP", "PATT", "PCMD", "PRNP", "RESD", "RLLK", "RMPD",
    "RMPS", "SCRV", "SEL", "SMAT", "SMOC", "STOS",
})


_SEMANTICS: dict[str, InstructionSemantics] = {
    # Contacts and comparisons
    "XIC": _semantics(read=(0,)),
    "XIO": _semantics(read=(0,)),
    "EQU": _semantics(read=(0, 1)),
    "NEQ": _semantics(read=(0, 1)),
    "LES": _semantics(read=(0, 1)),
    "LEQ": _semantics(read=(0, 1)),
    "GRT": _semantics(read=(0, 1)),
    "GEQ": _semantics(read=(0, 1)),
    "MEQ": _semantics(read=(0, 1)),
    "EQ": _semantics(read=(0, 1)),
    "NE": _semantics(read=(0, 1)),
    "LT": _semantics(read=(0, 1)),
    "LE": _semantics(read=(0, 1)),
    "GT": _semantics(read=(0, 1)),
    "GE": _semantics(read=(0, 1)),
    "LIM": _semantics(read=(0, 1, 2)),
    # Coils, latches, resets, and one-shots
    "OTE": _semantics(write=(0,)),
    "OTL": _semantics(write=(0,)),
    "OTU": _semantics(write=(0,)),
    "RES": _semantics(write=(0,)),
    "CLR": _semantics(write=(0,)),
    "ONS": _semantics(control=(0,)),
    "OSR": _semantics(control=(0,)),
    "OSF": _semantics(control=(0,)),
    # Timer and counter instances are stateful control operands; preset and
    # accumulated values are read operands when they are tag references.
    "TON": _semantics(read=(1, 2), control=(0,)),
    "TOF": _semantics(read=(1, 2), control=(0,)),
    "RTO": _semantics(read=(1, 2), control=(0,)),
    "CTU": _semantics(read=(1, 2), control=(0,)),
    "CTD": _semantics(read=(1, 2), control=(0,)),
    # Data movement and math. ``-1`` is the final supplied operand.
    "MOV": _semantics(read=(0,), write=(-1,)),
    "MOVE": _semantics(read=(0,), write=(-1,)),
    "MVM": _semantics(read=(0, 1), write=(2,)),
    "COP": _semantics(read=(0,), write=(1,)),
    "CPS": _semantics(read=(0,), write=(1,)),
    "FLL": _semantics(read=(0,), write=(1,)),
    "BTD": _semantics(read=(0, 1), write=(2,)),
    "ADD": _semantics(read=(0, 1), write=(-1,)),
    "SUB": _semantics(read=(0, 1), write=(-1,)),
    "MUL": _semantics(read=(0, 1), write=(-1,)),
    "DIV": _semantics(read=(0, 1), write=(-1,)),
    "MOD": _semantics(read=(0, 1), write=(-1,)),
    "NEG": _semantics(read=(0,), write=(-1,)),
    "ABS": _semantics(read=(0,), write=(-1,)),
    "SQR": _semantics(read=(0,), write=(-1,)),
    "SQRT": _semantics(read=(0,), write=(-1,)),
    "TRUNC": _semantics(read=(0,), write=(-1,)),
    "FRD": _semantics(read=(0,), write=(-1,)),
    "TOD": _semantics(read=(0,), write=(-1,)),
    "SWPB": _semantics(read=(0,), write=(-1,)),
    "SCP": _semantics(read=(0, 1, 2, 3, 4), write=(5,)),
    "SCPL": _semantics(read=(0, 1, 2, 3, 4), write=(5,)),
    "SCL": _semantics(read=(0, 1, 2, 3, 4), write=(5,)),
    "GSV": _semantics(read=(0,), write=(1,)),
    "CPT": _semantics(read=(1,), write=(0,)),
    # Control-flow and system instructions have known syntax but no generic
    # tag-direction rule here.
    "JSR": _semantics(read=(0,)),
    "SBR": _semantics(read=(0,)),
    "SSV": _semantics(read=(0, 1, 2)),
    "FAL": _semantics(read=(0, 1, 2)),
    "FSC": _semantics(read=(0, 1, 2)),
}

# Keep known-but-undirected instructions in the same table so consumers do not
# maintain a second vocabulary.  They intentionally receive UNKNOWN roles.
for _mnemonic in COMMON_INSTRUCTIONS:
    _SEMANTICS.setdefault(_mnemonic, InstructionSemantics())

# Directional entries such as CPT/SCP are also part of the known vocabulary;
# expose the union so verifier and graph diagnostics agree on what is known.
COMMON_INSTRUCTIONS = frozenset(set(COMMON_INSTRUCTIONS) | set(_SEMANTICS))
INSTRUCTION_SEMANTICS: Mapping[str, InstructionSemantics] = MappingProxyType(_SEMANTICS)


def _resolve_indices(selectors: tuple[int, ...], operand_count: int) -> tuple[int, ...]:
    if operand_count <= 0:
        return ()

    resolved: list[int] = []
    for selector in selectors:
        index = operand_count - 1 if selector == -1 else selector
        if 0 <= index < operand_count and index not in resolved:
            resolved.append(index)
    return tuple(resolved)


def get_operand_indices(
    mnemonic: str,
    operand_count: int,
) -> tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...]]:
    """Return resolved ``(read, write, control)`` operand indices."""
    semantics = INSTRUCTION_SEMANTICS.get(mnemonic.upper())
    if semantics is None:
        return (), (), ()
    return (
        _resolve_indices(semantics.read_operands, operand_count),
        _resolve_indices(semantics.write_operands, operand_count),
        _resolve_indices(semantics.control_operands, operand_count),
    )


def get_instruction_operand_role(
    mnemonic: str,
    operand_index: int,
    operand_count: int,
) -> OperandRole:
    """Classify one operand conservatively using the shared table."""
    reads, writes, controls = get_operand_indices(mnemonic, operand_count)
    if operand_index in controls:
        return OperandRole.READ_WRITE_CONTROL
    if operand_index in writes:
        return OperandRole.WRITE_DESTINATION
    if operand_index in reads:
        return OperandRole.READ_SOURCE
    return OperandRole.UNKNOWN


def is_destructive(mnemonic: str, operand_count: Optional[int] = None) -> bool:
    """Return whether an instruction can mutate a destination or control tag."""
    semantics = INSTRUCTION_SEMANTICS.get(mnemonic.upper())
    if semantics is None:
        return False
    if operand_count is None:
        return semantics.is_destructive
    _reads, writes, controls = get_operand_indices(mnemonic, operand_count)
    return bool(writes or controls)


def is_known_instruction(mnemonic: str) -> bool:
    """Return whether the mnemonic is in the shared known vocabulary."""
    return mnemonic.upper() in INSTRUCTION_SEMANTICS
