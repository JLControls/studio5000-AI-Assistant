"""Tests for structural project overview (issue #9).

These verify that project structure is captured at index time and that
``get_project_overview`` reports it deterministically without ever falling back
to a semantic/vector search.
"""
import asyncio
import os
import shutil

from l5x_analyzer.l5x_vector_db import L5XVectorDatabase
from l5x_analyzer.l5x_mcp_integration import L5XSDKMCPIntegration

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
FIXTURE_FILE = os.path.join(FIXTURE_DIR, "multiprogram.L5X")


def _no_semantic_search(*args, **kwargs):
    raise AssertionError("get_project_overview must not run a semantic search")


def test_exported_indexing_captures_structure(tmp_path, monkeypatch):
    """Indexing exported L5X files records a deterministic structure blob."""
    # Isolate the fixture into its own directory so the project name is stable.
    proj_dir = tmp_path / "MyProj"
    proj_dir.mkdir()
    shutil.copy(FIXTURE_FILE, proj_dir / "multiprogram.L5X")

    vdb = L5XVectorDatabase(cache_dir=str(tmp_path / "cache"))
    # Structural capture must not depend on embeddings being built.
    monkeypatch.setattr(vdb, "build_vector_database", lambda *a, **k: None)

    assert vdb.index_exported_l5x_files(str(proj_dir), force_rebuild=True) is True

    structure = vdb.indexed_projects["MyProj"]["structure"]
    assert sorted(structure["programs"]) == ["Alpha", "Beta", "Gamma"]
    assert len(structure["routines"]) == 5
    assert structure["udts"] == ["MyUDT"]


def test_overview_reports_structural_counts_without_semantic_search(tmp_path, monkeypatch):
    vdb = L5XVectorDatabase(cache_dir=str(tmp_path / "cache"))
    vdb.indexed_projects["MyProj"] = {
        "file_count": 1,
        "chunk_count": 42,
        "structure": {
            "controller": "TestCtl",
            "programs": ["Alpha", "Beta", "Gamma"],
            "routines": [
                {"program": "Alpha", "name": "Logic", "type": "RLL", "encoded": False},
                {"program": "Alpha", "name": "Init", "type": "RLL", "encoded": False},
                {"program": "Beta", "name": "MainRoutine", "type": "RLL", "encoded": False},
                {"program": "Beta", "name": "Secret", "type": "RLL", "encoded": True},
                {"program": "Gamma", "name": "Logic", "type": "RLL", "encoded": False},
            ],
            "udts": ["MyUDT"],
        },
    }
    integration = L5XSDKMCPIntegration(vector_db=vdb)
    # Any semantic search during overview is a regression.
    monkeypatch.setattr(vdb, "search_l5x_content", _no_semantic_search)

    result = asyncio.run(integration.get_project_overview("MyProj.L5X"))

    assert result["success"] is True
    assert result["overview"]["program_count"] == 3
    assert result["overview"]["routine_count"] == 5
    assert result["overview"]["udt_count"] == 1
    assert result["controller"] == "TestCtl"


def test_overview_counts_duplicate_named_routines(tmp_path, monkeypatch):
    vdb = L5XVectorDatabase(cache_dir=str(tmp_path / "cache"))
    vdb.indexed_projects["MyProj"] = {
        "structure": {
            "controller": "TestCtl",
            "programs": ["Alpha", "Gamma"],
            "routines": [
                {"program": "Alpha", "name": "Logic", "type": "RLL", "encoded": False},
                {"program": "Gamma", "name": "Logic", "type": "RLL", "encoded": False},
            ],
            "udts": [],
        },
    }
    integration = L5XSDKMCPIntegration(vector_db=vdb)
    monkeypatch.setattr(vdb, "search_l5x_content", _no_semantic_search)

    result = asyncio.run(integration.get_project_overview("MyProj.L5X"))

    assert result["overview"]["routine_count"] == 2
    identities = {(r["program"], r["name"]) for r in result["routine_details"]}
    assert identities == {("Alpha", "Logic"), ("Gamma", "Logic")}


