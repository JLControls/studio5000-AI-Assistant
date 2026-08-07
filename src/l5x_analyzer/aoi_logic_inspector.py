"""Deep AOI Logic Inspector for Studio 5000 L5X files.

Reads internal ladder rungs inside <AddOnInstructionDefinition>/<Routines>
to analyze how outputs (ScaledVal, Flow, Tot, mBTUhr, Alarms) are calculated
from inputs and local tags before making assumptions.
"""

import xml.etree.ElementTree as ET
import re
from typing import Dict, List, Optional, Set

class AOIScalingProfile:
    def __init__(self, aoi_name: str):
        self.aoi_name: str = aoi_name
        self.is_scaling_aoi: bool = False
        self.raw_input_param: Optional[str] = None
        self.raw_min_param: Optional[str] = None
        self.raw_max_param: Optional[str] = None
        self.scaled_min_param: Optional[str] = None
        self.scaled_max_param: Optional[str] = None
        self.scaled_output_param: Optional[str] = None
        self.engineering_units: Optional[str] = None

class AOIParameterRole:
    def __init__(self, name: str, data_type: str, usage: str, description: str = ""):
        self.name: str = name
        self.data_type: str = data_type
        self.usage: str = usage
        self.description: str = description
        self.is_scaled_pv: bool = False
        self.is_flow_rate: bool = False
        self.is_volume_total: bool = False
        self.is_energy_rate: bool = False
        self.is_alarm_status: bool = False

class AOILogicProfile:
    def __init__(self, aoi_name: str, description: str = ""):
        self.aoi_name: str = aoi_name
        self.description: str = description
        self.parameters: Dict[str, AOIParameterRole] = {}
        self.scaling_profile: AOIScalingProfile = AOIScalingProfile(aoi_name)
        self.output_params: List[str] = []

    def get_primary_scada_output(self) -> Optional[str]:
        """Find the primary output parameter for SCADA display."""
        # 1. Scaled PV
        for p_name, param in self.parameters.items():
            if param.usage in ("Output", "InOut") and param.is_scaled_pv:
                return p_name
        # 2. Flow rate / Energy rate
        for p_name, param in self.parameters.items():
            if param.usage in ("Output", "InOut") and (param.is_flow_rate or param.is_energy_rate):
                return p_name
        # 3. First output parameter
        if self.output_params:
            return self.output_params[0]
        return None


def inspect_aoi_definition(aoi_elem: ET.Element) -> AOILogicProfile:
    """Inspect an AddOnInstructionDefinition XML element to extract parameter roles and internal logic behavior."""
    aoi_name = aoi_elem.attrib.get("Name", "UnknownAOI")
    desc_elem = aoi_elem.find("Description")
    desc = desc_elem.text.strip() if desc_elem is not None and desc_elem.text else ""

    profile = AOILogicProfile(aoi_name, desc)

    # 1. Inspect Parameter definitions
    for p in aoi_elem.findall("Parameters/Parameter"):
        p_name = p.attrib.get("Name", "")
        p_type = p.attrib.get("DataType", "")
        p_usage = p.attrib.get("Usage", "Input")
        p_desc_el = p.find("Description")
        p_desc = p_desc_el.text.strip() if p_desc_el is not None and p_desc_el.text else ""

        param_role = AOIParameterRole(p_name, p_type, p_usage, p_desc)
        if p_usage in ("Output", "InOut"):
            profile.output_params.append(p_name)

        # Keyword heuristics from parameter description & name
        combined_text = f"{p_name} {p_desc}".lower()

        if any(k in combined_text for k in ["scaled", "engineering unit", "eu val", "scaled_val"]):
            param_role.is_scaled_pv = True
        if any(k in combined_text for k in ["flow rate", "gpm", "header flow", "flow"]):
            param_role.is_flow_rate = True
        if any(k in combined_text for k in ["total", "totalizer", "accumulated", "volume"]):
            param_role.is_volume_total = True
        if any(k in combined_text for k in ["btu", "mbtu", "heat rate", "energy"]):
            param_role.is_energy_rate = True
        if any(k in combined_text for k in ["almstat", "alarm status", "fault status", "0=off"]):
            param_role.is_alarm_status = True

        profile.parameters[p_name] = param_role

    # 2. Inspect Internal Routine Logic (Rungs inside AOI)
    routines = aoi_elem.findall("Routines/Routine")
    for routine in routines:
        for rung in routine.findall("Rung"):
            text_el = rung.find("Text")
            if text_el is None or not text_el.text:
                continue
            text = text_el.text.strip()

            # Check for CPT/SCP scaling math, e.g., CPT(ScaledVal, (InRaw - InRawMin) * ...)
            if "CPT(" in text or "SCP(" in text or "SCL(" in text:
                profile.scaling_profile.is_scaling_aoi = True
                # Match parameters involved in scaling
                for p_name in profile.parameters:
                    p_lower = p_name.lower()
                    if "rawmin" in p_lower or "inmin" in p_lower:
                        profile.scaling_profile.raw_min_param = p_name
                    elif "rawmax" in p_lower or "inmax" in p_lower:
                        profile.scaling_profile.raw_max_param = p_name
                    elif "scaledmin" in p_lower or "eumin" in p_lower or "outmin" in p_lower:
                        profile.scaling_profile.scaled_min_param = p_name
                    elif "scaledmax" in p_lower or "eumax" in p_lower or "outmax" in p_lower:
                        profile.scaling_profile.scaled_max_param = p_name
                    elif "scaledval" in p_lower or "scaled" in p_lower or "out" == p_lower:
                        profile.scaling_profile.scaled_output_param = p_name

    return profile


class AOILogicRegistry:
    """Extensible registry holding AOI Profiles across L5X projects."""

    def __init__(self):
        self._profiles: Dict[str, AOILogicProfile] = {}

    def register_from_l5x(self, root: ET.Element):
        for aoi_elem in root.iter("AddOnInstructionDefinition"):
            profile = inspect_aoi_definition(aoi_elem)
            self._profiles[profile.aoi_name] = profile

    def get_profile(self, aoi_name: str) -> Optional[AOILogicProfile]:
        return self._profiles.get(aoi_name)
