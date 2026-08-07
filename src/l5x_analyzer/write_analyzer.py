"""Rung Write-Detection Engine for Studio 5000 L5X projects.

Analyzes routine ladder logic across controller and program scopes to determine
which tags are written to by PLC logic, physical I/O inputs, or operator setpoints.
Used to filter out unwritten internal PLC tags from SCADA export candidates.
"""

import re
import xml.etree.ElementTree as ET
from typing import Dict, Set, List, Optional

# Regex patterns for common destructive/write instructions in Rockwell ladder logic
DESTRUCTIVE_BIT_RE = re.compile(r'\b(?:OTE|OTL|OTU)\s*\(\s*([A-Za-z0-9_.:\[\]]+)\s*\)', re.IGNORECASE)
DESTRUCTIVE_DEST_RE = re.compile(r'\b(?:MOV|MVM|CPT|ADD|SUB|MUL|DIV|CLR|FLL|SWPB)\s*\([^,\)]*(?:,[^,\)]*)*,\s*([A-Za-z0-9_.:\[\]]+)\s*\)', re.IGNORECASE)
BTD_DEST_RE = re.compile(r'\bBTD\s*\([^,\)]+,[^,\)]+,\s*([A-Za-z0-9_.:\[\]]+)\s*,', re.IGNORECASE)
TIMER_COUNTER_RE = re.compile(r'\b(?:TON|TOF|RTO|CTU|CTD)\s*\(\s*([A-Za-z0-9_.:\[\]]+)\s*,', re.IGNORECASE)

class TagWriteMap:
    def __init__(self):
        self.written_tags: Set[str] = set()
        self.tag_write_locations: Dict[str, List[str]] = {}
        self.io_inputs: Set[str] = set()
        self.hmi_setpoints: Set[str] = set()

    def record_write(self, tag_ref: str, location: str = ""):
        base_tag = self._clean_tag_ref(tag_ref)
        if base_tag:
            self.written_tags.add(base_tag)
            self.written_tags.add(tag_ref)
            if base_tag not in self.tag_write_locations:
                self.tag_write_locations[base_tag] = []
            if location and location not in self.tag_write_locations[base_tag]:
                self.tag_write_locations[base_tag].append(location)

    def record_io_input(self, tag_name: str):
        base_tag = self._clean_tag_ref(tag_name)
        if base_tag:
            self.io_inputs.add(base_tag)
            self.written_tags.add(base_tag)

    def record_hmi_setpoint(self, tag_name: str):
        base_tag = self._clean_tag_ref(tag_name)
        if base_tag:
            self.hmi_setpoints.add(base_tag)
            self.written_tags.add(base_tag)

    def is_written(self, tag_name: str) -> bool:
        base_tag = self._clean_tag_ref(tag_name)
        if not base_tag:
            return False
        # Direct check or base tag check
        if tag_name in self.written_tags or base_tag in self.written_tags:
            return True
        if base_tag in self.io_inputs or base_tag in self.hmi_setpoints:
            return True
        # Check prefix matches for structures (e.g. Com_CW -> Com_CW.Flow)
        prefix = base_tag + "."
        if any(w.startswith(prefix) for w in self.written_tags):
            return True
        return False

    @staticmethod
    def _clean_tag_ref(tag_ref: str) -> str:
        if not tag_ref:
            return ""
        # Remove array indices, e.g. Tag[0] -> Tag
        cleaned = re.sub(r'\[.*?\]', '', tag_ref.strip())
        # Remove program prefix if present
        if cleaned.startswith("Program:"):
            parts = cleaned.split(".", 1)
            if len(parts) > 1:
                cleaned = parts[1]
        return cleaned


def analyze_l5x_tag_writes(root: ET.Element) -> TagWriteMap:
    """Analyze an L5X XML root tree to record all tag write operations."""
    write_map = TagWriteMap()

    # 1. Identify AOI Output Parameter positions
    aoi_outputs: Dict[str, List[int]] = {}
    for aoi in root.iter("AddOnInstructionDefinition"):
        aoi_name = aoi.attrib.get("Name", "")
        output_indices = []
        for idx, param in enumerate(aoi.findall("Parameters/Parameter")):
            usage = param.attrib.get("Usage", "Input")
            if usage in ("Output", "InOut"):
                output_indices.append(idx)
        if output_indices:
            aoi_outputs[aoi_name] = output_indices

    # 2. Record Physical I/O Inputs and HMI Setpoints/Commands from Tags
    for tag in root.iter("Tag"):
        name = tag.attrib.get("Name", "")
        alias_for = tag.attrib.get("AliasFor", "")

        # Physical digital/analog inputs
        if name.startswith("Com_AliasDIn_") or name.startswith("Com_AliasAIn_") or name.startswith("Htr1_AliasDIn_") or "AliasDIn" in name or "AliasAIn" in name:
            write_map.record_io_input(name)
        elif alias_for and (":I" in alias_for or "Input" in alias_for):
            write_map.record_io_input(name)

        # Operator HMI commands / setpoints
        if name.startswith("Com_Cmd_") or name.startswith("Com_Set_") or name.startswith("Htr1_Cmd_") or name.startswith("Htr1_Set_") or "Set_" in name or "Cmd_" in name:
            write_map.record_hmi_setpoint(name)

    # 3. Scan all routine rungs across all Programs and AOIs
    for routine in root.iter("Routine"):
        routine_name = routine.attrib.get("Name", "UnknownRoutine")
        for rung in routine.iter("Rung"):
            rung_num = rung.attrib.get("Number", "0")
            location = f"{routine_name}:R{rung_num}"
            text_el = rung.find("Text")
            if text_el is None or not text_el.text:
                continue
            text = text_el.text.strip()

            # OTE / OTL / OTU
            for match in DESTRUCTIVE_BIT_RE.findall(text):
                write_map.record_write(match, location)

            # MOV / CPT / ADD / SUB / MUL / DIV / CLR / FLL / SWPB
            for match in DESTRUCTIVE_DEST_RE.findall(text):
                write_map.record_write(match, location)

            # BTD
            for match in BTD_DEST_RE.findall(text):
                write_map.record_write(match, location)

            # Timer / Counter implicitly writes to .ACC, .DN, .TT
            for match in TIMER_COUNTER_RE.findall(text):
                write_map.record_write(f"{match}.ACC", location)
                write_map.record_write(f"{match}.DN", location)
                write_map.record_write(f"{match}.TT", location)

            # Check AOI calls for output arguments
            for aoi_name, output_indices in aoi_outputs.items():
                if aoi_name in text:
                    # Match AOI_NAME(arg1, arg2, ...)
                    pattern = r'\b' + re.escape(aoi_name) + r'\s*\((.*?)\)'
                    for call_match in re.finditer(pattern, text):
                        args_str = call_match.group(1)
                        # Split args by comma (respecting nested brackets)
                        args = [a.strip() for a in args_str.split(",")]
                        for out_idx in output_indices:
                            if out_idx < len(args):
                                arg_ref = args[out_idx]
                                if arg_ref and arg_ref.upper() != "NA":
                                    write_map.record_write(arg_ref, location)

    return write_map
