"""
L5X Parser Module

High-performance XML parsing of Rockwell Automation L5X files using lxml.
Extracts controller metadata, data types, tags, programs, routines, and rungs.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Generator, Optional

from lxml import etree


@dataclass
class TagUsage:
    """Represents a tag's usage location in the project."""
    program: str
    routine: str
    rung_number: int
    usage_type: str  # 'read', 'write', 'destructive'
    instruction: str
    ref: str = ""  # Full reference as seen in logic, e.g., "Tag[86].Member"


@dataclass
class Tag:
    """Represents a PLC tag."""
    name: str
    data_type: str
    scope: str  # 'Controller' or program name
    description: str = ""
    external_access: str = ""
    tag_class: str = "Standard"
    constant: bool = False
    alias_for: str = ""  # Target for alias tags
    usages: list[TagUsage] = field(default_factory=list)
    dimension: int = 0  # Array dimension (0 for scalar)
    comments: dict[str, str] = field(default_factory=dict)  # Operand -> text for per-element docs


@dataclass
class Rung:
    """Represents a ladder logic rung."""
    number: int
    rung_type: str  # 'N' (normal), 'I' (insert), 'D' (delete)
    text: str
    comment: str = ""


@dataclass
class Routine:
    """Represents a PLC routine."""
    name: str
    routine_type: str  # 'RLL', 'ST', 'FBD', 'SFC'
    rungs: list[Rung] = field(default_factory=list)
    description: str = ""


@dataclass
class Program:
    """Represents a PLC program."""
    name: str
    main_routine: str
    routines: list[Routine] = field(default_factory=list)
    local_tags: list[Tag] = field(default_factory=list)
    disabled: bool = False
    description: str = ""
    comments: dict[str, str] = field(default_factory=dict)


@dataclass 
class DataTypeMember:
    """Represents a member of a user-defined data type."""
    name: str
    data_type: str
    dimension: int = 0
    description: str = ""
    hidden: bool = False
    external_access: str = "Read/Write"
    bit_number: Optional[int] = None
    target: Optional[str] = None


@dataclass
class UserDataType:
    """Represents a user-defined data type."""
    name: str
    family: str = "NoFamily"
    udt_class: str = "User"
    members: list[DataTypeMember] = field(default_factory=list)
    description: str = ""


@dataclass
class AOIParameter:
    """Represents a single Add-On Instruction parameter definition."""
    name: str
    usage: str = ""          # 'Input' | 'Output' | 'InOut'
    required: bool = False


@dataclass
class AddOnInstruction:
    """Represents an Add-On Instruction definition."""
    name: str
    revision: str = ""
    vendor: str = ""
    description: str = ""
    routines: list[Routine] = field(default_factory=list)
    # Ordered parameter definitions (document order). Used to label the
    # arguments of an AOI call block, the way Studio 5000 does.
    parameters: list[AOIParameter] = field(default_factory=list)


@dataclass
class ModulePort:
    """Represents a port on a module."""
    port_id: str
    address: str  # IP address or slot number
    port_type: str  # Ethernet, ICP, PointIO, etc.
    upstream: bool = False


@dataclass
class IOPoint:
    """Represents an individual I/O point on a module."""
    operand: str  # e.g., ".0", ".1", ".Data.0", etc.
    point_type: str  # 'Input' or 'Output'
    description: str = ""
    module_name: str = ""  # Parent module name
    tag_reference: str = ""  # Full tag reference (e.g., "Module:I.Data.0")
    is_used: bool = False  # Whether this point is used in logic
    mapped_tag: str = ""  # Tag that this point is mapped to (if any)

    @property
    def point_number(self) -> int:
        """Extract the numeric point number from operand string."""
        try:
            # Handle various formats: ".0", ".Data.0", ".Pt[0]"
            parts = self.operand.replace('[', '.').replace(']', '')
            nums = [p for p in parts.split('.') if p.isdigit()]
            return int(nums[-1]) if nums else -1
        except (ValueError, AttributeError):
            return -1


