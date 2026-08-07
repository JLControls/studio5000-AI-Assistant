import xml.etree.ElementTree as ET
from l5x_analyzer.write_analyzer import analyze_l5x_tag_writes

def test_write_analyzer_detects_destructives():
    l5x_xml = """
    <RSLogix5000Content>
      <Controller Name="TestPLC">
        <Tags>
          <Tag Name="WrittenBit" DataType="BOOL"/>
          <Tag Name="UnwrittenBit" DataType="BOOL"/>
          <Tag Name="Com_AliasDIn_Start" DataType="BOOL"/>
          <Tag Name="Com_Set_PressureSP" DataType="REAL"/>
        </Tags>
        <Programs>
          <Program Name="MainProg">
            <Routines>
              <Routine Name="MainRoutine">
                <Rung Number="0">
                  <Text>XIC(Com_AliasDIn_Start) OTE(WrittenBit);</Text>
                </Rung>
              </Routine>
            </Routines>
          </Program>
        </Programs>
      </Controller>
    </RSLogix5000Content>
    """
    root = ET.fromstring(l5x_xml)
    write_map = analyze_l5x_tag_writes(root)

    assert write_map.is_written("WrittenBit") is True
    assert write_map.is_written("Com_AliasDIn_Start") is True
    assert write_map.is_written("Com_Set_PressureSP") is True
    assert write_map.is_written("UnwrittenBit") is False
