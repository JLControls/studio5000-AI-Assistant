import importlib
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
VENDORED_ACD = REPO_ROOT / "src" / "acd"


def test_acd_package_resolves_from_repository_source_tree():
    acd = importlib.import_module("acd")

    assert Path(acd.__file__).resolve().is_relative_to(VENDORED_ACD.resolve())


def test_converter_does_not_depend_on_external_acd_source(monkeypatch):
    monkeypatch.setenv("ACD_TOOLS_SOURCE", str(REPO_ROOT / "missing-acd-source"))
    converter = importlib.import_module("l5x_analyzer.acd_offline_convert")

    converter._apply_runtime_compatibility()