# Catalog of known I/O module point counts
# Format: catalog_pattern -> (input_count, output_count, data_format)
# data_format:
#   'data' = standard digital (.XX format)
#   'safety' = safety I/O (.PtXXData format)
#   'channel' = analog (.ChXData format)
IO_MODULE_CATALOG = {
    # ============================================================
    # 1756 ControlLogix Digital I/O
    # ============================================================
    '1756-IA16': (16, 0, 'data'),  # 16-pt 120VAC input
    '1756-IA16I': (16, 0, 'data'),  # 16-pt 120VAC input isolated
    '1756-IA32': (32, 0, 'data'),  # 32-pt 120VAC input
    '1756-IB16': (16, 0, 'data'),  # 16-pt 24VDC input
    '1756-IB16D': (16, 0, 'data'),  # 16-pt 24VDC input diagnostic
    '1756-IB16I': (16, 0, 'data'),  # 16-pt 24VDC input isolated
    '1756-IB16IF': (16, 0, 'data'),  # 16-pt 24VDC input isolated fast
    '1756-IB32': (32, 0, 'data'),  # 32-pt 24VDC input
    '1756-IC16': (16, 0, 'data'),  # 16-pt 24VDC input conformal
    '1756-IG16': (16, 0, 'data'),  # 16-pt 24VDC input group isolated
    '1756-IH16I': (16, 0, 'data'),  # 16-pt 125VDC input isolated
    '1756-IM16I': (16, 0, 'data'),  # 16-pt 240VAC/125VDC input isolated
    '1756-IN16': (16, 0, 'data'),  # 16-pt 24VAC/DC input
    '1756-IV16': (16, 0, 'data'),  # 16-pt contact/TTL input
    '1756-IV32': (32, 0, 'data'),  # 32-pt contact/TTL input
    '1756-OA16': (0, 16, 'data'),  # 16-pt 120/240VAC output
    '1756-OA16I': (0, 16, 'data'),  # 16-pt 120/240VAC output isolated
    '1756-OA8': (0, 8, 'data'),  # 8-pt 120/240VAC output
    '1756-OA8D': (0, 8, 'data'),  # 8-pt 120/240VAC output diagnostic
    '1756-OA8E': (0, 8, 'data'),  # 8-pt 120/240VAC output e-fused
    '1756-OB16D': (0, 16, 'data'),  # 16-pt 24VDC output diagnostic
    '1756-OB16E': (0, 16, 'data'),  # 16-pt 24VDC output e-fused
    '1756-OB16I': (0, 16, 'data'),  # 16-pt 24VDC output isolated
    '1756-OB16IS': (0, 16, 'data'),  # 16-pt 24VDC output isolated source
    '1756-OB32': (0, 32, 'data'),  # 32-pt 24VDC output
    '1756-OC8': (0, 8, 'data'),  # 8-pt 24VDC output conformal
    '1756-OG16': (0, 16, 'data'),  # 16-pt 24VDC output group isolated
    '1756-OH8I': (0, 8, 'data'),  # 8-pt 125VDC output isolated
    '1756-ON8': (0, 8, 'data'),  # 8-pt 24VAC/DC output
    '1756-OV16E': (0, 16, 'data'),  # 16-pt contact output e-fused
    '1756-OV32E': (0, 32, 'data'),  # 32-pt contact output e-fused
    '1756-OW16I': (0, 16, 'data'),  # 16-pt relay output isolated
    '1756-OX8I': (0, 8, 'data'),  # 8-pt relay output isolated
    # ============================================================
    # 1756 ControlLogix Analog I/O
    # ============================================================
    '1756-IF16': (16, 0, 'channel'),  # 16-ch analog input
    '1756-IF16H': (16, 0, 'channel'),  # 16-ch analog input HART
    '1756-IF16IH': (16, 0, 'channel'),  # 16-ch analog input isolated HART
    '1756-IF4FXOF2F': (4, 2, 'channel'),  # 4-ch AI + 2-ch AO fast
    '1756-IF6CIS': (6, 0, 'channel'),  # 6-ch analog current input isolated
    '1756-IF6I': (6, 0, 'channel'),  # 6-ch analog input isolated
    '1756-IF8': (8, 0, 'channel'),  # 8-ch analog input
    '1756-IF8H': (8, 0, 'channel'),  # 8-ch analog input HART
    '1756-IF8I': (8, 0, 'channel'),  # 8-ch analog input isolated
    '1756-IF8IH': (8, 0, 'channel'),  # 8-ch analog input isolated HART
    '1756-IR6I': (6, 0, 'channel'),  # 6-ch RTD input isolated
    '1756-IR12': (12, 0, 'channel'),  # 12-ch RTD input
    '1756-IT6I': (6, 0, 'channel'),  # 6-ch thermocouple input isolated
    '1756-IT6I2': (6, 0, 'channel'),  # 6-ch thermocouple input isolated v2
    '1756-OF4': (0, 4, 'channel'),  # 4-ch analog output
    '1756-OF6CI': (0, 6, 'channel'),  # 6-ch analog current output isolated
    '1756-OF6VI': (0, 6, 'channel'),  # 6-ch analog voltage output isolated
    '1756-OF8': (0, 8, 'channel'),  # 8-ch analog output
    '1756-OF8H': (0, 8, 'channel'),  # 8-ch analog output HART
    '1756-OF8I': (0, 8, 'channel'),  # 8-ch analog output isolated
    # ============================================================
    # 1756 ControlLogix Safety I/O
    # ============================================================
    '1756-IB16ISOE': (16, 0, 'safety'),  # 16-pt safety input
    '1756-OB16ISOE': (0, 16, 'safety'),  # 16-pt safety output
    # ============================================================
    # 1756 ControlLogix Specialty I/O
    # ============================================================
    '1756-HSC': (4, 0, 'channel'),  # High-speed counter
    '1756-HYD02': (2, 2, 'channel'),  # Hydraulic servo
    '1756-LSC8XIB8I': (8, 8, 'data'),  # Limit switch + digital
    '1756-LSS': (2, 0, 'channel'),  # LVDT/RVDT input
    '1756-MO2AE': (0, 2, 'channel'),  # Dual-axis motion
    '1756-MO4AR': (0, 4, 'channel'),  # 4-axis motion
    '1756-MO8SE': (0, 8, 'channel'),  # 8-axis motion (SERCOS)
    # ============================================================
    # 1734 Point I/O Digital
    # ============================================================
    '1734-IB2': (2, 0, 'data'),  # 2-point DC input
    '1734-IB4': (4, 0, 'data'),  # 4-point DC input
    '1734-IB4D': (4, 0, 'data'),  # 4-point DC input diagnostic
    '1734-IB8': (8, 0, 'data'),  # 8-point DC input
    '1734-IB8S': (8, 0, 'safety'),  # 8-point safety input
    '1734-IB16': (16, 0, 'data'),  # 16-point DC input
    '1734-IA2': (2, 0, 'data'),  # 2-point AC input
    '1734-IA4': (4, 0, 'data'),  # 4-point AC input
    '1734-IA8': (8, 0, 'data'),  # 8-point AC input
    '1734-IJ2': (2, 0, 'data'),  # 2-point sourcing input
    '1734-IK': (2, 0, 'data'),  # 2-point contact input
    '1734-IM2': (2, 0, 'data'),  # 2-point AC/DC input
    '1734-IM4': (4, 0, 'data'),  # 4-point AC/DC input
    '1734-IV4': (4, 0, 'data'),  # 4-point NAMUR input
    '1734-IV8': (8, 0, 'data'),  # 8-point NAMUR input
    '1734-OB2': (0, 2, 'data'),  # 2-point DC output
    '1734-OB2E': (0, 2, 'data'),  # 2-point DC output e-fused
    '1734-OB2EP': (0, 2, 'data'),  # 2-point DC output e-fused protected
    '1734-OB4': (0, 4, 'data'),  # 4-point DC output
    '1734-OB4E': (0, 4, 'data'),  # 4-point DC output e-fused
    '1734-OB8': (0, 8, 'data'),  # 8-point DC output
    '1734-OB8E': (0, 8, 'data'),  # 8-point DC output e-fused
    '1734-OB8S': (0, 8, 'safety'),  # 8-point safety output
    '1734-OB16': (0, 16, 'data'),  # 16-point DC output
    '1734-OB16E': (0, 16, 'data'),  # 16-point DC output e-fused
    '1734-OA2': (0, 2, 'data'),  # 2-point AC output
    '1734-OA4': (0, 4, 'data'),  # 4-point AC output
    '1734-OJ2': (0, 2, 'data'),  # 2-point sinking output
    '1734-OW2': (0, 2, 'data'),  # 2-point relay output
    '1734-OW4': (0, 4, 'data'),  # 4-point relay output
    '1734-OX2': (0, 2, 'data'),  # 2-point relay output isolated
    # 1734 Point I/O Safety
    '1734-IB4S': (4, 0, 'safety'),  # 4-point safety input
    '1734-OB4S': (0, 4, 'safety'),  # 4-point safety output
    '1734-IE4S': (4, 0, 'safety'),  # 4-ch safety analog input
    '1734-OE4S': (0, 4, 'safety'),  # 4-ch safety analog output
    # 1734 Point I/O Analog
    '1734-IE2C': (2, 0, 'channel'),  # 2-ch analog current input
    '1734-IE2V': (2, 0, 'channel'),  # 2-ch analog voltage input
    '1734-IE4C': (4, 0, 'channel'),  # 4-ch analog current input
    '1734-IE4V': (4, 0, 'channel'),  # 4-ch analog voltage input
    '1734-IE8C': (8, 0, 'channel'),  # 8-ch analog input
    '1734-OE2C': (0, 2, 'channel'),  # 2-ch analog current output
    '1734-OE2V': (0, 2, 'channel'),  # 2-ch analog voltage output
    '1734-OE4C': (0, 4, 'channel'),  # 4-ch analog output
    '1734-IR2': (2, 0, 'channel'),  # 2-ch RTD input
    '1734-IR4': (4, 0, 'channel'),  # 4-ch RTD input
    '1734-IR8': (8, 0, 'channel'),  # 8-ch RTD input
    '1734-IT2I': (2, 0, 'channel'),  # 2-ch thermocouple
    '1734-IT4': (4, 0, 'channel'),  # 4-ch thermocouple
    # ============================================================
    # 1769 Compact I/O (CompactLogix local I/O)
    # ============================================================
    '1769-IA8I': (8, 0, 'data'),  # 8-pt 120VAC input isolated
    '1769-IA16': (16, 0, 'data'),  # 16-pt 120VAC input
    '1769-IG16': (16, 0, 'data'),  # 16-pt 24VDC input group isolated
    '1769-IQ6XOW4': (6, 4, 'data'),  # 6-pt input + 4-pt relay output
    '1769-IQ16': (16, 0, 'data'),  # 16-pt 24VDC input
    '1769-IQ16F': (16, 0, 'data'),  # 16-pt 24VDC input fast
    '1769-IQ32': (32, 0, 'data'),  # 32-pt 24VDC input
    '1769-IQ32T': (32, 0, 'data'),  # 32-pt 24VDC input fast
    '1769-IM12': (12, 0, 'data'),  # 12-pt 240VAC/DC input
    '1769-OA8': (0, 8, 'data'),  # 8-pt 120/240VAC output
    '1769-OA16': (0, 16, 'data'),  # 16-pt 120/240VAC output
    '1769-OB8': (0, 8, 'data'),  # 8-pt 24VDC output
    '1769-OB16': (0, 16, 'data'),  # 16-pt 24VDC output
    '1769-OB16P': (0, 16, 'data'),  # 16-pt 24VDC output protected
    '1769-OB32': (0, 32, 'data'),  # 32-pt 24VDC output
    '1769-OB32T': (0, 32, 'data'),  # 32-pt 24VDC output fast
    '1769-OG16': (0, 16, 'data'),  # 16-pt 24VDC output group isolated
    '1769-OV16': (0, 16, 'data'),  # 16-pt relay output
    '1769-OV32T': (0, 32, 'data'),  # 32-pt relay output fast
    '1769-OW8': (0, 8, 'data'),  # 8-pt relay output
    '1769-OW8I': (0, 8, 'data'),  # 8-pt relay output isolated
    '1769-OW16': (0, 16, 'data'),  # 16-pt relay output
    # 1769 Compact I/O Analog
    '1769-IF4': (4, 0, 'channel'),  # 4-ch analog input
    '1769-IF4I': (4, 0, 'channel'),  # 4-ch analog input isolated
    '1769-IF4XOF2': (4, 2, 'channel'),  # 4-ch AI + 2-ch AO combo
    '1769-IF4XOF2F': (4, 2, 'channel'),  # 4-ch AI + 2-ch AO combo fast
    '1769-IF8': (8, 0, 'channel'),  # 8-ch analog input
    '1769-IF16C': (16, 0, 'channel'),  # 16-ch analog current input
    '1769-IF16V': (16, 0, 'channel'),  # 16-ch analog voltage input
    '1769-IR6': (6, 0, 'channel'),  # 6-ch RTD input
    '1769-IT6': (6, 0, 'channel'),  # 6-ch thermocouple input
    '1769-OF2': (0, 2, 'channel'),  # 2-ch analog output
    '1769-OF4': (0, 4, 'channel'),  # 4-ch analog output
    '1769-OF4CI': (0, 4, 'channel'),  # 4-ch analog current output isolated
    '1769-OF4VI': (0, 4, 'channel'),  # 4-ch analog voltage output isolated
    '1769-OF8C': (0, 8, 'channel'),  # 8-ch analog current output
    '1769-OF8V': (0, 8, 'channel'),  # 8-ch analog voltage output
    # 1769 Compact I/O Specialty
    '1769-HSC': (4, 0, 'channel'),  # High-speed counter
    '1769-ASCII': (0, 0, 'data'),  # ASCII serial module (no I/O points)
    '1769-SM1': (1, 1, 'channel'),  # Servo drive interface
    '1769-SM2': (2, 2, 'channel'),  # Dual servo drive interface
    # ============================================================
    # 5069 Compact 5000 I/O (CompactLogix 5380/5480)
    # ============================================================
    '5069-IA8': (8, 0, 'data'),  # 8-pt AC input
    '5069-IA16': (16, 0, 'data'),  # 16-pt AC input
    '5069-IB6F-3': (6, 0, 'data'),  # 6-pt DC input fast 3-wire
    '5069-IB8': (8, 0, 'data'),  # 8-pt DC input
    '5069-IB16': (16, 0, 'data'),  # 16-pt DC input
    '5069-IB16F': (16, 0, 'data'),  # 16-pt DC input fast
    '5069-IB16F-3': (16, 0, 'data'),  # 16-pt DC input fast 3-wire
    '5069-IY4': (4, 0, 'data'),  # 4-pt isolated DC input
    '5069-OA8': (0, 8, 'data'),  # 8-pt AC output
    '5069-OA16': (0, 16, 'data'),  # 16-pt AC output
    '5069-OB8': (0, 8, 'data'),  # 8-pt DC output
    '5069-OB16': (0, 16, 'data'),  # 16-pt DC output
    '5069-OB16F-3': (0, 16, 'data'),  # 16-pt DC output fast 3-wire
    '5069-OBV8S': (0, 8, 'safety'),  # 8-pt safety output
    '5069-OW4I': (0, 4, 'data'),  # 4-pt relay output isolated
    '5069-OX4I': (0, 4, 'data'),  # 4-pt relay output isolated N.C.
    '5069-OY4': (0, 4, 'data'),  # 4-pt isolated DC output
    # 5069 Compact 5000 Analog
    '5069-IF4': (4, 0, 'channel'),  # 4-ch analog input
    '5069-IF4H': (4, 0, 'channel'),  # 4-ch analog input HART
    '5069-IF4XOF4': (4, 4, 'channel'),  # 4-ch AI + 4-ch AO combo
    '5069-IF8': (8, 0, 'channel'),  # 8-ch analog input
    '5069-IF8H': (8, 0, 'channel'),  # 8-ch analog input HART
    '5069-IF16H': (16, 0, 'channel'),  # 16-ch analog input HART
    '5069-IR6-HART': (6, 0, 'channel'),  # 6-ch RTD input HART
    '5069-IT6': (6, 0, 'channel'),  # 6-ch thermocouple input
    '5069-OF4': (0, 4, 'channel'),  # 4-ch analog output
    '5069-OF4H': (0, 4, 'channel'),  # 4-ch analog output HART
    '5069-OF8': (0, 8, 'channel'),  # 8-ch analog output
    '5069-OF8H': (0, 8, 'channel'),  # 8-ch analog output HART
    # 5069 Compact 5000 Safety
    '5069-IB8S': (8, 0, 'safety'),  # 8-pt safety input
    '5069-IB16S': (16, 0, 'safety'),  # 16-pt safety input
    '5069-OB8S': (0, 8, 'safety'),  # 8-pt safety output
    '5069-OB16S': (0, 16, 'safety'),  # 16-pt safety output
    # ============================================================
    # 1794 FLEX I/O
    # ============================================================
    '1794-IB8': (8, 0, 'data'),  # 8-pt DC input
    '1794-IB16': (16, 0, 'data'),  # 16-pt DC input
    '1794-IB32': (32, 0, 'data'),  # 32-pt DC input
    '1794-IB10XOB6': (10, 6, 'data'),  # 10-pt input + 6-pt output combo
    '1794-IB16XOB16': (16, 16, 'data'),  # 16-pt input + 16-pt output combo
    '1794-IA8': (8, 0, 'data'),  # 8-pt AC input
    '1794-IA16': (16, 0, 'data'),  # 16-pt AC input
    '1794-IM8': (8, 0, 'data'),  # 8-pt AC/DC input isolated
    '1794-IV16': (16, 0, 'data'),  # 16-pt DC input isolated
    '1794-IV32': (32, 0, 'data'),  # 32-pt DC input isolated
    '1794-IRT8': (8, 0, 'channel'),  # 8-ch RTD input
    '1794-IJ2': (2, 0, 'data'),  # 2-pt sourcing input isolated
    '1794-OB8': (0, 8, 'data'),  # 8-pt DC output
    '1794-OB8EP': (0, 8, 'data'),  # 8-pt DC output e-fused protected
    '1794-OB16': (0, 16, 'data'),  # 16-pt DC output
    '1794-OB16P': (0, 16, 'data'),  # 16-pt DC output protected
    '1794-OB32': (0, 32, 'data'),  # 32-pt DC output
    '1794-OB32P': (0, 32, 'data'),  # 32-pt DC output protected
    '1794-OA8': (0, 8, 'data'),  # 8-pt AC output
    '1794-OA16': (0, 16, 'data'),  # 16-pt AC output
    '1794-OW8': (0, 8, 'data'),  # 8-pt relay output
    '1794-OV16': (0, 16, 'data'),  # 16-pt relay output
    '1794-OV32': (0, 32, 'data'),  # 32-pt relay output
    # 1794 FLEX I/O Analog
    '1794-IE4XOE2': (4, 2, 'channel'),  # 4-ch AI + 2-ch AO combo
    '1794-IE8': (8, 0, 'channel'),  # 8-ch analog input
    '1794-IE8H': (8, 0, 'channel'),  # 8-ch analog input HART
    '1794-IE8XOE4': (8, 4, 'channel'),  # 8-ch AI + 4-ch AO combo
    '1794-IE12': (12, 0, 'channel'),  # 12-ch analog input
    '1794-IF2XOF2I': (2, 2, 'channel'),  # 2-ch AI + 2-ch AO isolated
    '1794-IF4I': (4, 0, 'channel'),  # 4-ch analog input isolated
    '1794-IF8IH': (8, 0, 'channel'),  # 8-ch analog input isolated HART
    '1794-IT8': (8, 0, 'channel'),  # 8-ch thermocouple input
    '1794-OE4': (0, 4, 'channel'),  # 4-ch analog output
    '1794-OE8H': (0, 8, 'channel'),  # 8-ch analog output HART
    '1794-OE12': (0, 12, 'channel'),  # 12-ch analog output
    # ============================================================
    # 1746 SLC 500 I/O (legacy, but still in use)
    # ============================================================
    '1746-IA8': (8, 0, 'data'),  # 8-pt AC input
    '1746-IA16': (16, 0, 'data'),  # 16-pt AC input
    '1746-IB8': (8, 0, 'data'),  # 8-pt DC input
    '1746-IB16': (16, 0, 'data'),  # 16-pt DC input
    '1746-IB32': (32, 0, 'data'),  # 32-pt DC input
    '1746-IV8': (8, 0, 'data'),  # 8-pt DC input isolated
    '1746-IV16': (16, 0, 'data'),  # 16-pt DC input isolated
    '1746-IV32': (32, 0, 'data'),  # 32-pt DC input isolated
    '1746-IM4': (4, 0, 'data'),  # 4-pt AC/DC input
    '1746-IM8': (8, 0, 'data'),  # 8-pt AC/DC input
    '1746-IM16': (16, 0, 'data'),  # 16-pt AC/DC input
    '1746-IN16': (16, 0, 'data'),  # 16-pt TTL/contact input
    '1746-OA8': (0, 8, 'data'),  # 8-pt AC output
    '1746-OA16': (0, 16, 'data'),  # 16-pt AC output
    '1746-OB8': (0, 8, 'data'),  # 8-pt DC output
    '1746-OB16': (0, 16, 'data'),  # 16-pt DC output
    '1746-OB16E': (0, 16, 'data'),  # 16-pt DC output e-fused
    '1746-OB32': (0, 32, 'data'),  # 32-pt DC output
    '1746-OB32E': (0, 32, 'data'),  # 32-pt DC output e-fused
    '1746-OV8': (0, 8, 'data'),  # 8-pt DC output isolated
    '1746-OV16': (0, 16, 'data'),  # 16-pt DC output isolated
    '1746-OV32': (0, 32, 'data'),  # 32-pt DC output isolated
    '1746-OW4': (0, 4, 'data'),  # 4-pt relay output
    '1746-OW8': (0, 8, 'data'),  # 8-pt relay output
    '1746-OW16': (0, 16, 'data'),  # 16-pt relay output
    '1746-OX8': (0, 8, 'data'),  # 8-pt relay output isolated
    # 1746 SLC 500 Analog
    '1746-NI4': (4, 0, 'channel'),  # 4-ch analog input
    '1746-NI8': (8, 0, 'channel'),  # 8-ch analog input
    '1746-NI16I': (16, 0, 'channel'),  # 16-ch analog input isolated
    '1746-NIO4I': (2, 2, 'channel'),  # 2-ch AI + 2-ch AO isolated
    '1746-NIO4V': (2, 2, 'channel'),  # 2-ch AI + 2-ch AO voltage
    '1746-NO4I': (0, 4, 'channel'),  # 4-ch analog output isolated
    '1746-NO4V': (0, 4, 'channel'),  # 4-ch analog output voltage
    '1746-NO8I': (0, 8, 'channel'),  # 8-ch analog output isolated
    '1746-NR4': (4, 0, 'channel'),  # 4-ch RTD input
    '1746-NR8': (8, 0, 'channel'),  # 8-ch RTD input
    '1746-NT4': (4, 0, 'channel'),  # 4-ch thermocouple input
    '1746-NT8': (8, 0, 'channel'),  # 8-ch thermocouple input
}


