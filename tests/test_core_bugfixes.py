"""Regression coverage for the remaining PLAN-11 core reliability fixes."""

import ast
import asyncio
import io
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from ai_assistant.code_assistant import LadderLogicGenerator, PLCRequirement
from ai_assistant.enhanced_code_assistant import IndustrialInstructionMapper
from ai_assistant.enhanced_ladder_generator import EnhancedLadderLogicGenerator
from code_generator.l5x_generator import L5XGenerator, LadderRung, Routine
from l5x_analyzer.l5x_mcp_integration import L5XSDKMCPIntegration
from l5x_analyzer.l5x_vector_db import L5XVectorDatabase
from mcp_server import studio5000_mcp_server
from mcp_server.studio5000_mcp_server import MCPServer, Studio5000MCPServer, handle_mcp_request
from verification.sdk_verifier import SDKVerifier


def test_bug04_get_project_overview_rejects_missing_project_with_available_projects(tmp_path):
    vector_db = L5XVectorDatabase(cache_dir=str(tmp_path / "cache"))
    vector_db.indexed_projects["Kemco_HA105"] = {
        "file_count": 1,
        "chunk_count": 20,
        "structure": {
            "controller": "Kemco_Ctl",
            "programs": ["MainProgram"],
            "routines": [],
            "udts": [],
        },
    }
    integration = L5XSDKMCPIntegration(vector_db=vector_db)

    result = asyncio.run(integration.get_project_overview("UnindexedProject.L5X"))

    assert result["success"] is False
    assert "UnindexedProject" in result["error"]
    assert "Kemco_HA105" in result["error"]
    assert "Kemco_Ctl" not in result.get("controller", "")


def test_bug06_all_diagnostic_prints_in_target_modules_use_stderr():
    source_root = Path(__file__).parents[1] / "src"
    module_paths = [
        source_root / "code_generator" / "l5x_generator.py",
        source_root / "ai_assistant" / "code_assistant.py",
        source_root / "ai_assistant" / "enhanced_main_assistant.py",
        source_root / "drawings_analyzer" / "pdf_parser.py",
        source_root / "documentation" / "instruction_vector_db.py",
    ]

    violations = []
    for path in module_paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Name) or node.func.id != "print":
                continue
            file_keyword = next((keyword for keyword in node.keywords if keyword.arg == "file"), None)
            if file_keyword is None or not isinstance(file_keyword.value, ast.Attribute):
                violations.append(f"{path}:{node.lineno}")
                continue
            if not (
                isinstance(file_keyword.value.value, ast.Name)
                and file_keyword.value.value.id == "sys"
                and file_keyword.value.attr == "stderr"
            ):
                violations.append(f"{path}:{node.lineno}")

    assert violations == [], f"Diagnostic print calls can pollute MCP stdout: {violations}"


def test_bug06_l5x_generator_error_does_not_pollute_stdout(monkeypatch, tmp_path):
    captured_stdout = io.StringIO()
    captured_stderr = io.StringIO()
    monkeypatch.setattr(sys, "stdout", captured_stdout)
    monkeypatch.setattr(sys, "stderr", captured_stderr)

    result = L5XGenerator().save_routine_export(
        Routine(name="TestRoutine", type="RLL", rungs=[]),
        str(tmp_path / "nonexistent_dir" / "out.L5X"),
    )

    assert result is False
    assert captured_stdout.getvalue() == ""
    assert "Error saving routine export" in captured_stderr.getvalue()


