"""Regression tests for deterministic L5X tag where-used queries."""

import asyncio
import json
import os

from l5x_analyzer.tag_cross_reference import find_tag_references
from l5x_analyzer.l5x_mcp_integration import L5XSDKMCPIntegration
from mcp_server.studio5000_mcp_server import Studio5000MCPServer, handle_mcp_request


FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
FACT_FIXTURE = os.path.join(FIXTURE_DIR, "fact_accessor.L5X")
MULTI_FIXTURE = os.path.join(FIXTURE_DIR, "multiprogram.L5X")


def test_cross_reference_classifies_program_tag_read():
    result = find_tag_references(FACT_FIXTURE, "Pumped", program_scope="Heater1")

    assert result["success"] is True
    assert result["summary"]["reads"] == 1
    assert result["summary"]["writes"] == 0
    assert result["references"][0]["role"] == "READ_SOURCE"
    assert result["references"][0]["program"] == "Heater1"
    assert result["references"][0]["routine"] == "Logic"
    assert result["references"][0]["rung_number"] == 3


def test_cross_reference_resolves_member_operand_and_write_role():
    result = find_tag_references(MULTI_FIXTURE, "Ctl_Tag_A")

    assert result["success"] is True
    assert result["summary"]["writes"] == 1
    reference = result["references"][0]
    assert reference["program"] == "Alpha"
    assert reference["resolved_tag"] == "Ctl_Tag_A.0"
    assert reference["instruction"] == "OTE"
    assert reference["role"] == "WRITE_DESTINATION"


def test_cross_reference_rejects_ambiguous_scope():
    result = find_tag_references(FACT_FIXTURE, "Shared_Name")

    assert result["success"] is False
    assert "ambiguous" in result["error"].lower()

    program_result = find_tag_references(
        FACT_FIXTURE, "Shared_Name", program_scope="Heater1"
    )
    assert program_result["success"] is True
    assert program_result["scope"] == "Program"
    assert program_result["tag_program"] == "Heater1"
    assert program_result["program_scope"] == "Heater1"


def test_cross_reference_mcp_registration_and_dispatch():
    server = Studio5000MCPServer(doc_root=".")
    listed = asyncio.run(handle_mcp_request(server, {
        "jsonrpc": "2.0", "id": 1, "method": "tools/list",
    }))
    tools = {tool["name"]: tool for tool in listed["result"]["tools"]}
    assert "find_tag_references" in tools
    assert tools["find_tag_references"]["inputSchema"]["required"] == [
        "l5x_file_path", "tag_name"
    ]

    # Avoid loading the optional sentence-transformer model while exercising
    # the pure structural handler.
    server._l5x_integration = L5XSDKMCPIntegration()
    response = asyncio.run(handle_mcp_request(server, {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "find_tag_references",
            "arguments": {
                "l5x_file_path": FACT_FIXTURE,
                "tag_name": "Pumped",
                "program_scope": "Heater1",
            },
        },
    }))
    payload = json.loads(response["result"]["content"][0]["text"])
    assert payload["success"] is True
    assert payload["summary"]["total"] == 1
