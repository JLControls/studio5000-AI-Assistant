import json
import pytest
from pathlib import Path
from tag_analyzer.comment_pipeline import PLCCommentPipeline
from tag_analyzer.tag_mcp_integration import TagMCPIntegration
from mcp_server.studio5000_mcp_server import Studio5000MCPServer, handle_mcp_request

@pytest.fixture
def tmp_work_dir(tmp_path):
    return tmp_path

def test_generate_deliverables_decisions_path(tmp_work_dir):
    pipeline = PLCCommentPipeline()
    decisions = [
        {
            "TYPE": "TAG",
            "SCOPE": "",
            "NAME": "TestTag1",
            "PROPOSED_DESCRIPTION": "Test description 1",
            "CONFIDENCE": "HIGH",
            "STATUS": "inferred",
        }
    ]
    dec_file = tmp_work_dir / "my_decisions.json"
    dec_file.write_text(json.dumps(decisions), encoding="utf-8")

    res = pipeline.generate_deliverables(
        decisions_path=str(dec_file),
        output_dir=str(tmp_work_dir / "out"),
    )
    assert res["decisions_processed"] == 1
    assert Path(res["csv_delta"]).exists()
    assert Path(res["html_report"]).exists()
    assert Path(res["decisions_json"]).exists()

def test_generate_deliverables_work_packet_path(tmp_work_dir):
    pipeline = PLCCommentPipeline()
    packet = {
        "controller": "THAWROOM",
        "auto_decisions": [
            {
                "TYPE": "TAG",
                "SCOPE": "",
                "NAME": "AutoTag",
                "PROPOSED_DESCRIPTION": "Automatic Description",
                "CONFIDENCE": "HIGH",
                "STATUS": "inferred",
            }
        ],
        "to_resolve": [
            {
                "entity": "N101[0]",
                "draft_decision": {
                    "TYPE": "COMMENT",
                    "SCOPE": "THAWROOM",
                    "NAME": "N101[0]",
                    "PROPOSED_DESCRIPTION": "Thaw room enable bit",
                    "CONFIDENCE": "MEDIUM",
                    "STATUS": "inferred",
                },
            },
            {
                "entity": "N101[1]",
                "draft_decision": {
                    "TYPE": "COMMENT",
                    "SCOPE": "THAWROOM",
                    "NAME": "N101[1]",
                    "PROPOSED_DESCRIPTION": "",  # Unauthored draft, should be skipped
                    "CONFIDENCE": "",
                    "STATUS": "inferred",
                },
            },
        ],
    }
    pkt_file = tmp_work_dir / "work_packet.json"
    pkt_file.write_text(json.dumps(packet), encoding="utf-8")

    res = pipeline.generate_deliverables(
        work_packet_path=str(pkt_file),
        output_dir=str(tmp_work_dir / "out"),
    )
    assert res["decisions_processed"] == 2  # 1 auto + 1 authored draft
    assert res["skipped_unauthored_drafts"] == 1
    assert Path(res["csv_delta"]).exists()

def test_comment_row_name_specifier_split_and_cp1252_safe(tmp_work_dir):
    pipeline = PLCCommentPipeline()
    decisions = [
        {
            "TYPE": "COMMENT",
            "SCOPE": "THAWROOM",
            "NAME": "N101[20].1",
            "PROPOSED_DESCRIPTION": "Master Enable → Active (≥ 50°C)",
            "CONFIDENCE": "HIGH",
            "STATUS": "inferred",
        }
    ]
    res = pipeline.generate_deliverables(
        decisions=decisions,
        output_dir=str(tmp_work_dir / "out"),
    )
    csv_file = Path(res["csv_delta"])
    content = csv_file.read_text(encoding="cp1252")
    # Verify split of N101[20].1 into NAME=N101 and SPECIFIER=[20].1
    # Line format: COMMENT,THAWROOM,N101,"Master Enable -> Active (>= 50degC)",,[20].1,
    assert "COMMENT,THAWROOM,N101," in content
    assert "[20].1" in content
    assert "->" in content
    assert ">=" in content
    assert "degC" in content

def test_tools_list_schema_contains_generate_program_comments():
    server = Studio5000MCPServer(doc_root=".")
    req = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    import asyncio
    resp = asyncio.run(handle_mcp_request(server, req))
    tools = resp["result"]["tools"]
    gen_prog = next((t for t in tools if t["name"] == "generate_program_comments"), None)
    assert gen_prog is not None
    assert "acd_path" in gen_prog["inputSchema"]["properties"]
    assert "acd_path" in gen_prog["inputSchema"]["required"]

    gen_del = next((t for t in tools if t["name"] == "generate_comment_deliverables"), None)
    assert gen_del is not None
    assert "work_packet_path" in gen_del["inputSchema"]["properties"]
    assert "decisions_path" in gen_del["inputSchema"]["properties"]