def get_module_io_spec(catalog_number: str) -> tuple:
    """
    Get I/O specification for a module based on catalog number.

    Returns:
        (input_count, output_count, data_format) or (0, 0, None)
    """
    # Strip version suffix (e.g., /C, /B) and normalize
    base_catalog = catalog_number.split('/')[0].upper()

    # Try exact match first
    if base_catalog in IO_MODULE_CATALOG:
        return IO_MODULE_CATALOG[base_catalog]

    # Try prefix matching for variations
    for pattern, spec in IO_MODULE_CATALOG.items():
        if base_catalog.startswith(pattern):
            return spec

    return (0, 0, None)


@dataclass
class Module:
    """Represents an I/O module."""
    name: str
    catalog_number: str
    vendor: str
    slot: str = ""
    description: str = ""
    parent_module: str = ""
    parent_port: str = ""
    ports: list[ModulePort] = field(default_factory=list)
    io_points: list[IOPoint] = field(default_factory=list)


@dataclass
class Controller:
    """Represents the entire PLC project."""
    name: str
    processor_type: str
    major_rev: int
    minor_rev: int
    export_date: str = ""
    software_revision: str = ""
    description: str = ""
    
    # Network properties
    comm_path: str = ""  # Communication path to controller
    ethernet_mode: str = ""  # A1/A2: Dual-IP, etc.
    
    data_types: list[UserDataType] = field(default_factory=list)
    add_on_instructions: list[AddOnInstruction] = field(default_factory=list)
    modules: list[Module] = field(default_factory=list)
    controller_tags: list[Tag] = field(default_factory=list)
    programs: list[Program] = field(default_factory=list)
    comments: dict[str, str] = field(default_factory=dict)


