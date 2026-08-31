from dataclasses import dataclass, field
from typing import List, Optional
from .parser import Controller, Program, Module
import re

@dataclass
class DeviceSetpoint:
    name: str
    value: str
    description: str

@dataclass
class DeviceControl:
    program: str
    routine: str
    rung: int
    text: str
    type: str # "Start", "Stop", "Reset", "Enable", "Disable", "Command"

@dataclass
class Device:
    name: str
    device_type: str # "Servo", "VFD"
    description: str
    setpoints: List[DeviceSetpoint] = field(default_factory=list)
    controls: List[DeviceControl] = field(default_factory=list)

class DeviceExtractor:
    def __init__(self, controller: Controller):
        self.controller = controller

    def extract(self) -> List[Device]:
        devices = []
        devices.extend(self._extract_servos())
        devices.extend(self._extract_vfds())
        return devices

    def _extract_servos(self) -> List[Device]:
        servos = []
        for program in self.controller.programs:
            if program.name.startswith("AXIS_"):
                device = Device(
                    name=program.name,
                    device_type="Servo",
                    description=program.description
                )
                
                # Extract Setpoints from R00_Parameter_Initialize
                for routine in program.routines:
                    if routine.name == "R00_Parameter_Initialize":
                        for rung in routine.rungs:
                            # Look for MOV instructions
                            # Pattern: MOV(Source, Destination)
                            matches = re.finditer(r'MOV\(([^,]+),([^)]+)\)', rung.text)
                            for match in matches:
                                source = match.group(1).strip()
                                dest = match.group(2).strip()
                                if "MotionInstructions.Data" in dest:
                                    param_name = dest.replace("MotionInstructions.Data.", "")
                                    device.setpoints.append(DeviceSetpoint(
                                        name=param_name,
                                        value=source,
                                        description=rung.comment
                                    ))
                
                # Extract Controls from Main
                for routine in program.routines:
                    if routine.name == "Main":
                        for rung in routine.rungs:
                            # Look for OTE to Interlocks
                            matches = re.finditer(r'OTE\(MotionInstructions\.Interlocks\.([^)]+)\)', rung.text)
                            for match in matches:
                                interlock = match.group(1).strip()
                                device.controls.append(DeviceControl(
                                    program=program.name,
                                    routine=routine.name,
                                    rung=rung.number,
                                    text=rung.text,
                                    type=interlock
                                ))
                
                servos.append(device)
        return servos

    def _extract_vfds(self) -> List[Device]:
        vfds = []
        for module in self.controller.modules:
            if "PowerFlex" in module.catalog_number:
                device = Device(
                    name=module.name,
                    device_type="VFD",
                    description=module.description
                )
                
                # Find potential control tags (Tag name is prefix of Module name)
                controller_control_tags = []
                for tag in self.controller.controller_tags:
                    if module.name.startswith(tag.name) and len(tag.name) > 4: 
                        controller_control_tags.append(tag.name)
                
                # Search for controls in all programs
                for program in self.controller.programs:
                    # Find program-scoped control tags
                    program_control_tags = []
                    for tag in program.local_tags:
                        if module.name.startswith(tag.name) and len(tag.name) > 4:
                            program_control_tags.append(tag.name)
                    
                    # Combine tags to search for in this program
                    tags_to_search = controller_control_tags + program_control_tags
                    
                    for routine in program.routines:
                        for rung in routine.rungs:
                            # OTE to Output tags
                            # Pattern: OTE(ModuleName:O.BitName)
                            # Allow for spaces around the tag
                            ote_pattern = f'OTE\\(\\s*{re.escape(module.name)}:O\\.([^)]+?)\\s*\\)'
                            matches = re.finditer(ote_pattern, rung.text)
                            for match in matches:
                                bit_name = match.group(1).strip()
                                device.controls.append(DeviceControl(
                                    program=program.name,
                                    routine=routine.name,
                                    rung=rung.number,
                                    text=rung.text,
                                    type=bit_name
                                ))
                            
                            # Frequency Command
                            # Pattern: MOV(Source, ModuleName:O.FreqCommand) or MUL(..., ModuleName:O.FreqCommand)
                            # Allow for spaces
                            freq_pattern = f'[,\\(]\\s*([^,]+?)\\s*,\\s*{re.escape(module.name)}:O\\.FreqCommand\\s*\\)'
                            matches = re.finditer(freq_pattern, rung.text)
                            for match in matches:
                                source = match.group(1).strip()
                                device.controls.append(DeviceControl(
                                    program=program.name,
                                    routine=routine.name,
                                    rung=rung.number,
                                    text=rung.text,
                                    type="FreqCommand"
                                ))
                                
                                # Try to find setpoint if it's a simple MOV
                                if "MOV" in rung.text:
                                    device.setpoints.append(DeviceSetpoint(
                                        name="FreqCommand",
                                        value=source,
                                        description=rung.comment
                                    ))
                            
                            # Control Tag Usage
                            for tag_name in tags_to_search:
                                # We are interested in Start, Stop, Cmd, etc.
                                # Regex: OTE(TagName.([^)]+))
                                tag_ote_pattern = f'OTE\\(\\s*{re.escape(tag_name)}\\.([^)]+?)\\s*\\)'
                                matches = re.finditer(tag_ote_pattern, rung.text)
                                for match in matches:
                                    member = match.group(1).strip()
                                    # Filter for interesting members
                                    if any(x in member.lower() for x in ['start', 'stop', 'cmd', 'run', 'enable']):
                                        device.controls.append(DeviceControl(
                                            program=program.name,
                                            routine=routine.name,
                                            rung=rung.number,
                                            text=rung.text,
                                            type=f"{tag_name}.{member}"
                                        ))

                vfds.append(device)
        return vfds