def test_overview_surfaces_add_on_and_module_inventory(tmp_path, monkeypatch):
    vdb = L5XVectorDatabase(cache_dir=str(tmp_path / "cache"))
    vdb.indexed_projects["MyProj"] = {
        "structure": {
            "controller": "TestCtl",
            "programs": ["Alpha"],
            "routines": [{"program": "Alpha", "name": "Logic", "type": "RLL", "encoded": False}],
            "udts": ["MyUDT"],
            "add_on_instructions": ["Scale"],
            "modules": [
                {"name": "Local", "catalog": "5069-L306ER", "parent": "Local", "slot": "0"},
                {"name": "AI_Module", "catalog": "5069-IF8/A", "parent": "Local", "slot": "2"},
            ],
        },
    }
    integration = L5XSDKMCPIntegration(vector_db=vdb)
    monkeypatch.setattr(vdb, "search_l5x_content", _no_semantic_search)

    result = asyncio.run(integration.get_project_overview("MyProj.L5X"))

    assert result["overview"]["add_on_instruction_count"] == 1
    assert result["overview"]["module_count"] == 2
    assert result["add_on_instructions"] == ["Scale"]
    assert {m["name"] for m in result["modules"]} == {"Local", "AI_Module"}


def test_stale_cache_without_structure_requires_reindex(tmp_path, monkeypatch):
    vdb = L5XVectorDatabase(cache_dir=str(tmp_path / "cache"))
    # Legacy cache entry: no 'structure' key.
    vdb.indexed_projects["MyProj"] = {"file_count": 1, "chunk_count": 10}
    integration = L5XSDKMCPIntegration(vector_db=vdb)
    monkeypatch.setattr(vdb, "search_l5x_content", _no_semantic_search)

    result = asyncio.run(integration.get_project_overview("MyProj.L5X"))

    assert result["success"] is False
    assert "re-index" in result["error"].lower()


def test_overview_rejects_unindexed_project_instead_of_using_first_cache(tmp_path):
    vdb = L5XVectorDatabase(cache_dir=str(tmp_path / "cache"))
    vdb.indexed_projects["OtherProject"] = {
        "structure": {
            "controller": "OtherCtl",
            "programs": [],
            "routines": [],
            "udts": [],
        },
    }
    integration = L5XSDKMCPIntegration(vector_db=vdb)

    result = asyncio.run(integration.get_project_overview("RequestedProject.L5X"))

    assert result["success"] is False
    assert "RequestedProject" in result["error"]
    assert "index_exported_l5x_files" in result["error"]
    assert "OtherCtl" not in result.get("controller", "")


def test_acd_indexing_captures_same_structure_shape(tmp_path, monkeypatch):
    """The ACD path must persist the same structure blob as exported-L5X indexing."""
    vdb = L5XVectorDatabase(cache_dir=str(tmp_path / "cache"))

    # Stand in for the offline ACD->L5X conversion by writing the fixture into
    # the temp L5X path the indexer chose.
    import l5x_analyzer.acd_offline_convert as conv

    def fake_convert(acd_path, l5x_path, pretty=False):
        shutil.copy(FIXTURE_FILE, l5x_path)
        return {"success": True}

    from l5x_analyzer.sdk_powered_analyzer import SDKPoweredL5XAnalyzer
    vdb.sdk_analyzer = SDKPoweredL5XAnalyzer()

    monkeypatch.setattr(conv, "convert_acd_to_l5x", fake_convert)
    monkeypatch.setattr(vdb, "build_vector_database", lambda *a, **k: None)
    monkeypatch.setattr(vdb.sdk_analyzer, "parse_routine_l5x", lambda *a, **k: [])

    ok = asyncio.run(vdb.index_acd_project(str(tmp_path / "Widget.ACD"), force_rebuild=True))
    assert ok is True

    structure = vdb.indexed_projects["Widget"]["structure"]
    assert sorted(structure["programs"]) == ["Alpha", "Beta", "Gamma"]
    assert len(structure["routines"]) == 5