class L5XParser:
    """
    High-performance L5X file parser using lxml.
    
    Parses Rockwell Automation L5X export files and extracts:
    - Controller metadata
    - User-defined data types
    - Add-On Instructions
    - I/O modules
    - Controller and program-scoped tags
    - Programs, routines, and rungs with ladder logic
    """
    
    # Instructions that write to operands (destructive operations)
    DESTRUCTIVE_INSTRUCTIONS = {
        'OTE', 'OTL', 'OTU', 'RES', 'MOV', 'MVM', 'CLR', 
        'CTU', 'CTD', 'TON', 'TOF', 'RTO', 'TON', 'TOF',
        'ADD', 'SUB', 'MUL', 'DIV', 'CPT', 'COP', 'FLL',
        'FSC', 'FAL', 'FBC', 'DDT', 'PID', 'MSG', 'GSV', 'SSV',
        'JSR', 'SBR', 'RET', 'FOR', 'NXT', 'BRK',
        'MSO', 'MSF', 'MAH', 'MAM', 'MAJ', 'MAS', 'MAFR', 'MAPC', 'MATC',
    }
    
    # Instructions that read operands
    READ_INSTRUCTIONS = {
        'XIC', 'XIO', 'ONS', 'OSR', 'OSF',
        'EQU', 'NEQ', 'LES', 'LEQ', 'GRT', 'GEQ', 'MEQ', 'LIM',
        'CMP', 'SQO', 'SQC', 'SQL',
    }
    
    def __init__(self, file_path: str | Path):
        """Initialize parser with L5X file path."""
        self.file_path = Path(file_path)
        self._tree: Optional[etree._ElementTree] = None
        self._root: Optional[etree._Element] = None
        self._nsmap: dict = {}
        
    def parse(self) -> Controller:
        """Parse the L5X file and return a Controller object."""
        # Use iterparse for memory efficiency with large files
        self._tree = etree.parse(str(self.file_path))
        self._root = self._tree.getroot()
        
        # Extract controller element
        controller_elem = self._root.find('.//Controller')
        if controller_elem is None:
            raise ValueError(f"No Controller element found in {self.file_path}")
        
        # Build controller object
        controller = Controller(
            name=controller_elem.get('Name', ''),
            processor_type=controller_elem.get('ProcessorType', ''),
            major_rev=int(controller_elem.get('MajorRev', 0)),
            minor_rev=int(controller_elem.get('MinorRev', 0)),
            export_date=self._root.get('ExportDate', ''),
            software_revision=self._root.get('SoftwareRevision', ''),
            description=self._get_description(controller_elem),
            comm_path=controller_elem.get('CommPath', ''),
            ethernet_mode=controller_elem.get('EtherNetIPMode', ''),
        )
        
        # Parse all sections
        controller.data_types = list(self._parse_data_types(controller_elem))
        controller.add_on_instructions = list(self._parse_aois(controller_elem))
        controller.modules = list(self._parse_modules(controller_elem))
        controller.controller_tags = list(self._parse_tags(controller_elem, 'Controller'))
        controller.programs = list(self._parse_programs(controller_elem))
        controller.comments = self._parse_comments(controller_elem)
        
        return controller
    
    @staticmethod
    def _element_text(elem: Optional[etree._Element]) -> str:
        """Return an element's documentation text.

        Studio 5000 exports documentation in two shapes depending on whether
        multi-language documentation is enabled in the project:

            <Description><![CDATA[plain text]]></Description>              (single-language)
            <Description><LocalizedDescription Lang="en-US"><![CDATA[..]]>  (multi-language)
                </LocalizedDescription></Description>

        The same applies to <Comment> / <LocalizedComment>. We accept either:
        direct text first, then fall back to the first non-empty localized child
        (preferring en-US when several languages are present).
        """
        if elem is None:
            return ""
        if elem.text and elem.text.strip():
            return elem.text.strip()
        # Localized wrapper: pick en-US if present, else first non-empty child.
        preferred = None
        for child in elem:
            if child.text and child.text.strip():
                if child.get('Lang', '').lower().startswith('en'):
                    return child.text.strip()
                if preferred is None:
                    preferred = child.text.strip()
        return preferred or ""

    def _get_description(self, elem: etree._Element) -> str:
        """Extract description from element (single- or multi-language)."""
        return self._element_text(elem.find('Description'))
    
    def _parse_comments(self, parent_elem: etree._Element) -> dict[str, str]:
        """Parse comments from a Comments element."""
        comments = {}
        comments_elem = parent_elem.find('Comments')
        if comments_elem is not None:
            for comment in comments_elem.findall('Comment'):
                operand = comment.get('Operand', '')
                text = self._element_text(comment)
                if operand and text:
                    # Remove leading dot if present
                    if operand.startswith('.'):
                        operand = operand[1:]
                    comments[operand] = text
        return comments

    def _parse_data_types(self, controller_elem: etree._Element) -> Generator[UserDataType, None, None]:
        """Parse user-defined data types."""
        for dt_elem in controller_elem.findall('.//DataTypes/DataType'):
            udt = UserDataType(
                name=dt_elem.get('Name', ''),
                family=dt_elem.get('Family', 'NoFamily'),
                udt_class=dt_elem.get('Class', 'User'),
                description=self._get_description(dt_elem),
            )
            
            # Parse members
            for member_elem in dt_elem.findall('.//Members/Member'):
                if member_elem.get('Hidden', 'false').lower() == 'true':
                    continue  # Skip hidden backing members
                    
                member = DataTypeMember(
                    name=member_elem.get('Name', ''),
                    data_type=member_elem.get('DataType', ''),
                    dimension=int(member_elem.get('Dimension', 0)),
                    description=self._get_description(member_elem),
                    hidden=member_elem.get('Hidden', 'false').lower() == 'true',
                    external_access=member_elem.get('ExternalAccess', 'Read/Write'),
                    bit_number=int(member_elem.get('BitNumber')) if member_elem.get('BitNumber') else None,
                    target=member_elem.get('Target'),
                )
                udt.members.append(member)
            
            yield udt
    
    def _parse_aois(self, controller_elem: etree._Element) -> Generator[AddOnInstruction, None, None]:
        """Parse Add-On Instruction definitions."""
        for aoi_elem in controller_elem.findall('.//AddOnInstructionDefinitions/AddOnInstructionDefinition'):
            aoi = AddOnInstruction(
                name=aoi_elem.get('Name', ''),
                revision=aoi_elem.get('Revision', ''),
                vendor=aoi_elem.get('Vendor', ''),
                description=self._get_description(aoi_elem),
            )

            # Parse parameter definitions in document order. Studio 5000 lists a
            # call's arguments in this order, so it lets us label each operand
            # with its parameter name.
            params_elem = aoi_elem.find('Parameters')
            if params_elem is not None:
                for p in params_elem.findall('Parameter'):
                    aoi.parameters.append(AOIParameter(
                        name=p.get('Name', ''),
                        usage=p.get('Usage', ''),
                        required=p.get('Required', 'false').lower() == 'true',
                    ))

            # Parse AOI routines
            for routine_elem in aoi_elem.findall('.//Routines/Routine'):
                routine = self._parse_routine(routine_elem)
                aoi.routines.append(routine)

            yield aoi
    
    def _parse_modules(self, controller_elem: etree._Element):
        """Parse I/O modules with full I/O point enumeration.
        
        I/O references in Rockwell use the format:
          - For remote I/O: ParentModule:Slot:I.Point or ParentModule:Slot:O.Point
          - For local I/O: Local:Slot:I.Data.Point or Local:Slot:O.Data.Point
          
        Examples:
          - HEAT_ZONE_1:1:I.00 = Input 0 on slot 1 of HEAT_ZONE_1 adapter
          - HEAT_ZONE_1:5:O.00 = Output 0 on slot 5 of HEAT_ZONE_1 adapter
          - HEAT_ZONE_1:11:I.Ch0Data = Channel 0 of RTD module in slot 11
        """
        for mod_elem in controller_elem.findall('.//Modules/Module'):
            mod_name = mod_elem.get('Name', '')
            catalog = mod_elem.get('CatalogNumber', '')
            parent_module = mod_elem.get('ParentModule', '')

            # Get slot from Port address if available
            slot = ""
            port_elem = mod_elem.find('.//Ports/Port[@Upstream="true"]')
            if port_elem is not None:
                slot = port_elem.get('Address', '')

            # Parse all ports for network info
            ports = []
            for port_el in mod_elem.findall('.//Ports/Port'):
                ports.append(ModulePort(
                    port_id=port_el.get('Id', ''),
                    address=port_el.get('Address', ''),
                    port_type=port_el.get('Type', ''),
                    upstream=port_el.get('Upstream', 'false') == 'true',
                ))

            # Get I/O spec from catalog
            in_count, out_count, data_fmt = get_module_io_spec(catalog)

            # Build description lookup from InAliasTag/OutAliasTag comments
            desc_map = {}  # operand -> description

            in_alias = mod_elem.find('.//InAliasTag/Comments')
            if in_alias is not None:
                for c in in_alias.findall('Comment'):
                    op = c.get('Operand', '')
                    txt = c.text.strip() if c.text else ''
                    if op:
                        desc_map[op] = txt

            out_alias = mod_elem.find('.//OutAliasTag/Comments')
            if out_alias is not None:
                for c in out_alias.findall('Comment'):
                    op = c.get('Operand', '')
                    txt = c.text.strip() if c.text else ''
                    if op:
                        desc_map[op] = txt

            io_points = []
            
            # Determine tag reference base
            # For remote I/O: ParentModule:Slot:I/O.Point
            # For local/embedded: ModuleName:I/O.Point or Local:Slot:I/O.Point
            if parent_module and slot:
                # Remote I/O module - use parent:slot addressing
                tag_base = f"{parent_module}:{slot}"
            else:
                # Local or embedded - use module name directly
                tag_base = mod_name if mod_name else "Local"

            # Enumerate input points
            for i in range(in_count):
                if data_fmt == 'data':
                    # Standard digital I/O - uses .XX format
                    operand = f".Data.{i}"
                    tag_ref = f"{tag_base}:I.{i:02d}"
                elif data_fmt == 'safety':
                    # Safety I/O - uses .PtXXData format
                    operand = f".Pt{i:02d}Data"
                    tag_ref = f"{tag_base}:I.Pt{i:02d}Data"
                elif data_fmt == 'channel':
                    operand = f".Ch{i}Data"
                    tag_ref = f"{tag_base}:I.Ch{i}Data"
                else:
                    operand = f".{i}"
                    tag_ref = f"{tag_base}:I.{i:02d}"

                # Look up description - try multiple operand formats
                # L5X Comments use ".0", ".1" but we might generate ".Data.0"
                desc = desc_map.get(operand, '')
                if not desc:
                    desc = desc_map.get(f".{i}", '')  # Try simple format

                io_points.append(IOPoint(
                    operand=operand,
                    point_type='Input',
                    description=desc,
                    module_name=mod_name,
                    tag_reference=tag_ref,
                ))

            # Enumerate output points
            for i in range(out_count):
                if data_fmt == 'data':
                    operand = f".Data.{i}"
                    tag_ref = f"{tag_base}:O.{i:02d}"
                elif data_fmt == 'safety':
                    # Safety I/O - uses .PtXXData format
                    operand = f".Pt{i:02d}Data"
                    tag_ref = f"{tag_base}:O.Pt{i:02d}Data"
                elif data_fmt == 'channel':
                    operand = f".Ch{i}Data"
                    tag_ref = f"{tag_base}:O.Ch{i}Data"
                else:
                    operand = f".{i}"
                    tag_ref = f"{tag_base}:O.{i:02d}"

                # Look up description - try multiple operand formats
                desc = desc_map.get(operand, '')
                if not desc:
                    desc = desc_map.get(f".{i}", '')  # Try simple format

                io_points.append(IOPoint(
                    operand=operand,
                    point_type='Output',
                    description=desc,
                    module_name=mod_name,
                    tag_reference=tag_ref,
                ))

            yield Module(
                name=mod_name,
                catalog_number=catalog,
                vendor=mod_elem.get('Vendor', ''),
                slot=slot,
                description=self._get_description(mod_elem),
                parent_module=parent_module,
                parent_port=mod_elem.get('ParentModPortId', ''),
                ports=ports,
                io_points=io_points,
            )
    
    def _parse_tags(self, parent_elem: etree._Element, scope: str) -> Generator[Tag, None, None]:
        """Parse tags from a Tags element."""
        for tag_elem in parent_elem.findall('.//Tags/Tag'):
            # Skip if this is under a Program (we'll get those separately)
            if scope == 'Controller' and tag_elem.getparent().getparent().tag == 'Program':
                continue
                
            # Parse dimensions (can be single or multi-dimensional like "32 18")
            dim_attr = tag_elem.get('Dimensions', '')
            dim_val = 0
            if dim_attr:
                try:
                    # Extract first integer found
                    m = re.findall(r"\d+", str(dim_attr))
                    if m:
                        dim_val = int(m[0])
                except Exception:
                    dim_val = 0

            tag = Tag(
                name=tag_elem.get('Name', ''),
                data_type=tag_elem.get('DataType', ''),
                scope=scope,
                description=self._get_description(tag_elem),
                external_access=tag_elem.get('ExternalAccess', 'Read/Write'),
                tag_class=tag_elem.get('Class', 'Standard'),
                constant=tag_elem.get('Constant', 'false').lower() == 'true',
                alias_for=tag_elem.get('AliasFor', ''),
                dimension=dim_val,
                comments=self._parse_comments(tag_elem),
            )
            yield tag
    
    def _parse_programs(self, controller_elem: etree._Element) -> Generator[Program, None, None]:
        """Parse programs."""
        for prog_elem in controller_elem.findall('.//Programs/Program'):
            program = Program(
                name=prog_elem.get('Name', ''),
                main_routine=prog_elem.get('MainRoutineName', ''),
                disabled=prog_elem.get('Disabled', 'false').lower() == 'true',
                description=self._get_description(prog_elem),
            )
            
            # Parse program-scoped tags
            program.local_tags = list(self._parse_tags(prog_elem, program.name))
            
            # Parse program comments
            program.comments = self._parse_comments(prog_elem)
            
            # Parse routines
            for routine_elem in prog_elem.findall('.//Routines/Routine'):
                routine = self._parse_routine(routine_elem)
                program.routines.append(routine)
            
            yield program
    
    def _parse_routine(self, routine_elem: etree._Element) -> Routine:
        """Parse a routine element."""
        routine = Routine(
            name=routine_elem.get('Name', ''),
            routine_type=routine_elem.get('Type', 'RLL'),
            description=self._get_description(routine_elem),
        )
        
        # Parse RLL rungs
        if routine.routine_type == 'RLL':
            for rung_elem in routine_elem.findall('.//RLLContent/Rung'):
                rung = self._parse_rung(rung_elem)
                routine.rungs.append(rung)
        
        # Parse Structured Text routines (ST)
        elif routine.routine_type == 'ST':
            # Common L5X structures:
            # <STContent><STText><![CDATA[ ... ]]></STText></STContent>
            # or occasionally <STContent><Text>...</Text></STContent>
            st_text = ''
            st_content = routine_elem.find('.//STContent')
            if st_content is not None:
                st_text_elem = st_content.find('STText')
                if st_text_elem is None:
                    st_text_elem = st_content.find('Text')
                if st_text_elem is not None and st_text_elem.text:
                    st_text = st_text_elem.text.strip()
            else:
                # Fallback: some exports place ST under Routine/Text
                fallback = routine_elem.find('Text')
                if fallback is not None and fallback.text:
                    st_text = fallback.text.strip()

            # Represent ST as a single pseudo-rung for rendering purposes
            routine.rungs.append(Rung(
                number=1,
                rung_type='N',
                text=st_text,
                comment=routine.description or ''
            ))
        
        return routine
    
    def _parse_rung(self, rung_elem: etree._Element) -> Rung:
        """Parse a rung element."""
        text_elem = rung_elem.find('Text')

        return Rung(
            number=int(rung_elem.get('Number', 0)),
            rung_type=rung_elem.get('Type', 'N'),
            text=text_elem.text.strip() if text_elem is not None and text_elem.text else '',
            comment=self._element_text(rung_elem.find('Comment')),
        )


