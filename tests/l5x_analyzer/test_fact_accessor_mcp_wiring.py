"""MCP wiring tests for the issue #28 fact-accessor tools.

Guards the three registration touch-points the server requires: an ``add_tool``
registration, a ``tools/list`` input schema, and a working ``tools/call``
dispatch that reaches the accessor and returns real bindings.
"""
import asyncio
import json
import os

from mcp_server.studio5000_mcp_server import Studio5000MCPServer, handle_mcp_request

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "fact_accessor.L5X")

NEW_TOOLS = ("get_tag_value", "describe_aoi", "decode_aoi_call")


def _tools_list():
    server = Studio5000MCPServer(doc_root=".")
    req = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    resp = asyncio.run(handle_mcp_request(server, req))
    return resp["result"]["tools"]


def test_new_tools_listed_with_schema():
    tools = {t["name"]: t for t in _tools_list()}
    for name in NEW_TOOLS:
        assert name in tools, f"{name} missing from tools/list"

    assert set(tools["get_tag_value"]["inputSchema"]["required"]) == {
        "l5x_file_path", "tag_name",
    }
    assert set(tools["describe_aoi"]["inputSchema"]["required"]) == {
        "l5x_file_path", "aoi_name",
    }
    assert set(tools["decode_aoi_call"]["inputSchema"]["required"]) == {
        "l5x_file_path", "routine_name", "rung_number",
    }


def test_tools_call_decode_aoi_call_roundtrip():
    server = Studio5000MCPServer(doc_root=".")
    req = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "decode_aoi_call",
            "arguments": {
                "l5x_file_path": FIXTURE,
                "routine_name": "Logic",
                "rung_number": 0,
                "program_name": "Heater1",
            },
        },
    }
    resp = asyncio.run(handle_mcp_request(server, req))
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload["success"] is True
    binding = {b["param_name"]: b for b in payload["calls"][0]["bindings"]}
    assert binding["In"]["operand"] == "Raw_In"