def test_bug06_mcp_subprocess_stdout_contains_only_json(tmp_path):
    server_path = Path(__file__).parents[1] / "src" / "mcp_server" / "studio5000_mcp_server.py"
    request = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path(__file__).parents[1] / "src")

    completed = subprocess.run(
        [sys.executable, str(server_path), "--doc-root", str(tmp_path)],
        input=json.dumps(request) + "\n",
        text=True,
        capture_output=True,
        env=environment,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    output_lines = [line for line in completed.stdout.splitlines() if line.strip()]
    assert output_lines
    assert all(isinstance(json.loads(line), dict) for line in output_lines)
    assert "Studio 5000 MCP Server starting" in completed.stderr


def test_bug07_generator_accepts_target_program_alias_and_preserves_program_name():
    generator = L5XGenerator()
    routine = Routine(
        name="SafetyStopRoutine",
        type="RLL",
        rungs=[LadderRung(number=0, logic="XIC(E_Stop)OTE(Safety_Fault);")],
    )

    xml_output = generator.generate_routine_export(
        routine=routine,
        target_program="SafetyProgram",
    )
    legacy_xml_output = generator.generate_routine_export(
        routine=routine,
        program_name="LegacyProgram",
    )

    assert 'Name="SafetyProgram"' in xml_output
    assert 'Name="MainProgram"' not in xml_output
    assert 'Name="LegacyProgram"' in legacy_xml_output


def test_bug07_create_l5x_routine_forwards_target_program_and_schema(tmp_path):
    server = object.__new__(Studio5000MCPServer)

    class FakeAssistant:
        async def generate_ladder_logic(self, specification):
            return {
                "success": True,
                "ladder_logic": "XIC(Start)OTE(Run);",
                "tags": [],
                "instructions_used": ["XIC", "OTE"],
            }

    server.enhanced_assistant = FakeAssistant()
    server.server = MCPServer("test")
    server.server.add_tool("create_l5x_routine", "test", server.create_l5x_routine)

    result = asyncio.run(
        server.create_l5x_routine(
            {
                "name": "SafetyRoutine",
                "specification": "start safety logic",
                "target_program": "SafetyProgram",
                "save_path": str(tmp_path / "SafetyRoutine.L5X"),
            }
        )
    )
    schema_response = asyncio.run(
        handle_mcp_request(
            server,
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        )
    )
    routine_tool = next(
        tool for tool in schema_response["result"]["tools"] if tool["name"] == "create_l5x_routine"
    )

    assert result["success"] is True
    assert 'Name="SafetyProgram"' in result["l5x_content"]
    assert (tmp_path / "SafetyRoutine.L5X").read_text(encoding="utf-8") == result["l5x_content"]
    properties = routine_tool["inputSchema"]["properties"]["routine_spec"]["properties"]
    assert "target_program" in properties
    assert "program_name" in properties


def test_bug08_start_stop_logic_generates_seal_in_latch():
    requirement = PLCRequirement(
        description="Start stop motor control with start PB, stop PB, and conveyor motor output",
        inputs=["Start_PB", "Stop_PB"],
        outputs=["Motor_Run"],
    )

    code = LadderLogicGenerator().generate_from_requirements(requirement)

    assert code.ladder_logic == "[XIC(Start_PB) , XIC(Motor_Run) ]XIO(Stop_PB)OTE(Motor_Run);"
    assert "latch" in code.validation_notes[0].lower()


def test_action13_no_produce_consume_ladder_instructions():
    ladder_generator = EnhancedLadderLogicGenerator()
    code_assistant = IndustrialInstructionMapper.__new__(IndustrialInstructionMapper)
    asyncio.run(code_assistant._initialize_comprehensive_mappings())

    assert "PRODUCE" not in ladder_generator.comm_mappings.values()
    assert "CONSUME" not in ladder_generator.comm_mappings.values()
    assert "PRODUCE" not in code_assistant.comm_instructions.values()
    assert "CONSUME" not in code_assistant.comm_instructions.values()


def test_action19_python_version_guard_rejects_unsupported_runtime(monkeypatch):
    captured_stderr = io.StringIO()
    monkeypatch.setattr(sys, "stderr", captured_stderr)

    assert studio5000_mcp_server._require_python_312(
        (3, 12, 14), executable="/repo/.venv/bin/python"
    ) is True
    assert studio5000_mcp_server._require_python_312(
        (3, 13, 0), executable="/usr/bin/python3.13"
    ) is False
    assert "Python 3.12" in captured_stderr.getvalue()
    assert "3.13.0" in captured_stderr.getvalue()
    assert "/usr/bin/python3.13" in captured_stderr.getvalue()


def test_action19_main_returns_nonzero_before_initialization_on_unsupported_runtime(monkeypatch):
    captured_stderr = io.StringIO()
    monkeypatch.setattr(studio5000_mcp_server.sys, "version_info", (3, 13, 0))
    monkeypatch.setattr(studio5000_mcp_server.sys, "stderr", captured_stderr)

    assert asyncio.run(studio5000_mcp_server.main()) == 2
    assert "requires Python 3.12.x" in captured_stderr.getvalue()


def test_bug09_verifier_does_not_warn_input_only_for_standard_outputs():
    verifier = SDKVerifier()
    for ladder_logic in (
        "XIC(Run)TON(Timer1,5000,0);",
        "XIC(Enable)ADD(A,B,C);",
        "XIC(Part)MOV(Source,Destination);",
        "XIC(Count)CTU(Counter,10,0);",
    ):
        result = asyncio.run(verifier.verify_ladder_logic(ladder_logic))
        assert not [warning for warning in result.warnings if warning.code == "INPUT_ONLY"], ladder_logic


def test_bug09_verifier_still_warns_for_contact_only_rung():
    result = asyncio.run(SDKVerifier().verify_ladder_logic("XIC(Run);"))

    assert [warning.code for warning in result.warnings] == ["INPUT_ONLY"]
