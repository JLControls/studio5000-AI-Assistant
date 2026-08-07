"""Ambiguity Detector for Studio 5000 L5X tag exports.

Detects low-confidence or ambiguous tag mapping scenarios (e.g. multiple scaling outputs,
un-annotated totalizers, multi-pump lead/lag status bits) and emits guidance queries.
Allows agent to ask the user for guidance via interactive questions.
"""

import xml.etree.ElementTree as ET
from typing import List, Dict, Any, Optional

class AmbiguityQuery:
    def __init__(self, tag_name: str, question: str, options: List[str], default_option: str):
        self.tag_name: str = tag_name
        self.question: str = question
        self.options: List[str] = options
        self.default_option: str = default_option

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tag_name": self.tag_name,
            "question": self.question,
            "options": self.options,
            "default_option": self.default_option
        }


def detect_tag_ambiguities(root: ET.Element) -> List[AmbiguityQuery]:
    """Detect ambiguous tags in L5X project requiring potential user guidance."""
    queries: List[AmbiguityQuery] = []

    for tag in root.iter("Tag"):
        name = tag.attrib.get("Name", "")
        data_type = tag.attrib.get("DataType", "")
        comment_el = tag.find("Description")
        comment = comment_el.text.strip() if comment_el is not None and comment_el.text else ""

        # Un-annotated flow totalizers or multi-member structures
        if data_type in ("TOTALIZER", "FData1", "Fdata2") and not comment:
            queries.append(AmbiguityQuery(
                tag_name=name,
                question=f"Tag '{name}' is a flow totalizer structure with no description. Should it be mapped as a Flow Rate (GPM) or Volume Total (GAL)?",
                options=["Map both Flow Rate (.Flow) and Flow Total (.Tot)", "Map Flow Rate (.Flow) only", "Map Flow Total (.Tot) only"],
                default_option="Map both Flow Rate (.Flow) and Flow Total (.Tot)"
            ))

        # Un-annotated multi-pump lead/lag controller
        if data_type in ("PSet2_LL1", "LEAD_LAG") and not comment:
            queries.append(AmbiguityQuery(
                tag_name=name,
                question=f"Pump set controller '{name}' has no comment. Map Lead/Lag status bits to SCADA?",
                options=["Map Lead Pump & Pump Run Status bits", "Do not map internal lead/lag status"],
                default_option="Map Lead Pump & Pump Run Status bits"
            ))

    return queries
