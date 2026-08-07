"""Extensible AOI & UDT Structure Expander for SCADA Tag Exporter.

Expands Rockwell composite process structures (FData1, Fdata2, TData1, Btu1, SCP,
TOTALIZER, HrCtr1, TLevel1, PSet2_LL1) into operator-facing atomic SCADA tags.
"""

from typing import List, Dict, Any, Optional

class ExpandedMemberTag:
    def __init__(self, member_suffix: str, name_suffix: str, data_type: str, eng_unit: str = "", doc_desc: str = ""):
        self.member_suffix: str = member_suffix
        self.name_suffix: str = name_suffix
        self.data_type: str = data_type
        self.eng_unit: str = eng_unit
        self.doc_desc: str = doc_desc

STRUCTURE_EXPANSION_RULES: Dict[str, List[ExpandedMemberTag]] = {
    "FData1": [
        ExpandedMemberTag(".Flow", "Flow Rate", "Float4", "GPM", "Calculated volumetric flow rate"),
        ExpandedMemberTag(".Tot", "Flow Total", "Float4", "GAL", "Accumulated volumetric flow total"),
        ExpandedMemberTag(".Tot_ACC", "Flow Total Accumulator", "Int4", "Counts", "Raw totalizer counter value"),
        ExpandedMemberTag(".Tot_Rollover", "Flow Total Rollover Count", "Int4", "Count", "Totalizer rollover counter"),
    ],
    "Fdata2": [
        ExpandedMemberTag(".Flow", "Flow Rate", "Float4", "GPM", "Calculated volumetric flow rate"),
        ExpandedMemberTag(".Tot", "Flow Total", "Float4", "GAL", "Accumulated volumetric flow total"),
    ],
    "TData1": [
        ExpandedMemberTag(".Temp", "Temperature", "Float4", "°F", "Process temperature reading"),
        ExpandedMemberTag(".SP", "Temperature Setpoint", "Float4", "°F", "Target temperature setpoint"),
    ],
    "Btu1": [
        ExpandedMemberTag(".mBTUhr", "Heat Duty Rate", "Float4", "mBTU/hr", "Calculated thermal power duty"),
        ExpandedMemberTag(".Total_mBTU", "Total Thermal Energy", "Float4", "mBTU", "Cumulative energy total"),
    ],
    "TOTALIZER": [
        ExpandedMemberTag(".Flow", "Flow Rate", "Float4", "GPM", "Flow rate input"),
        ExpandedMemberTag(".Tot", "Flow Total", "Float4", "GAL", "Accumulated flow total"),
        ExpandedMemberTag(".ACC", "Raw Accumulator", "Int4", "Counts", "Raw accumulator count"),
        ExpandedMemberTag(".DN", "Batch Complete", "Boolean", "", "Totalizer batch target reached"),
    ],
    "HrCtr1": [
        ExpandedMemberTag(".Hours", "Operating Hours", "Float4", "Hrs", "Equipment operating hour counter"),
        ExpandedMemberTag(".Min", "Operating Minutes", "Float4", "Min", "Equipment operating minute counter"),
        ExpandedMemberTag(".Run_Stat", "Run Status", "Boolean", "", "Equipment run status feedback"),
    ],
    "SCP": [
        ExpandedMemberTag(".ScaledVal", "Scaled Value", "Float4", "", "Scaled engineering unit output value"),
    ],
    "SCPLim1": [
        ExpandedMemberTag(".ScaledVal", "Scaled Value", "Float4", "", "Scaled engineering unit output value"),
    ],
    "PSet2_LL1": [
        ExpandedMemberTag(".P1_Lead", "Pump 1 Lead Status", "Boolean", "", "Pump 1 assigned as lead pump"),
        ExpandedMemberTag(".P2_Lead", "Pump 2 Lead Status", "Boolean", "", "Pump 2 assigned as lead pump"),
        ExpandedMemberTag(".P1_Run_En", "Pump 1 Run Enable", "Boolean", "", "Pump 1 command run enable"),
        ExpandedMemberTag(".P2_Run_En", "Pump 2 Run Enable", "Boolean", "", "Pump 2 command run enable"),
        ExpandedMemberTag(".Com_AlmStat_P1", "Alarm Status Pump 1", "Int4", "", "Pump 1 operational alarm status code"),
        ExpandedMemberTag(".Com_AlmStat_P2", "Alarm Status Pump 2", "Int4", "", "Pump 2 operational alarm status code"),
    ],
    "TLevel1": [
        ExpandedMemberTag(".Hi_L", "High Level Alarm", "Boolean", "", "Storage tank high level alarm"),
        ExpandedMemberTag(".AvgRt_L", "Average Rate Level Demand", "Boolean", "", "Storage tank average rate fill demand"),
        ExpandedMemberTag(".EmgRt_L", "Emergency Rate Level Demand", "Boolean", "", "Storage tank emergency rate fill demand"),
        ExpandedMemberTag(".Lo_L", "Low Level Alarm", "Boolean", "", "Storage tank low level alarm"),
        ExpandedMemberTag(".Mod_V1_PID_SP", "Modulating Valve Target Setpoint", "Float4", "GPM", "Calculated makeup valve target flow setpoint"),
    ],
}


# Case-insensitive index: L5X data-type strings do not always match the canonical
# casing of the rule keys (and callers may upper-case dtypes), so all lookups go
# through the lowercased type name.
_RULES_CI: Dict[str, List[ExpandedMemberTag]] = {
    key.lower(): rules for key, rules in STRUCTURE_EXPANSION_RULES.items()
}


def _rules_for(data_type: str) -> Optional[List[ExpandedMemberTag]]:
    """Return the expansion rules for ``data_type`` (case-insensitive), or None."""
    return _RULES_CI.get((data_type or "").lower())


def is_expandable_structure(data_type: str) -> bool:
    """Check if data_type has a known structure expansion rule (case-insensitive)."""
    return _rules_for(data_type) is not None


def find_member_rule(data_type: str, member_suffix: str) -> Optional[ExpandedMemberTag]:
    """Return the rule for one member of ``data_type`` by its ``.Suffix`` (or bare name).

    Used to recover a member's Ignition data type / engineering unit when an agent
    supplies a member ref directly (e.g. ``Com_CW.Flow``) rather than the struct root.
    """
    rules = _rules_for(data_type)
    if not rules:
        return None
    suffix = member_suffix if member_suffix.startswith(".") else "." + member_suffix.split(".")[-1]
    for rule in rules:
        if rule.member_suffix.lower() == suffix.lower():
            return rule
    return None


def expand_structure_members(base_plc_tag: str, data_type: str, base_friendly_name: str = "") -> List[Dict[str, Any]]:
    """Expand a composite tag into member SCADA tag specifications."""
    rules = _rules_for(data_type)
    if not rules:
        return []

    results = []
    for rule in rules:
        plc_ref = f"{base_plc_tag}{rule.member_suffix}"
        friendly_title = f"{base_friendly_name} {rule.name_suffix}".strip() if base_friendly_name else rule.name_suffix
        results.append({
            "plc_tag": plc_ref,
            "name": friendly_title,
            "dataType": rule.data_type,
            "engUnit": rule.eng_unit,
            "doc_desc": rule.doc_desc,
            "base_tag": base_plc_tag,
            "member_suffix": rule.member_suffix
        })
    return results
