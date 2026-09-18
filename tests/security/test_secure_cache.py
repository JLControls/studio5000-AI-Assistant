"""Security and isolation tests for vector-cache serialization."""

import pickle
from pathlib import Path

import numpy as np
import pytest

from mcp_server.cache_manager import (
    CacheSecurityError,
    SecureVectorCache,
    SharedCacheManager,
)


def test_secure_cache_round_trip_uses_json_and_npy(tmp_path):
    embeddings = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32)
    metadata = [{"name": "first", "tags": ["safe"]}]

    SecureVectorCache.save(tmp_path, None, embeddings, metadata)

    assert (tmp_path / "embeddings.npy").is_file()
    assert (tmp_path / "metadata.json").is_file()
    assert not list(tmp_path.glob("*.pkl"))

    index, loaded_embeddings, loaded_metadata = SecureVectorCache.load(
        tmp_path, load_index=False
    )

    assert index is None
    np.testing.assert_array_equal(loaded_embeddings, embeddings)
    assert loaded_metadata == metadata


def test_secure_cache_round_trip_faiss_index(tmp_path):
    import faiss

    index = faiss.IndexFlatIP(2)
    index.add(np.array([[1.0, 0.0]], dtype=np.float32))

    SecureVectorCache.save(tmp_path, index, None, [])
    loaded_index, embeddings, metadata = SecureVectorCache.load(
        tmp_path, load_embeddings=False
    )

    assert loaded_index.ntotal == 1
    assert embeddings is None
    assert metadata == []


def test_legacy_pickle_is_rejected_before_deserialization(tmp_path):
    marker = tmp_path / "executed.txt"

    class Malicious:
        def __reduce__(self):
            return (Path.write_text, (marker, "executed"))

    with (tmp_path / "legacy.pkl").open("wb") as stream:
        pickle.dump(Malicious(), stream)

    with pytest.raises(CacheSecurityError, match="legacy pickle"):
        SecureVectorCache.load(tmp_path)

    assert not marker.exists()


def test_legacy_pickle_makes_cache_invalid(tmp_path):
    SecureVectorCache.save(tmp_path, None, None, {"version": 1})
    (tmp_path / "old_cache.pickle").write_bytes(b"not loaded")

    assert not SecureVectorCache.is_cache_valid(tmp_path)


def test_clear_registered_caches_removes_only_known_artifacts(tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    (cache_dir / "metadata.json").write_text("{}", encoding="utf-8")
    (cache_dir / "embeddings.npy").write_bytes(b"numpy")
    (cache_dir / "old.pkl").write_bytes(b"legacy")
    unrelated = cache_dir / "notes.txt"
    unrelated.write_text("keep", encoding="utf-8")
    unrelated_json = cache_dir / "unrelated.json"
    unrelated_json.write_text("keep", encoding="utf-8")

    manager = SharedCacheManager()
    manager.register_cache_dir(cache_dir)
    result = manager.clear_registered_caches()

    assert result["deleted_files"] == 3
    assert not (cache_dir / "metadata.json").exists()
    assert not (cache_dir / "embeddings.npy").exists()
    assert not (cache_dir / "old.pkl").exists()
    assert unrelated.read_text(encoding="utf-8") == "keep"
    assert unrelated_json.read_text(encoding="utf-8") == "keep"


def test_clear_rejects_symlink_cache_directory(tmp_path):
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(real_dir, target_is_directory=True)
    except OSError as exc:  # Windows without SeCreateSymbolicLinkPrivilege
        pytest.skip(f"symlinks not creatable here: {exc}")

    with pytest.raises(ValueError, match="unsafe cache directory"):
        SecureVectorCache.clear(link)


def test_metadata_filename_cannot_escape_cache_directory(tmp_path):
    with pytest.raises(ValueError, match="single .json filename"):
        SecureVectorCache.save(tmp_path, None, None, {}, "../outside.json")
