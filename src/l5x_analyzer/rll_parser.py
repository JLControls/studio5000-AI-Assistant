"""Small, dependency-free helpers for parsing RLL instruction calls.

The exported RLL representation is text inside ``<Text>`` CDATA nodes.  A
comma is not necessarily an operand separator: expressions and branch legs can
contain nested parentheses or square brackets.  These helpers deliberately do
only the balanced-delimiter work.  Instruction semantics and tag resolution
belong to the cross-reference engine.
"""

from __future__ import annotations

from typing import List, Tuple


def split_operands(inner: str) -> List[str]:
    """Split an instruction's argument text on top-level commas."""
    if not inner.strip():
        return []

    operands: List[str] = []
    depth = 0
    current: List[str] = []
    for char in inner:
        if char in "([":
            depth += 1
        elif char in ")]":
            depth = max(0, depth - 1)
        if char == "," and depth == 0:
            operands.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    operands.append("".join(current).strip())
    return operands


def find_calls(text: str) -> List[Tuple[str, List[str], str]]:
    """Return balanced ``(mnemonic, operands, source_text)`` tuples.

    The scan advances past a complete call after finding its matching closing
    parenthesis.  This preserves instruction order and prevents commas inside a
    nested expression from shifting operand positions.
    """
    calls: List[Tuple[str, List[str], str]] = []
    index = 0
    length = len(text)

    while index < length:
        char = text[index]
        if not (char.isalpha() or char == "_"):
            index += 1
            continue

        name_end = index + 1
        while name_end < length and (
            text[name_end].isalnum() or text[name_end] == "_"
        ):
            name_end += 1

        mnemonic = text[index:name_end]
        open_index = name_end
        while open_index < length and text[open_index] in " \t":
            open_index += 1
        if open_index >= length or text[open_index] != "(":
            index = name_end
            continue

        depth = 0
        close_index = open_index
        while close_index < length:
            if text[close_index] == "(":
                depth += 1
            elif text[close_index] == ")":
                depth -= 1
                if depth == 0:
                    break
            close_index += 1

        if depth != 0:
            # An incomplete call is not an instruction we can classify safely.
            # Leave it out; callers can report their own malformed-text warning.
            break

        inner = text[open_index + 1:close_index]
        calls.append(
            (mnemonic, split_operands(inner), text[index:close_index + 1])
        )
        index = close_index + 1

    return calls