class TagCrossReference:
    """
    Builds a cross-reference database of tag usages across all rungs.
    """
    
    # Pattern to extract instructions and their operands
    INSTRUCTION_PATTERN = re.compile(
        r'([A-Z_][A-Z0-9_]*)\s*\(([^)]*)\)',
        re.IGNORECASE
    )
    
    # Pattern to extract tag names from operands
    TAG_PATTERN = re.compile(
        r'([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*(?:\[[^\]]+\])?(?:\.[A-Za-z_][A-Za-z0-9_]*)*)',
    )

    # Destination operand index by instruction (0-based)
    # Only operands at this index are considered destructive writes.
    DEST_OPERAND_INDEX: dict[str, int] = {
        # Coils and simple tags
        'OTE': 0, 'OTL': 0, 'OTU': 0, 'RES': 0, 'CLR': 0,
        # Timers/Counters
        'CTU': 0, 'CTD': 0, 'TON': 0, 'TOF': 0, 'RTO': 0,
        # Moves and block operations
        'MOV': 1, 'MVM': 1, 'COP': 1, 'FLL': 1,
        # Math operations: ADD(SrcA, SrcB, Dest)
        'ADD': 2, 'SUB': 2, 'MUL': 2, 'DIV': 2,
        # Control/derived
        'CPT': 0,
        # System value
        'SSV': 0,  # Set System Value
        'GSV': 1,  # Get System Value writes into second operand
        # Message
        'MSG': 0,
    }

    # Instructions known to be read-only regarding operands
    READ_ONLY_INSTRUCTIONS = {
        'XIC', 'XIO', 'ONS', 'OSR', 'OSF',
        'EQU', 'NEQ', 'LES', 'LEQ', 'GRT', 'GEQ', 'MEQ', 'LIM',
        'CMP',
        # Control flow (do not mark destructive)
        'JSR', 'SBR', 'RET', 'FOR', 'NXT', 'BRK',
    }
    
    def __init__(self, controller: Controller):
        """Initialize with parsed controller."""
        self.controller = controller
        self._tag_map: dict[str, Tag] = {}
        self._build_tag_map()
    
    def _build_tag_map(self):
        """Build a map of all tags by name."""
        for tag in self.controller.controller_tags:
            self._tag_map[tag.name.lower()] = tag
        
        for program in self.controller.programs:
            for tag in program.local_tags:
                key = f"{program.name.lower()}.{tag.name.lower()}"
                self._tag_map[key] = tag
    
    def build_cross_reference(self):
        """Build cross-reference of all tag usages."""
        # Process all programs
        for program in self.controller.programs:
            for routine in program.routines:
                for rung in routine.rungs:
                    self._process_rung(program.name, routine.name, rung)
        
        # Process AOI routines
        for aoi in self.controller.add_on_instructions:
            for routine in aoi.routines:
                for rung in routine.rungs:
                    self._process_rung(f"AOI:{aoi.name}", routine.name, rung)
    
    def _process_rung(self, program: str, routine: str, rung: Rung):
        """Process a rung and extract tag usages."""
        for match in self.INSTRUCTION_PATTERN.finditer(rung.text):
            instruction = match.group(1).upper()
            operands_text = match.group(2)

            # Split operands by commas, respecting simple formats
            operands = [op.strip() for op in re.split(r',\s*', operands_text)] if operands_text else []
            dest_index = self.DEST_OPERAND_INDEX.get(instruction, None)

            # Determine if instruction is read-only
            is_read_only = instruction in self.READ_ONLY_INSTRUCTIONS

            # Process each operand and assign usage type per operand role
            for idx, operand in enumerate(operands):
                # Find tags within this operand expression
                for tag_match in self.TAG_PATTERN.finditer(operand):
                    tag_name = tag_match.group(1)
                    base_name = tag_name.split('.')[0].split('[')[0]

                    # Look up tag in local or controller scope
                    tag = self._find_tag(base_name, program)
                    if not tag:
                        continue

                    # Usage classification
                    if not is_read_only and dest_index is not None and idx == dest_index:
                        usage_type = 'destructive'
                    else:
                        usage_type = 'read'

                    usage = TagUsage(
                        program=program,
                        routine=routine,
                        rung_number=rung.number,
                        usage_type=usage_type,
                        instruction=instruction,
                        ref=tag_name,
                    )
                    tag.usages.append(usage)
    
    def _find_tag(self, name: str, program: str) -> Optional[Tag]:
        """Find a tag by name, checking local scope first."""
        # Check program scope
        local_key = f"{program.lower()}.{name.lower()}"
        if local_key in self._tag_map:
            return self._tag_map[local_key]
        
        # Check controller scope
        if name.lower() in self._tag_map:
            return self._tag_map[name.lower()]
        
        return None
    
    def get_all_tags(self) -> list[Tag]:
        """Get all tags with their usage information."""
        return list(self._tag_map.values())
    
    def get_tag_usages(self, tag_name: str) -> list[TagUsage]:
        """Get all usages for a specific tag."""
        tag = self._find_tag(tag_name, '')
        return tag.usages if tag else []

    # --- Documentation helpers expected by the generator ---
    def generate_documentation(self, full_path: str, max_refs: int = 3, program: Optional[str] = None) -> str:
        """Generate a brief documentation string for a tag path.

        Resolves controller- or program-scoped tags. When program is provided,
        attempts local scope first; otherwise aggregates usages across any tag
        with the same base name.
        Filters array-element refs (e.g., Tag[86]) to only matching operand refs.
        """
        try:
            base = full_path.split('.')[0].split('[')[0]
            if not base:
                return ""

            # Extract array index (if any) from full_path like "Tag[86]" or "Program:Tag[86]"
            idx_match = re.search(r"\[(\d+)\]", full_path)
            idx_str = idx_match.group(1) if idx_match else None

            tags_to_report: list[Tag] = []

            # Try exact resolution first
            if program:
                t = self._find_tag(base, program)
                if t:
                    tags_to_report.append(t)
            # Controller-scope fallback
            t_ctrl = self._find_tag(base, '')
            if t_ctrl and t_ctrl not in tags_to_report:
                tags_to_report.append(t_ctrl)

            # If still unresolved, aggregate any tags matching this base name
            if not tags_to_report:
                base_lower = base.lower()
                # Controller name match
                ctrl_tag = self._tag_map.get(base_lower)
                if ctrl_tag:
                    tags_to_report.append(ctrl_tag)
                # Program-scoped matches: keys like 'program.base'
                for key, tag in self._tag_map.items():
                    if key.endswith('.' + base_lower):
                        tags_to_report.append(tag)

            if not tags_to_report:
                return ""

            # Combine usages across all matching tags
            usages: list[TagUsage] = []
            description = ""
            for t in tags_to_report:
                description = description or t.description
                usages.extend(t.usages)

            if not usages:
                return description or ""

            # If we have an array index, filter usages to only those referencing that index
            if idx_str:
                idx_token = f"[{idx_str}]"
                usages = [u for u in usages if idx_token in (u.ref or '')]
                if not usages:
                    # If nothing matched exactly, fall back to base behavior
                    usages = []  # keep empty so we can return description only

            if not usages:
                return description or ""

            # Deduplicate by location and ref to avoid duplicates
            seen = set()
            deduped: list[TagUsage] = []
            for u in usages:
                key = (u.program, u.routine, u.rung_number, u.instruction, u.ref or base)
                if key not in seen:
                    seen.add(key)
                    deduped.append(u)

            # Prefer destructive references (writes) and limit to a small number
            destructive = [u for u in deduped if u.usage_type == 'destructive']
            reads = [u for u in deduped if u.usage_type != 'destructive']

            parts: list[str] = []
            # Show up to 2 destructive writes
            for u in destructive[:2]:
                parts.append(f"{u.program}/{u.routine} #{u.rung_number} {u.instruction} (write)")
            # If no writes found, show up to 3 reads
            if not parts:
                for u in reads[:3]:
                    parts.append(f"{u.program}/{u.routine} #{u.rung_number} {u.instruction} (read)")

            # Indicate additional references conservatively
            extra = max(0, len(destructive) - 2) if destructive else max(0, len(reads) - len(parts))
            summary_suffix = f" +{extra} more" if extra > 0 else ""
            return (f"Refs: " + "; ".join(parts) + summary_suffix) if parts else (description or "")
        except Exception:
            return ""

    def generate_member_documentation(self, member_path: str, max_refs: int = 3) -> str:
        """Best-effort documentation for a UDT member path.

        Without a specific base tag instance we cannot resolve scope reliably,
        so return an empty string to avoid blocking generation.
        """
        return ""


def discover_l5x_files(root_path: str | Path) -> Generator[Path, None, None]:
    """
    Recursively discover all L5X files in a directory.
    
    Args:
        root_path: Root directory to search
        
    Yields:
        Path objects for each L5X file found
    """
    root = Path(root_path)
    for l5x_file in root.rglob('*.l5x'):
        # Skip backup files
        if '.bak' in l5x_file.stem.lower():
            continue
        yield l5x_file


def parse_all_l5x_files(root_path: str | Path) -> Generator[tuple[Path, Controller], None, None]:
    """
    Parse all L5X files in a directory tree.
    
    Args:
        root_path: Root directory to search
        
    Yields:
        Tuples of (file_path, Controller)
    """
    for l5x_file in discover_l5x_files(root_path):
        try:
            parser = L5XParser(l5x_file)
            controller = parser.parse()
            yield l5x_file, controller
        except Exception as e:
            print(f"Error parsing {l5x_file}: {e}")
            continue
