"""Unit tests for code assistant regex parsing, ST generation, and modernized analyzer features."""

import unittest
from ai_assistant.code_assistant import NaturalLanguageParser, LadderLogicGenerator, PLCRequirement
from code_generator.l5x_generator import L5XGenerator, Routine, LadderRung


class CodeAssistantRegexAndSTTest(unittest.TestCase):
    def setUp(self):
        self.parser = NaturalLanguageParser()
        self.generator = LadderLogicGenerator()

    def test_extract_time_values_ms_and_sec_and_min(self):
        self.assertEqual(self.generator._extract_time_value("Delay for 500 ms"), 500)
        self.assertEqual(self.generator._extract_time_value("Wait 5 seconds before starting"), 5000)
        self.assertEqual(self.generator._extract_time_value("Run timer for 10 s"), 10000)
        self.assertEqual(self.generator._extract_time_value("Keep running for 2 min"), 120000)
        self.assertEqual(self.generator._extract_time_value("No time specified"), 5000)

    def test_extract_numeric_value(self):
        self.assertEqual(self.generator._extract_numeric_value("Count up to 42 parts"), 42)
        self.assertEqual(self.generator._extract_numeric_value("Cycle count 100"), 100)
        self.assertEqual(self.generator._extract_numeric_value("No number", default=7), 7)

    def test_extract_conditions_regex(self):
        conditions = self.parser._extract_conditions("IF pressure is high THEN open valve")
        self.assertTrue(len(conditions) > 0)
        self.assertTrue(any("pressure is high" in c for c in conditions))

    def test_structured_text_start_stop(self):
        req = PLCRequirement(
            description="Start the motor when start button pressed and stop when stop button pressed",
            inputs=["START_PB", "STOP_PB"],
            outputs=["MOTOR_RUN"],
            logic_type="structured_text"
        )
        code = self.generator.generate_from_requirements(req)
        self.assertIn("IF START_PB AND NOT STOP_PB THEN", code.ladder_logic)
        self.assertIn("MOTOR_RUN := TRUE;", code.ladder_logic)
        self.assertIn("ELSIF STOP_PB THEN", code.ladder_logic)

    def test_structured_text_timer(self):
        req = PLCRequirement(
            description="Delay 2500 ms after sensor triggers before activating buzzer",
            inputs=["SENSOR_IN"],
            outputs=["BUZZER_OUT"],
            logic_type="structured_text"
        )
        code = self.generator.generate_from_requirements(req)
        self.assertIn("DELAY_TIMER.PRE := 2500;", code.ladder_logic)
        self.assertIn("TONR(DELAY_TIMER);", code.ladder_logic)
        self.assertIn("BUZZER_OUT := DELAY_TIMER.DN;", code.ladder_logic)
        self.assertTrue(any(t["name"] == "DELAY_TIMER" and t["data_type"] == "TIMER" for t in code.tags))

    def test_structured_text_counter(self):
        req = PLCRequirement(
            description="Count 15 parts before stopping conveyor",
            inputs=["PART_SENSOR", "RESET_PB"],
            outputs=["CONVEYOR_STOP"],
            logic_type="structured_text"
        )
        code = self.generator.generate_from_requirements(req)
        self.assertIn("COUNTER.PRE := 15;", code.ladder_logic)
        self.assertIn("CTU(COUNTER);", code.ladder_logic)
        self.assertTrue(any(t["name"] == "COUNTER" and t["data_type"] == "COUNTER" for t in code.tags))

    def test_structured_text_sequence(self):
        req = PLCRequirement(
            description="Sequence state machine for packaging step",
            inputs=["START_PB", "PROCESS_DONE"],
            outputs=["PROCESS_ACTIVE"],
            logic_type="structured_text"
        )
        code = self.generator.generate_from_requirements(req)
        self.assertIn("CASE STEP_NUMBER OF", code.ladder_logic)
        self.assertIn("END_CASE;", code.ladder_logic)

    def test_structured_text_interlock(self):
        req = PLCRequirement(
            description="Safety interlock fault protection for hydraulic press",
            inputs=["E_STOP_OK", "OVERLOAD_FAULT"],
            outputs=["PRESS_ENABLE"],
            logic_type="structured_text"
        )
        code = self.generator.generate_from_requirements(req)
        self.assertIn("IF E_STOP_OK AND NOT OVERLOAD_FAULT THEN", code.ladder_logic)
        self.assertIn("PRESS_ENABLE := TRUE;", code.ladder_logic)

    def test_st_routine_multiline_xml_generation(self):
        gen = L5XGenerator()
        st_logic = "MOTOR_RUN := TRUE;\nDELAY_TIMER.PRE := 5000;\nTONR(DELAY_TIMER);"
        routine = Routine(
            name="ST_Logic",
            type="ST",
            rungs=[LadderRung(number=0, logic=st_logic, comment="Main ST Logic")]
        )
        xml = gen.generate_routine(routine)
        self.assertIn('<STContent>', xml)
        self.assertIn('<Line Number="0">', xml)
        self.assertIn('<Line Number="1">', xml)
        self.assertIn('<Line Number="2">', xml)
        self.assertIn('<![CDATA[MOTOR_RUN := TRUE;]]>', xml)


if __name__ == "__main__":
    unittest.main()
