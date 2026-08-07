import xml.etree.ElementTree as ET
from l5x_analyzer.aoi_logic_inspector import inspect_aoi_definition, AOILogicRegistry

def test_aoi_logic_inspector_parses_parameters_and_routines():
    aoi_xml = """
    <AddOnInstructionDefinition Name="SCP" Revision="1.0">
      <Description>Scale with Parameters</Description>
      <Parameters>
        <Parameter Name="In" DataType="REAL" Usage="Input"/>
        <Parameter Name="InRawMin" DataType="REAL" Usage="Input"/>
        <Parameter Name="InRawMax" DataType="REAL" Usage="Input"/>
        <Parameter Name="ScaledMin" DataType="REAL" Usage="Input"/>
        <Parameter Name="ScaledMax" DataType="REAL" Usage="Input"/>
        <Parameter Name="ScaledVal" DataType="REAL" Usage="Output">
          <Description>Scaled engineering unit output value</Description>
        </Parameter>
      </Parameters>
      <Routines>
        <Routine Name="Logic">
          <Rung Number="0">
            <Text>CPT(ScaledVal, (In - InRawMin) * (ScaledMax - ScaledMin) / (InRawMax - InRawMin) + ScaledMin);</Text>
          </Rung>
        </Routine>
      </Routines>
    </AddOnInstructionDefinition>
    """
    elem = ET.fromstring(aoi_xml)
    profile = inspect_aoi_definition(elem)

    assert profile.aoi_name == "SCP"
    assert profile.get_primary_scada_output() == "ScaledVal"
    assert profile.scaling_profile.is_scaling_aoi is True
    assert profile.scaling_profile.scaled_output_param == "ScaledVal"
