"""
Ladder Logic to Graphviz DOT Converter

Converts Rockwell Automation ladder logic (RLL) text syntax into 
Graphviz DOT format for visualization with d3-graphviz.

Handles complex nested branch structures (BST/NXB/BND) and generates
properly aligned parallel branches using rank=same constraints.
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Union


class InstructionType(Enum):
    """Types of ladder logic instructions for visual rendering."""
    CONTACT_NO = "contact_no"       # Normally Open (XIC)
    CONTACT_NC = "contact_nc"       # Normally Closed (XIO)
    COIL = "coil"                   # Output Energize (OTE)
    COIL_LATCH = "coil_latch"       # Output Latch (OTL)
    COIL_UNLATCH = "coil_unlatch"   # Output Unlatch (OTU)
    TIMER = "timer"                 # TON, TOF, RTO
    COUNTER = "counter"             # CTU, CTD
    COMPARE = "compare"             # EQU, NEQ, LES, GRT, etc.
    MATH = "math"                   # ADD, SUB, MUL, DIV, CPT
    MOVE = "move"                   # MOV, MVM, COP
    ONESHOT = "oneshot"             # ONS, OSR, OSF
    MOTION = "motion"               # MSO, MSF, MAJ, MAH, etc.
    FUNCTION = "function"           # JSR, SBR, RET
    RESET = "reset"                 # RES
    AOI = "aoi"                     # Add-On Instructions
    OTHER = "other"                 # Unknown/Other


# Friendly names for instructions (displayed in ladder diagrams)
INSTRUCTION_FRIENDLY_NAMES: dict[str, str] = {
    'CTU': 'Count Up',
    'CTD': 'Count Down',
    'TON': 'Timer On Delay',
    'TOF': 'Timer Off Delay', 
    'RTO': 'Retentive Timer',
    'XIC': 'Examine If Closed',
    'XIO': 'Examine If Open',
    'OTE': 'Output Energize',
    'OTL': 'Output Latch',
    'OTU': 'Output Unlatch',
    'ONS': 'One Shot',
    'OSR': 'One Shot Rising',
    'OSF': 'One Shot Falling',
    'RES': 'Reset',
    'MOV': 'Move',
    'ADD': 'Add',
    'SUB': 'Subtract',
    'MUL': 'Multiply',
    'DIV': 'Divide',
    'EQU': 'Equal',
    'NEQ': 'Not Equal',
    'LES': 'Less Than',
    'LEQ': 'Less Or Equal',
    'GRT': 'Greater Than',
    'GEQ': 'Greater Or Equal',
    'JSR': 'Jump To Subroutine',
    'RET': 'Return',
    'GSV': 'Get System Value',
    'SSV': 'Set System Value',
    'MSG': 'Message',
    'COP': 'Copy',
    'FLL': 'Fill',
    'CLR': 'Clear',
    'BTD': 'Bit Field Distribute',
}


@dataclass
class LadderInstruction:
    """Represents a parsed ladder logic instruction."""
    instruction: str
    operands: list[str]
    instruction_type: InstructionType
    node_id: str = ""
    
    def get_primary_tag(self) -> str:
        """Get the primary tag name from operands."""
        if self.operands:
            return self.operands[0].split('.')[0].split('[')[0]
        return ""


@dataclass
class LadderBranch:
    """Represents a branch in ladder logic (BST/NXB structure)."""
    elements: list[Union[LadderInstruction, 'LadderBranchGroup']] = field(default_factory=list)


@dataclass
class LadderBranchGroup:
    """Represents a group of parallel branches."""
    branches: list[LadderBranch] = field(default_factory=list)


@dataclass
class LadderRung:
    """Represents a complete ladder rung with all branches."""
    rung_number: int
    comment: str
    main_branch: LadderBranch = field(default_factory=LadderBranch)


class LadderParser:
    """
    Parses ladder logic text syntax into structured objects.
    
    The L5X ladder logic uses a specific text format:
    - Instructions: INSTR(operand1,operand2,...)
    - Serial: Instructions in sequence
    - Parallel branches: [branch1 ,branch2 ,branch3]
    - Legacy branches: BST ... NXB ... BND
    """
    
    # Instruction classification
    INSTRUCTION_TYPES = {
        # Contacts
        'XIC': InstructionType.CONTACT_NO,
        'XIO': InstructionType.CONTACT_NC,
        
        # Coils
        'OTE': InstructionType.COIL,
        'OTL': InstructionType.COIL_LATCH,
        'OTU': InstructionType.COIL_UNLATCH,
        
        # Timers
        'TON': InstructionType.TIMER,
        'TOF': InstructionType.TIMER,
        'RTO': InstructionType.TIMER,
        
        # Counters
        'CTU': InstructionType.COUNTER,
        'CTD': InstructionType.COUNTER,
        
        # Comparisons
        'EQU': InstructionType.COMPARE,
        'NEQ': InstructionType.COMPARE,
        'LES': InstructionType.COMPARE,
        'LEQ': InstructionType.COMPARE,
        'GRT': InstructionType.COMPARE,
        'GEQ': InstructionType.COMPARE,
        'LIM': InstructionType.COMPARE,
        'MEQ': InstructionType.COMPARE,
        'CMP': InstructionType.COMPARE,
        
        # Math
        'ADD': InstructionType.MATH,
        'SUB': InstructionType.MATH,
        'MUL': InstructionType.MATH,
        'DIV': InstructionType.MATH,
        'CPT': InstructionType.MATH,
        'SQR': InstructionType.MATH,
        'ABS': InstructionType.MATH,
        
        # Move
        'MOV': InstructionType.MOVE,
        'MVM': InstructionType.MOVE,
        'COP': InstructionType.MOVE,
        'FLL': InstructionType.MOVE,
        'CLR': InstructionType.MOVE,
        
        # One-shots
        'ONS': InstructionType.ONESHOT,
        'OSR': InstructionType.ONESHOT,
        'OSF': InstructionType.ONESHOT,
        
        # Motion
        'MSO': InstructionType.MOTION,
        'MSF': InstructionType.MOTION,
        'MAJ': InstructionType.MOTION,
        'MAM': InstructionType.MOTION,
        'MAH': InstructionType.MOTION,
        'MAS': InstructionType.MOTION,
        'MAFR': InstructionType.MOTION,
        'MAPC': InstructionType.MOTION,
        
        # Functions
        'JSR': InstructionType.FUNCTION,
        'SBR': InstructionType.FUNCTION,
        'RET': InstructionType.FUNCTION,
        
        # Reset
        'RES': InstructionType.RESET,
    }
    
    # Pattern to match instructions with their operands
    INSTRUCTION_PATTERN = re.compile(
        r'([A-Z_][A-Z0-9_]*)\s*\(([^()]*(?:\([^()]*\)[^()]*)*)\)',
        re.IGNORECASE
    )
    
    def __init__(self):
        self._node_counter = 0
    
    def _next_node_id(self) -> str:
        """Generate unique node ID."""
        self._node_counter += 1
        return f"n{self._node_counter}"
    
    def parse_rung(self, rung_text: str, rung_number: int = 0, comment: str = "") -> LadderRung:
        """Parse a complete rung text into structured format."""
        self._node_counter = 0
        rung = LadderRung(rung_number=rung_number, comment=comment)
        
        # Clean up the text
        text = rung_text.strip()
        if text.endswith(';'):
            text = text[:-1]
        
        # Parse the main branch
        rung.main_branch = self._parse_branch_content(text)
        return rung
    
    def _parse_branch_content(self, text: str) -> LadderBranch:
        """Parse branch content which may contain nested branches."""
        branch = LadderBranch()
        pos = 0
        
        while pos < len(text):
            char = text[pos]
            
            if char == '[':
                # Found a branch group
                end_pos = self._find_matching_bracket(text, pos)
                branch_text = text[pos+1:end_pos]
                branch_group = self._parse_branch_group(branch_text)
                branch.elements.append(branch_group)
                pos = end_pos + 1
            elif char in ' \t\n':
                pos += 1
            else:
                # Parse instruction
                match = self.INSTRUCTION_PATTERN.match(text, pos)
                if match:
                    instr = self._parse_instruction(match.group(1), match.group(2))
                    instr.node_id = self._next_node_id()
                    branch.elements.append(instr)
                    pos = match.end()
                else:
                    pos += 1
        
        return branch
    
    def _parse_branch_group(self, text: str) -> LadderBranchGroup:
        """Parse a branch group (parallel branches separated by commas)."""
        group = LadderBranchGroup()
        
        # Split by comma, but respect nested brackets
        branches_text = self._split_branches(text)
        
        for branch_text in branches_text:
            branch = self._parse_branch_content(branch_text.strip())
            group.branches.append(branch)
        
        return group
    
    def _split_branches(self, text: str) -> list[str]:
        """Split branch text by commas, respecting nested brackets and parentheses.
        
        Branch separators are commas at depth 0 (outside all brackets AND parentheses).
        Commas inside instruction operands like GSV(A,B,C) should not split.
        """
        branches = []
        current = []
        bracket_depth = 0
        paren_depth = 0
        
        for char in text:
            if char == '[':
                bracket_depth += 1
                current.append(char)
            elif char == ']':
                bracket_depth -= 1
                current.append(char)
            elif char == '(':
                paren_depth += 1
                current.append(char)
            elif char == ')':
                paren_depth -= 1
                current.append(char)
            elif char == ',' and bracket_depth == 0 and paren_depth == 0:
                branches.append(''.join(current))
                current = []
            else:
                current.append(char)
        
        if current:
            branches.append(''.join(current))
        
        return branches
    
    def _find_matching_bracket(self, text: str, start: int) -> int:
        """Find the matching closing bracket."""
        depth = 1
        pos = start + 1
        while pos < len(text) and depth > 0:
            if text[pos] == '[':
                depth += 1
            elif text[pos] == ']':
                depth -= 1
            pos += 1
        return pos - 1
    
    def _parse_instruction(self, name: str, operands_str: str) -> LadderInstruction:
        """Parse a single instruction."""
        # Split operands by comma, respecting nested structures
        operands = self._split_operands(operands_str)

        # Determine instruction type
        instr_type = self.INSTRUCTION_TYPES.get(
            name.upper(),
            InstructionType.AOI if name[0].isupper() else InstructionType.OTHER
        )

        # Built-in mnemonics are normalised to upper case (XIC, OTE, ...), but an
        # AOI's name is case-sensitive (e.g. "MotorCtl") and must match its
        # AddOnInstructionDefinition for the parameter-name map to resolve.
        display = name if instr_type == InstructionType.AOI else name.upper()

        return LadderInstruction(
            instruction=display,
            operands=operands,
            instruction_type=instr_type
        )
    
    def _split_operands(self, text: str) -> list[str]:
        """Split operands by comma, respecting nested parentheses."""
        operands = []
        current = []
        depth = 0
        
        for char in text:
            if char == '(':
                depth += 1
                current.append(char)
            elif char == ')':
                depth -= 1
                current.append(char)
            elif char == ',' and depth == 0:
                op = ''.join(current).strip()
                if op and op != '?':  # Skip placeholder operands
                    operands.append(op)
                current = []
            else:
                current.append(char)
        
        if current:
            op = ''.join(current).strip()
            if op and op != '?':
                operands.append(op)
        
        return operands


class DotGenerator:
    """
    Generates Graphviz DOT syntax from parsed ladder logic.
    
    Uses HTML-like labels for visual representation of ladder elements
    and rank constraints for proper branch alignment.
    
    Layout: Input conditions are left-justified, outputs are right-justified.
    Parallel branches are aligned vertically with rank=same constraints.
    """
    
    # Output instructions that should be right-justified
    OUTPUT_INSTRUCTIONS = {
        InstructionType.COIL,
        InstructionType.COIL_LATCH,
        InstructionType.COIL_UNLATCH,
        InstructionType.TIMER,
        InstructionType.COUNTER,
        InstructionType.RESET,
    }
    
    # Visual styles — authentic Studio 5000 ladder: black linework on a white
    # canvas, monospace identifiers, operand text in control-blue, instruction
    # blocks with a light-grey title bar. No pastel fills (the old "AI" look).
    _INK = '#14171B'        # linework + glyphs
    _OPERAND = '#0B4F9E'    # tag / operand text (Studio blue)
    _LABEL = '#5B636E'      # muted parameter labels
    _HEADER = '#EEF1F4'     # instruction title-bar fill

    STYLES = {
        InstructionType.CONTACT_NO: {
            'shape': 'none',
            'label_template': '''<
                <TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0" CELLPADDING="5" COLOR="#14171B">
                    <TR><TD PORT="c"><FONT COLOR="#14171B">─┤ ├─</FONT></TD></TR>
                    <TR><TD><FONT COLOR="#0B4F9E">{tag}</FONT></TD></TR>
                </TABLE>
            >''',
            'color': '#14171B',
        },
        InstructionType.CONTACT_NC: {
            'shape': 'none',
            'label_template': '''<
                <TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0" CELLPADDING="5" COLOR="#14171B">
                    <TR><TD PORT="c"><FONT COLOR="#14171B">─┤/├─</FONT></TD></TR>
                    <TR><TD><FONT COLOR="#0B4F9E">{tag}</FONT></TD></TR>
                </TABLE>
            >''',
            'color': '#14171B',
        },
        InstructionType.COIL: {
            'shape': 'none',
            'label_template': '''<
                <TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0" CELLPADDING="5" COLOR="#14171B">
                    <TR><TD PORT="c"><FONT COLOR="#14171B">─( )─</FONT></TD></TR>
                    <TR><TD><FONT COLOR="#0B4F9E">{tag}</FONT></TD></TR>
                </TABLE>
            >''',
            'color': '#14171B',
        },
        InstructionType.COIL_LATCH: {
            'shape': 'none',
            'label_template': '''<
                <TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0" CELLPADDING="5" COLOR="#14171B">
                    <TR><TD PORT="c"><FONT COLOR="#14171B">─(L)─</FONT></TD></TR>
                    <TR><TD><FONT COLOR="#0B4F9E">{tag}</FONT></TD></TR>
                </TABLE>
            >''',
            'color': '#14171B',
        },
        InstructionType.COIL_UNLATCH: {
            'shape': 'none',
            'label_template': '''<
                <TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0" CELLPADDING="5" COLOR="#14171B">
                    <TR><TD PORT="c"><FONT COLOR="#14171B">─(U)─</FONT></TD></TR>
                    <TR><TD><FONT COLOR="#0B4F9E">{tag}</FONT></TD></TR>
                </TABLE>
            >''',
            'color': '#14171B',
        },
        InstructionType.TIMER: {
            'shape': 'none',
            'label_template': '''<
                <TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0" CELLPADDING="5" COLOR="#14171B">
                    <TR><TD COLSPAN="2" BGCOLOR="#EEF1F4" PORT="c"><B>{instr}</B></TD></TR>
                    <TR><TD ALIGN="RIGHT"><FONT COLOR="#5B636E">Timer</FONT></TD><TD ALIGN="LEFT"><FONT COLOR="#0B4F9E">{tag}</FONT></TD></TR>
                    <TR><TD ALIGN="RIGHT"><FONT COLOR="#5B636E">Preset</FONT></TD><TD ALIGN="LEFT">{preset}</TD></TR>
                </TABLE>
            >''',
            'color': '#14171B',
        },
        InstructionType.COUNTER: {
            'shape': 'none',
            'label_template': '''<
                <TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0" CELLPADDING="5" COLOR="#14171B">
                    <TR><TD COLSPAN="2" BGCOLOR="#EEF1F4" PORT="c"><B>{instr}</B></TD></TR>
                    <TR><TD ALIGN="RIGHT"><FONT COLOR="#5B636E">Counter</FONT></TD><TD ALIGN="LEFT"><FONT COLOR="#0B4F9E">{tag}</FONT></TD></TR>
                    <TR><TD ALIGN="RIGHT"><FONT COLOR="#5B636E">Preset</FONT></TD><TD ALIGN="LEFT">{preset}</TD></TR>
                </TABLE>
            >''',
            'color': '#14171B',
        },
        InstructionType.COMPARE: {
            'shape': 'none',
            'label_template': '''<
                <TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0" CELLPADDING="5" COLOR="#14171B">
                    <TR><TD BGCOLOR="#EEF1F4" PORT="c"><B>{instr}</B></TD></TR>
                    <TR><TD>{operation}</TD></TR>
                </TABLE>
            >''',
            'color': '#14171B',
        },
        InstructionType.MATH: {
            'shape': 'none',
            'label_template': '''<
                <TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0" CELLPADDING="5" COLOR="#14171B">
                    <TR><TD BGCOLOR="#EEF1F4" PORT="c"><B>{instr}</B></TD></TR>
                    <TR><TD>{operation}</TD></TR>
                </TABLE>
            >''',
            'color': '#14171B',
        },
        InstructionType.MOVE: {
            'shape': 'none',
            'label_template': '''<
                <TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0" CELLPADDING="5" COLOR="#14171B">
                    <TR><TD BGCOLOR="#EEF1F4" PORT="c"><B>{instr}</B></TD></TR>
                    <TR><TD>{operation}</TD></TR>
                </TABLE>
            >''',
            'color': '#14171B',
        },
        InstructionType.MOTION: {
            'shape': 'none',
            'label_template': '''<
                <TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0" CELLPADDING="5" COLOR="#14171B">
                    <TR><TD BGCOLOR="#EEF1F4" PORT="c"><B>{instr}</B></TD></TR>
                    <TR><TD><FONT COLOR="#0B4F9E">{axis}</FONT></TD></TR>
                </TABLE>
            >''',
            'color': '#14171B',
        },
        InstructionType.FUNCTION: {
            'shape': 'none',
            'label_template': '''<
                <TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0" CELLPADDING="5" COLOR="#14171B">
                    <TR><TD BGCOLOR="#EEF1F4" PORT="c"><B>{instr}</B></TD></TR>
                    <TR><TD><FONT COLOR="#0B4F9E">{routine}</FONT></TD></TR>
                </TABLE>
            >''',
            'color': '#14171B',
        },
        InstructionType.AOI: {
            'shape': 'none',
            'label_template': '''<
                <TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0" CELLPADDING="5" COLOR="#14171B">
                    <TR><TD COLSPAN="2" BGCOLOR="#EEF1F4" PORT="c"><B>{instr}</B></TD></TR>
                    <TR><TD COLSPAN="2"><FONT COLOR="#0B4F9E">{aoi_tag}</FONT></TD></TR>
                    {param_rows}
                </TABLE>
            >''',
            'color': '#14171B',
        },
    }

    DEFAULT_STYLE = {
        'shape': 'none',
        'label_template': '''<
            <TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0" CELLPADDING="5" COLOR="#14171B">
                <TR><TD BGCOLOR="#EEF1F4" PORT="c"><B>{instr}</B></TD></TR>
                <TR><TD><FONT COLOR="#0B4F9E">{operands}</FONT></TD></TR>
            </TABLE>
        >''',
        'color': '#14171B',
    }
    
    def __init__(self, tag_descriptions: Optional[dict[str, str]] = None,
                 aoi_params: Optional[dict[str, list[str]]] = None):
        self._edges: list[tuple[str, str]] = []
        self._nodes: list[str] = []
        self._ranks: list[list[str]] = []
        self._subgraphs: list[str] = []
        self._input_nodes: list[str] = []   # Nodes for left side (inputs)
        self._output_nodes: list[str] = []  # Nodes for right side (outputs)
        self._exit_nodes: list[str] = []    # Terminal nodes (wire to right rail)
        self.tag_descriptions = tag_descriptions or {}
        # {AOI_NAME: [parameter names, in call-argument order]} - used to label
        # each AOI call argument with its parameter name (Studio 5000 style).
        self.aoi_params = aoi_params or {}
    
    def generate(self, rung: LadderRung) -> str:
        """Generate DOT syntax for a ladder rung."""
        self._edges = []
        self._nodes = []
        self._ranks = []
        self._subgraphs = []
        self._input_nodes = []
        self._output_nodes = []
        self._exit_nodes = []

        # Process the main branch - returns list of exit nodes
        last_nodes = self._process_branch(rung.main_branch, None)
        self._exit_nodes = last_nodes or []

        # Build DOT output
        return self._build_dot(rung)
    
    def _process_branch(self, branch: LadderBranch, entry_nodes: Optional[list[str]]) -> list[str]:
        """Process a branch and return exit node IDs.
        
        Processes elements in order, handling both instructions and nested branches.
        """
        current_nodes = entry_nodes
        
        for element in branch.elements:
            if isinstance(element, LadderInstruction):
                node_def = self._create_node(element)
                self._nodes.append(node_def)

                if element.instruction_type in self.OUTPUT_INSTRUCTIONS:
                    # Outputs (coils, latches, output timers) are terminal AND, when
                    # several appear in a row, electrically PARALLEL - ladder logic
                    # has no series coils. Wire each from the current inputs (or the
                    # left rail if there are none) but do NOT advance current_nodes,
                    # so consecutive outputs branch from the same point and stack
                    # vertically at the right rail instead of chaining horizontally.
                    self._output_nodes.append(element.node_id)
                    if current_nodes:
                        for current in current_nodes:
                            self._edges.append((current, element.node_id))
                    else:
                        self._input_nodes.append(element.node_id)
                    # current_nodes intentionally unchanged
                else:
                    if current_nodes is None:
                        # Start of rung (or branch connected to start) -> input.
                        self._input_nodes.append(element.node_id)
                    if current_nodes:
                        for current in current_nodes:
                            self._edges.append((current, element.node_id))
                    current_nodes = [element.node_id]

            elif isinstance(element, LadderBranchGroup):
                exit_nodes = []
                branch_nodes = []
                
                for sub_branch in element.branches:
                    sub_exits = self._process_branch(sub_branch, current_nodes)
                    exit_nodes.extend(sub_exits)
                    
                    # Collect first nodes of each branch for rank alignment
                    if sub_branch.elements:
                        first_elem = sub_branch.elements[0]
                        if isinstance(first_elem, LadderInstruction):
                            branch_nodes.append(first_elem.node_id)
                
                # Add rank constraint for parallel branches
                if len(branch_nodes) > 1:
                    self._ranks.append(branch_nodes)
                
                current_nodes = exit_nodes if exit_nodes else current_nodes
        
        return current_nodes if current_nodes is not None else []
    
    def _create_node(self, instr: LadderInstruction) -> str:
        """Create a DOT node definition for an instruction."""
        style = self.STYLES.get(instr.instruction_type, self.DEFAULT_STYLE)
        
        # Build label based on instruction type
        label = self._build_label(instr, style)
        
        # Add tooltip with full operand info
        tooltip = f"{instr.instruction}({', '.join(instr.operands)})" if instr.operands else instr.instruction
        tooltip = self._escape_html(tooltip).replace('"', '&quot;')
        
        return f'{instr.node_id} [shape=none, label={label}, tooltip="{tooltip}"];'
    
    def _build_label(self, instr: LadderInstruction, style: dict) -> str:
        """Build the HTML label for an instruction."""
        template = style['label_template']
        
        tag = instr.operands[0] if instr.operands else ""
        preset = instr.operands[1] if len(instr.operands) > 1 else "?"
        operands = ", ".join(instr.operands[:3])
        if len(instr.operands) > 3:
            operands += "..."
        axis = instr.operands[0] if instr.operands else ""
        routine = instr.operands[0] if instr.operands else ""
        # AOI: operand[0] is the AOI instance tag (shown in its own header row);
        # operand[1:] are the call arguments. When we know the AOI's parameter
        # names (recovered from the ACD), each argument is rendered on its own
        # row as "paramName = operand", the way Studio 5000 labels them. When the
        # names are unknown (e.g. a source-protected AOI) we fall back to one
        # bare operand per row - never fabricating names.
        aoi_tag = instr.operands[0] if instr.operands else ""
        param_rows = ""
        if instr.instruction_type == InstructionType.AOI:
            param_rows = self._build_aoi_param_rows(instr)
        
        # Build operation string for math/compare/move instructions
        operation = self._build_operation_string(instr)
        
        # Get description
        description = ""
        if tag and self.tag_descriptions:
            # Try exact match first
            if tag in self.tag_descriptions:
                description = self.tag_descriptions[tag]
            else:
                # Try base tag match (e.g. Tag[0] -> Tag)
                base_tag = tag.split('[')[0]
                if base_tag in self.tag_descriptions:
                    description = self.tag_descriptions[base_tag]
        
        # Format description row
        description_row = ""
        if description:
            # Truncate description if too long
            if len(description) > 40:
                description = description[:37] + "..."
            description = self._escape_html(description)
            # Tag description shown as a Studio-style green comment line.
            description_row = f'<TR><TD BORDER="0"><FONT COLOR="#0B7A45" POINT-SIZE="9"><I>{description}</I></FONT></TD></TR>'
            
            # Inject description row into template
            # Find the first <TR> and insert before it
            idx = template.find('<TR>')
            if idx != -1:
                template = template[:idx] + description_row + template[idx:]
        
        # Escape HTML special characters
        tag = self._escape_html(tag)
        preset = self._escape_html(str(preset))
        operands = self._escape_html(operands)
        axis = self._escape_html(axis)
        routine = self._escape_html(routine)
        aoi_tag = self._escape_html(aoi_tag)
        operation = self._escape_html(operation)
        # NOTE: param_rows is already fully-formed (and escaped) HTML rows built
        # by _build_aoi_param_rows; it must not be escaped/wrapped again.

        # Wrap long text with line breaks
        tag = self._wrap_text(tag, max_length=40)
        operands = self._wrap_text(operands, max_length=40)
        preset = self._wrap_text(preset, max_length=40)
        axis = self._wrap_text(axis, max_length=40)
        routine = self._wrap_text(routine, max_length=40)
        aoi_tag = self._wrap_text(aoi_tag, max_length=40)
        operation = self._wrap_text(operation, max_length=50)
        
        # Build instruction label with friendly name
        friendly_name = INSTRUCTION_FRIENDLY_NAMES.get(instr.instruction, '')
        if friendly_name:
            instr_label = f'{instr.instruction}<BR/><FONT POINT-SIZE="9"><I>{friendly_name}</I></FONT>'
        else:
            instr_label = instr.instruction
        
        label = template.format(
            instr=instr_label,
            tag=tag,
            preset=preset,
            operands=operands,
            axis=axis,
            routine=routine,
            aoi_tag=aoi_tag,
            param_rows=param_rows,
            operation=operation,
        )

        return label

    def _build_aoi_param_rows(self, instr: LadderInstruction) -> str:
        """Build the per-argument <TR> rows for an AOI call block.

        operands[0] is the AOI instance tag (rendered separately as the header).
        operands[1:] are the call arguments. When we know the AOI's parameter
        names, each row reads "paramName = operand"; otherwise each argument is
        shown on its own row as a bare operand (no fabricated names).
        """
        args = instr.operands[1:] if len(instr.operands) > 1 else []
        if not args:
            return ''
        param_names = self.aoi_params.get(instr.instruction, [])
        rows = []
        for i, operand in enumerate(args):
            op = self._wrap_text(self._escape_html(operand), max_length=40)
            if i < len(param_names) and param_names[i]:
                name = self._escape_html(param_names[i])
                rows.append(
                    f'<TR><TD ALIGN="RIGHT"><FONT COLOR="#5B636E">{name}</FONT></TD>'
                    f'<TD ALIGN="LEFT"><FONT COLOR="#0B4F9E">{op}</FONT></TD></TR>'
                )
            else:
                # Unknown parameter name - render the bare operand on its own row.
                rows.append(f'<TR><TD COLSPAN="2" ALIGN="LEFT">{op}</TD></TR>')
        return ''.join(rows)
    
    def _build_operation_string(self, instr: LadderInstruction) -> str:
        """Build a human-readable operation string for math/compare/move."""
        ops = instr.operands
        name = instr.instruction
        
        # Math operations: result = A op B
        if name == 'ADD' and len(ops) >= 3:
            return f"{ops[0]} + {ops[1]} → {ops[2]}"
        elif name == 'SUB' and len(ops) >= 3:
            return f"{ops[0]} - {ops[1]} → {ops[2]}"
        elif name == 'MUL' and len(ops) >= 3:
            return f"{ops[0]} × {ops[1]} → {ops[2]}"
        elif name == 'DIV' and len(ops) >= 3:
            return f"{ops[0]} ÷ {ops[1]} → {ops[2]}"
        elif name == 'CPT' and len(ops) >= 2:
            return f"{ops[0]} := {ops[1]}"
        elif name == 'SQR' and len(ops) >= 2:
            return f"√{ops[0]} → {ops[1]}"
        elif name == 'ABS' and len(ops) >= 2:
            return f"|{ops[0]}| → {ops[1]}"
        elif name == 'NEG' and len(ops) >= 2:
            return f"-{ops[0]} → {ops[1]}"
        
        # Compare operations
        elif name == 'EQU' and len(ops) >= 2:
            return f"{ops[0]} = {ops[1]}"
        elif name == 'NEQ' and len(ops) >= 2:
            return f"{ops[0]} ≠ {ops[1]}"
        elif name == 'LES' and len(ops) >= 2:
            return f"{ops[0]} < {ops[1]}"
        elif name == 'LEQ' and len(ops) >= 2:
            return f"{ops[0]} ≤ {ops[1]}"
        elif name == 'GRT' and len(ops) >= 2:
            return f"{ops[0]} > {ops[1]}"
        elif name == 'GEQ' and len(ops) >= 2:
            return f"{ops[0]} ≥ {ops[1]}"
        elif name == 'LIM' and len(ops) >= 3:
            return f"{ops[0]} ≤ {ops[1]} ≤ {ops[2]}"
        elif name == 'MEQ' and len(ops) >= 3:
            return f"({ops[0]} & {ops[1]}) = {ops[2]}"
        elif name == 'CMP' and len(ops) >= 1:
            return f"{ops[0]}"
        
        # Move operations
        elif name == 'MOV' and len(ops) >= 2:
            return f"{ops[0]} → {ops[1]}"
        elif name == 'COP' and len(ops) >= 3:
            return f"{ops[0]} → {ops[1]} [{ops[2]}]"
        elif name == 'FLL' and len(ops) >= 3:
            return f"Fill {ops[1]} with {ops[0]} [{ops[2]}]"
        elif name == 'CLR' and len(ops) >= 1:
            return f"Clear {ops[0]}"
        
        # Bit operations
        elif name == 'BTD' and len(ops) >= 5:
            return f"{ops[0]}.{ops[1]} → {ops[2]}.{ops[3]} [{ops[4]}]"
        
        # Default: just list operands
        return ", ".join(ops[:3]) + ("..." if len(ops) > 3 else "")
    
    def _escape_html(self, text: str) -> str:
        """Escape HTML special characters."""
        return (text
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;'))
    
    def _wrap_text(self, text: str, max_length: int = 40) -> str:
        """Wrap long text with <BR/> tags for display in Graphviz HTML labels."""
        if len(text) <= max_length:
            return text
        
        # Try to break at natural delimiters: commas, dots, brackets
        lines = []
        current_line = ""
        
        # Split by common separators while keeping them
        tokens = re.split(r'(\s*,\s*|\s*\.\s*|\[|\]|\(|\))', text)
        
        for token in tokens:
            if not token:
                continue
                
            # If adding this token would exceed max_length, start new line
            if len(current_line) + len(token) > max_length and current_line:
                lines.append(current_line.strip())
                current_line = token
            else:
                current_line += token
        
        # Add any remaining text
        if current_line:
            lines.append(current_line.strip())
        
        # If still too long after natural breaks, force break
        final_lines = []
        for line in lines:
            if len(line) <= max_length:
                final_lines.append(line)
            else:
                # Force break long lines without natural breaks
                for i in range(0, len(line), max_length):
                    final_lines.append(line[i:i+max_length])
        
        return '<BR/>'.join(final_lines) if final_lines else text
    
    # Left/right power-rail anchor node ids (reserved; real tags can't collide
    # because they are sanitised to start with 'n').
    _LEFT_RAIL = '__rail_L'
    _RIGHT_RAIL = '__rail_R'

    def _build_dot(self, rung: LadderRung) -> str:
        """Build the complete DOT graph.

        Every rung is framed by a left and a right power rail. Each branch's first
        element is wired from the left rail and each terminal/output element is
        wired to the right rail, so the flow line is continuous from border to
        border (the Studio 5000 convention). Wires carry no arrowheads.
        """
        lines = [
            'digraph ladder {',
            '    rankdir=LR;',
            '    splines="ortho";',
            '    nodesep=0.28;',
            '    ranksep=0.45;',
            '    bgcolor="white";',
            '    node [fontname="Consolas", fontsize=11];',
            '    edge [fontname="Consolas", fontsize=10, color="#5A636E", arrowhead=none, penwidth=1.1];',
            '',
        ]

        # Power rails — thin dark vertical bars at the left and right borders.
        lines.append('    // Power rails')
        lines.append(f'    {self._LEFT_RAIL} [shape=box, style=filled, fillcolor="#3A4149", '
                     f'color="#3A4149", width=0.07, height=0.5, label="", fixedsize=false];')
        lines.append(f'    {self._RIGHT_RAIL} [shape=box, style=filled, fillcolor="#3A4149", '
                     f'color="#3A4149", width=0.07, height=0.5, label="", fixedsize=false];')

        lines.append('')
        lines.append('    // Nodes')
        for node in self._nodes:
            lines.append(f'    {node}')

        lines.append('')
        lines.append('    // Edges')
        for src, dst in self._edges:
            lines.append(f'    {src} -> {dst};')

        # Wire branch starts from the left rail.
        lines.append('')
        lines.append('    // Left rail feeds every branch start')
        starts = self._input_nodes if self._input_nodes else []
        if not starts and self._exit_nodes:
            starts = list(self._exit_nodes)
        for n in dict.fromkeys(starts):
            lines.append(f'    {self._LEFT_RAIL} -> {n};')

        # Wire terminal/output elements to the right rail (right-justified).
        lines.append('')
        lines.append('    // Right rail terminates every output')
        terminals = self._output_nodes if self._output_nodes else list(self._exit_nodes)
        terminals = list(dict.fromkeys(terminals))
        for n in terminals:
            lines.append(f'    {n} -> {self._RIGHT_RAIL};')

        # Pin the rails to the far left / far right.
        lines.append('')
        lines.append(f'    {{ rank=source; {self._LEFT_RAIL}; }}')
        lines.append(f'    {{ rank=sink; {self._RIGHT_RAIL}; }}')

        # Right-justify destructive/output instructions: align every output on the
        # same (rightmost) rank against the right rail, the way Studio stacks
        # parallel coils. (Ladder logic has no series coils, so all outputs are
        # parallel siblings and share this rank.)
        right_justified = list(dict.fromkeys(self._output_nodes))
        if len(right_justified) > 1:
            lines.append('')
            lines.append('    // Right-justified outputs')
            lines.append(f'    {{ rank=same; {"; ".join(right_justified)}; }}')

        # Rank constraints for parallel branches.
        if self._ranks:
            lines.append('')
            lines.append('    // Rank constraints for parallel branches')
            for rank_nodes in self._ranks:
                nodes_str = '; '.join(rank_nodes)
                lines.append(f'    {{ rank=same; {nodes_str}; }}')

        lines.append('}')

        return '\n'.join(lines)


def convert_rung_to_dot(rung_text: str, rung_number: int = 0, comment: str = "", tag_descriptions: Optional[dict[str, str]] = None, aoi_params: Optional[dict[str, list[str]]] = None) -> str:
    """
    Convert a ladder logic rung to Graphviz DOT syntax.
    
    This is the main entry point for ladder logic visualization.
    
    Args:
        rung_text: The raw ladder logic text (e.g., "XIC(A) BST XIO(B) NXB OTE(C) BND")
        rung_number: The rung number for labeling
        comment: Optional rung comment
        tag_descriptions: Optional dictionary mapping tag names to descriptions
        
    Returns:
        Graphviz DOT syntax string ready for d3-graphviz rendering
        
    Example:
        >>> dot = convert_rung_to_dot("XIC(Start) XIO(Stop) OTE(Motor)")
        >>> print(dot)
        digraph ladder {
            ...
        }
    """
    parser = LadderParser()
    rung = parser.parse_rung(rung_text, rung_number, comment)

    generator = DotGenerator(tag_descriptions, aoi_params)
    return generator.generate(rung)


def convert_all_rungs_to_dot(rungs: list[tuple[str, int, str]], tag_descriptions: Optional[dict[str, str]] = None, aoi_params: Optional[dict[str, list[str]]] = None) -> dict[int, str]:
    """
    Convert multiple rungs to DOT syntax.

    Args:
        rungs: List of (rung_text, rung_number, comment) tuples
        tag_descriptions: Optional dictionary mapping tag names to descriptions

    Returns:
        Dictionary mapping rung numbers to DOT strings
    """
    result = {}
    for rung_text, rung_number, comment in rungs:
        result[rung_number] = convert_rung_to_dot(rung_text, rung_number, comment, tag_descriptions, aoi_params)
    return result


# ---------------------------------------------------------------------------
# Layout model (for the custom SVG ladder renderer)
#
# Instead of emitting Graphviz DOT and fighting an auto-layout engine for rail
# pinning, we serialize each rung's series/parallel tree to a small JSON model
# that a purpose-built SVG renderer lays out directly. The model is intentionally
# terse (single-letter keys) since one is embedded per rung in the HTML.
#
#   Rung   = { "s": Series, "out": [Element, ...] }   # input chain + output coils
#   Series = { "s": [ Item, ... ] }
#   Item   = { "e": Element } | { "p": [ Series, ... ] }   # element | parallel group
#   Element = {
#       "r": "contact"|"coil"|"block",
#       "g": "no"|"nc"|"ote"|"otl"|"otu",   # glyph (contact/coil only)
#       "tag": str, "desc": str,            # contact/coil label + green description
#       "head": str, "sub": str,            # block title + friendly subtitle
#       "rows": [ [ [text, cls, align], ... ], ... ],   # block body cells
#       "tip": str,                         # tooltip
#   }
# cls is one of "tag" (clickable, blue), "label" (muted), "plain".
# ---------------------------------------------------------------------------

class ModelGenerator:
    """Serializes a parsed LadderRung into the JSON layout model above."""

    # Instructions that act on the rung (destructive) and are right-justified
    # against the right rail, the way Studio 5000 places them. AOIs are call
    # blocks that drive their instance, so they belong on the right too.
    _OUTPUT_TYPES = {
        InstructionType.COIL, InstructionType.COIL_LATCH, InstructionType.COIL_UNLATCH,
        InstructionType.TIMER, InstructionType.COUNTER, InstructionType.RESET,
        InstructionType.AOI,
    }
    _CONTACT_GLYPH = {
        InstructionType.CONTACT_NO: 'no',
        InstructionType.CONTACT_NC: 'nc',
    }
    _COIL_GLYPH = {
        InstructionType.COIL: 'ote',
        InstructionType.COIL_LATCH: 'otl',
        InstructionType.COIL_UNLATCH: 'otu',
    }

    def __init__(self, tag_descriptions: Optional[dict[str, str]] = None,
                 aoi_params: Optional[dict[str, list[str]]] = None):
        self.tag_descriptions = tag_descriptions or {}
        self.aoi_params = aoi_params or {}

    def generate(self, rung: LadderRung) -> dict:
        input_items: list[dict] = []
        outputs: list[dict] = []
        for element in rung.main_branch.elements:
            if isinstance(element, LadderInstruction):
                if element.instruction.upper() == 'NOP':
                    continue                       # comment-only rung - just rails
                el = self._element(element)
                if element.instruction_type in self._OUTPUT_TYPES:
                    outputs.append(el)
                else:
                    input_items.append({'e': el})
            elif isinstance(element, LadderBranchGroup):
                input_items.append(self._group(element))
        return {'s': {'s': input_items}, 'out': outputs}

    def _branch(self, branch: LadderBranch) -> dict:
        items: list[dict] = []
        for element in branch.elements:
            if isinstance(element, LadderInstruction):
                if element.instruction.upper() == 'NOP':
                    continue
                items.append({'e': self._element(element)})
            elif isinstance(element, LadderBranchGroup):
                items.append(self._group(element))
        return {'s': items}

    def _group(self, group: LadderBranchGroup) -> dict:
        return {'p': [self._branch(b) for b in group.branches]}

    def _element(self, instr: LadderInstruction) -> dict:
        t = instr.instruction_type
        ops = instr.operands
        tip = f"{instr.instruction}({', '.join(ops)})" if ops else instr.instruction

        if t in self._CONTACT_GLYPH:
            tag = ops[0] if ops else ''
            return {'r': 'contact', 'g': self._CONTACT_GLYPH[t], 'tag': tag,
                    'desc': self._desc(tag), 'tip': tip}
        if t in self._COIL_GLYPH:
            tag = ops[0] if ops else ''
            return {'r': 'coil', 'g': self._COIL_GLYPH[t], 'tag': tag,
                    'desc': self._desc(tag), 'tip': tip}

        head = instr.instruction
        sub = INSTRUCTION_FRIENDLY_NAMES.get(head, '')
        rows: list[list[list[str]]] = []
        desc = ''
        if t in (InstructionType.TIMER, InstructionType.COUNTER):
            kind = 'Timer' if t == InstructionType.TIMER else 'Counter'
            tag = ops[0] if ops else ''
            preset = ops[1] if len(ops) > 1 else '?'
            rows = [[[kind, 'label', 'r'], [tag, 'tag', 'l']],
                    [['Preset', 'label', 'r'], [str(preset), 'plain', 'l']]]
            desc = self._desc(tag)
        elif t in (InstructionType.COMPARE, InstructionType.MATH, InstructionType.MOVE):
            rows = [[[self._operation(instr), 'plain', 'l']]]
        elif t == InstructionType.AOI:
            tag = ops[0] if ops else ''
            rows = [[[tag, 'tag', 'l']]]
            names = self.aoi_params.get(head, [])
            for i, operand in enumerate(ops[1:]):
                if i < len(names) and names[i]:
                    rows.append([[names[i], 'label', 'r'], [operand, 'tag', 'l']])
                else:
                    rows.append([[operand, 'plain', 'l']])
            desc = self._desc(tag)
        else:
            # Function / motion / one-shot / reset / other: one row per operand,
            # treating identifier-like operands as clickable tags.
            for operand in ops:
                cls = 'tag' if re.match(r'[A-Za-z_]', operand) else 'plain'
                rows.append([[operand, cls, 'l']])
            if ops:
                desc = self._desc(ops[0])

        return {'r': 'block', 'head': head, 'sub': sub, 'rows': rows,
                'desc': desc, 'tip': tip}

    def _desc(self, tag: str) -> str:
        if not tag or not self.tag_descriptions:
            return ''
        # Best-effort: exact operand -> operand without array subscript -> the
        # parent/base tag's description (so a UDT member with no description of its
        # own inherits its tag's, e.g. DR1_MY_001.PER_ILK -> DR1_MY_001).
        desc = (self.tag_descriptions.get(tag)
                or self.tag_descriptions.get(tag.split('[')[0])
                or self.tag_descriptions.get(tag.split('.')[0].split('[')[0], ''))
        if len(desc) > 64:
            desc = desc[:61] + '…'
        return desc

    def _operation(self, instr: LadderInstruction) -> str:
        ops = instr.operands
        name = instr.instruction
        rules = {
            'ADD': lambda: f"{ops[0]} + {ops[1]} → {ops[2]}" if len(ops) >= 3 else None,
            'SUB': lambda: f"{ops[0]} - {ops[1]} → {ops[2]}" if len(ops) >= 3 else None,
            'MUL': lambda: f"{ops[0]} × {ops[1]} → {ops[2]}" if len(ops) >= 3 else None,
            'DIV': lambda: f"{ops[0]} ÷ {ops[1]} → {ops[2]}" if len(ops) >= 3 else None,
            'CPT': lambda: f"{ops[0]} := {ops[1]}" if len(ops) >= 2 else None,
            'MOV': lambda: f"{ops[0]} → {ops[1]}" if len(ops) >= 2 else None,
            'COP': lambda: f"{ops[0]} → {ops[1]} [{ops[2]}]" if len(ops) >= 3 else None,
            'EQU': lambda: f"{ops[0]} = {ops[1]}" if len(ops) >= 2 else None,
            'NEQ': lambda: f"{ops[0]} ≠ {ops[1]}" if len(ops) >= 2 else None,
            'LES': lambda: f"{ops[0]} < {ops[1]}" if len(ops) >= 2 else None,
            'LEQ': lambda: f"{ops[0]} ≤ {ops[1]}" if len(ops) >= 2 else None,
            'GRT': lambda: f"{ops[0]} > {ops[1]}" if len(ops) >= 2 else None,
            'GEQ': lambda: f"{ops[0]} ≥ {ops[1]}" if len(ops) >= 2 else None,
            'LIM': lambda: f"{ops[0]} ≤ {ops[1]} ≤ {ops[2]}" if len(ops) >= 3 else None,
        }
        rule = rules.get(name)
        if rule:
            out = rule()
            if out:
                return out
        return ", ".join(ops[:3]) + ("..." if len(ops) > 3 else "")


def convert_rung_to_model(rung_text: str, rung_number: int = 0, comment: str = "",
                          tag_descriptions: Optional[dict[str, str]] = None,
                          aoi_params: Optional[dict[str, list[str]]] = None) -> dict:
    """Parse a rung and return the JSON layout model for the SVG renderer."""
    parser = LadderParser()
    rung = parser.parse_rung(rung_text, rung_number, comment)
    return ModelGenerator(tag_descriptions, aoi_params).generate(rung)
