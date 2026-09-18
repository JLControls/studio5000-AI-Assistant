# Secure Deserialization & Vector Cache Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status:** Partial implementation. Current vector stores already use JSON/NumPy/FAISS with `allow_pickle=False`; the remaining work is a central adapter-aware cache contract and safe invalidation/cleanup.

**Goal:** Eliminate insecure pickle deserialization, standardize safe vector-cache formats, implement the remaining `SecureVectorCache` contract, add legacy rejection/migration guards, and expose cache clearing without cross-project leakage.

**Architecture:**
1. **Format Separation:**
   - Embedding arrays: `numpy.save(..., allow_pickle=False)` and `numpy.load(..., allow_pickle=False)` saving to `.npy`.
   - Chunk & Document Metadata: Serialized as standard UTF-8 JSON (`metadata.json`, `data.json`).
   - FAISS Indices: Serialized via C++ native binary format (`faiss.write_index` / `faiss.read_index`).
2. **Unified `SecureVectorCache` Engine (`src/mcp_server/cache_manager.py`):**
   - Centralized cache helper managing atomic writes, thread locks, age verification, and deserialization safety.
   - Rejects any attempt to deserialize `.pkl` files and provides safe automatic rebuilding.
3. **Data Confidentiality & Invalidation (`clear_vector_cache`):**
   - Exposes MCP tool and CLI to flush cached embeddings and customer tag/logic metadata between projects, preventing multi-tenant data leakage.

**Tech Stack:** Python 3.12, `numpy` (allow_pickle=False), `faiss-cpu`, `json`, `pathlib`, `threading`, `bandit`, `pytest`.

---

## Global Constraints

- Zero occurrences of `import pickle`, `pickle.load()`, or `pickle.dump()` in `src/`.
- All `numpy.load()` calls MUST specify `allow_pickle=False`.
- Legacy `.pkl` cache files on disk must NEVER be deserialized under any circumstance; they must be rejected or deleted.
- Vector database query performance must not degrade compared to pickle (native `.npy` + `.faiss` is faster and lighter).
- Bandit security linter (`bandit -r src -ll -ii`) must pass with 0 high-severity warnings.
- MCP `--test` smoke test must pass without requiring re-embedding or slow startup.

## Review gates before implementation

- Inventory every cache adapter before moving code into `cache_manager.py`. Preserve lazy imports and per-database metadata; the central manager must not eagerly import optional FAISS/torch dependencies.
- Cache validity must include source-artifact, model, schema, and format fingerprints. A safe serializer without invalidation can still return stale or cross-project data.
- Cleanup must operate only on explicitly registered cache directories/files, refuse symlink escapes, and never recursively delete a broad user cache root.
- Keep malicious-pickle rejection as a direct unit test. Run Bandit as a CI/security command rather than invoking a subprocess from the normal pytest suite.

---

## File Map

### Create:
- `tests/security/test_secure_cache.py` — Unit tests for secure serialization, malicious pickle exploit prevention, and cache invalidation.
- `tests/security/test_bandit_scan.py` — Automated test ensuring Bandit security linter runs clean across `src/`.

### Modify:
- `src/mcp_server/cache_manager.py` — Implement `SecureVectorCache` with atomic save/load and thread-safe lock management.
- `src/documentation/instruction_vector_db.py` — Replace `.pkl` loading with `SecureVectorCache` (`.npy`, `.json`, `.faiss`).
- `src/drawings_analyzer/pdf_vector_db.py` — Replace `.pkl` loading with `SecureVectorCache`.
- `src/l5x_analyzer/l5x_vector_db.py` — Replace `.pkl` loading with `SecureVectorCache`.
- `src/sdk_documentation/sdk_vector_db.py` — Replace `.pkl` loading with `SecureVectorCache`.
- `src/tag_analyzer/tag_vector_db.py` — Replace `.pkl` loading with `SecureVectorCache`.
- `src/mcp_server/studio5000_mcp_server.py` — Register `clear_vector_cache` MCP tool and secure instruction index cache.
- `tests/test_mcp_workaround_fixes.py` — Schema tests for `clear_vector_cache`.

### Do Not Modify:
- `tests/test_direct_acd_deliverables.py` (preserve existing worktree changes).

---

## Task-by-Task Implementation Plan

### Task 1: Build Unified `SecureVectorCache` in `src/mcp_server/cache_manager.py`

**Files:**
- Modify: `src/mcp_server/cache_manager.py`
- Create: `tests/security/test_secure_cache.py`

**Interfaces:**
```python
class SecureVectorCache:
    """Safe vector database serialization without Python pickle."""

    @staticmethod
    def save(
        cache_dir: Path,
        index: Optional[faiss.Index],
        embeddings: Optional[np.ndarray],
        metadata: List[Dict[str, Any]],
        metadata_filename: str = "metadata.json"
    ) -> None: ...

    @staticmethod
    def load(
        cache_dir: Path,
        metadata_filename: str = "metadata.json",
        load_index: bool = True,
        load_embeddings: bool = True
    ) -> Tuple[Optional[faiss.Index], Optional[np.ndarray], List[Dict[str, Any]]]: ...

    @staticmethod
    def is_cache_valid(
        cache_dir: Path,
        metadata_filename: str = "metadata.json",
        max_age_days: int = 30
    ) -> bool: ...

    @staticmethod
    def clear(cache_dir: Path) -> int:
        """Securely wipe cache files from disk and return count of deleted files."""
```

- [ ] **Step 1: Write failing unit test for `SecureVectorCache`.**
  In `tests/security/test_secure_cache.py`:
  - Test saving index, embeddings array, and metadata dictionary to a temporary directory.
  - Verify files created are `index.faiss`, `embeddings.npy`, `metadata.json`.
  - Test loading back data and verify array values and metadata match.
  - Verify attempting to pass corrupted or pickle-based files with `allow_pickle=False` raises `ValueError` / `SecurityError` rather than executing code.

- [ ] **Step 2: Run test to confirm failure.**
  ```bash
  python -m pytest tests/security/test_secure_cache.py -v
  ```

- [ ] **Step 3: Implement `SecureVectorCache` in `src/mcp_server/cache_manager.py`.**
  - Implement atomic file writing (write to temp file then rename).
  - Enforce `np.save(..., allow_pickle=False)` and `np.load(..., allow_pickle=False)`.
  - Use `json.dump(..., ensure_ascii=False, indent=2)` and `json.load()` for chunk metadata.
  - Use `faiss.write_index()` and `faiss.read_index()` for native C++ index serialization.
  - Implement legacy `.pkl` rejection: if `.pkl` files are found, log a warning and return cache invalid (`is_valid = False`), never calling `pickle.load`.

- [ ] **Step 4: Verify `test_secure_cache.py` passes.**
  ```bash
  python -m pytest tests/security/test_secure_cache.py -v
  ```

---

### Task 2: Refactor Documentation & SDK Vector Databases

**Files:**
- Modify: `src/documentation/instruction_vector_db.py`
- Modify: `src/sdk_documentation/sdk_vector_db.py`

- [ ] **Step 1: Write failing tests verifying secure format in documentation DBs.**
  In `tests/security/test_secure_cache.py`, add tests asserting that `InstructionVectorDB` and `SDKVectorDB` save/load `.npy` and `.json` files and operate without `pickle`.

- [ ] **Step 2: Refactor `instruction_vector_db.py`.**
  - Remove all `pickle` imports.
  - Update `_save_to_cache()` to save `instructions_data.json`, `embeddings.npy`, and `index.faiss`.
  - Update `_load_from_cache()` to load via `SecureVectorCache`.
  - Add rejection for legacy `instruction_data.pkl` / `instruction_embeddings.pkl`.

- [ ] **Step 3: Refactor `sdk_vector_db.py`.**
  - Remove all `pickle` imports.
  - Update `_save_to_cache()` and `_load_from_cache()` to use `SecureVectorCache`.
  - Add rejection for legacy `sdk_chunks.pkl`.

- [ ] **Step 4: Verify documentation vector DB tests pass.**
  ```bash
  python -m pytest tests/security/test_secure_cache.py -k "doc or sdk" -v
  ```

---

### Task 3: Refactor Tag, Drawing, and L5X Vector Databases

**Files:**
- Modify: `src/tag_analyzer/tag_vector_db.py`
- Modify: `src/drawings_analyzer/pdf_vector_db.py`
- Modify: `src/l5x_analyzer/l5x_vector_db.py`

- [ ] **Step 1: Write failing tests verifying secure format in tag, drawing, and L5X DBs.**
  In `tests/security/test_secure_cache.py`, add tests asserting `TagVectorDB`, `PDFVectorDB`, and `L5XVectorDB` serialize using `SecureVectorCache` without pickle.

- [ ] **Step 2: Refactor `tag_vector_db.py`.**
  - Remove any legacy `pickle` usages in `_save_to_cache` and `_load_from_cache`.
  - Ensure `_tag_chunk_to_dict` / `_tag_chunk_from_dict` cleanly serialize all `TagChunk` fields (including `DeviceInfo` and metadata) to JSON.
  - Ensure embeddings use `np.save(..., allow_pickle=False)`.

- [ ] **Step 3: Refactor `pdf_vector_db.py`.**
  - Remove all `pickle` usages.
  - Implement JSON serialization helper for PDF drawing chunks and symbol elements.
  - Save embeddings to `embeddings.npy` with `allow_pickle=False`.

- [ ] **Step 4: Refactor `l5x_vector_db.py`.**
  - Remove all `pickle` usages.
  - Implement JSON serialization helper for `L5XChunk` data.
  - Save embeddings to `embeddings.npy` with `allow_pickle=False`.

- [ ] **Step 5: Run tests and verify.**
  ```bash
  python -m pytest tests/security/test_secure_cache.py -v
  ```

---

### Task 4: Refactor Instruction Index Cache in `studio5000_mcp_server.py`

**Files:**
- Modify: `src/mcp_server/studio5000_mcp_server.py`

- [ ] **Step 1: Check `build_instruction_index` cache format.**
  In `src/mcp_server/studio5000_mcp_server.py:260-289`, verify `instruction_index_cache.json` uses safe UTF-8 JSON parsing. Ensure no fallback to `.pkl` exists.

- [ ] **Step 2: Add validation guard and error handling.**
  Ensure that if `instruction_index_cache.json` is corrupted or modified, it gracefully falls back to re-parsing HTML docs without failing the server.

- [ ] **Step 3: Test MCP server startup.**
  ```bash
  python src/mcp_server/studio5000_mcp_server.py --test
  ```

---

### Task 5: Implement `clear_vector_cache` MCP Tool & Confidentiality Management

**Files:**
- Modify: `src/mcp_server/studio5000_mcp_server.py`
- Modify: `tests/test_mcp_workaround_fixes.py`
- Modify: `tests/security/test_secure_cache.py`

**Interfaces:**
```json
{
  "name": "clear_vector_cache",
  "description": "Securely removes cached vector indices, embeddings, and customer metadata from disk to protect customer confidentiality between projects.",
  "parameters": {
    "type": "object",
    "properties": {
      "cache_type": {
        "type": "string",
        "enum": ["ALL", "L5X", "TAG_CSV", "PDF_DRAWINGS", "DOCS", "SDK"],
        "default": "ALL"
      }
    }
  }
}
```

- [ ] **Step 1: Write failing schema and unit tests for `clear_vector_cache`.**
  - In `tests/test_mcp_workaround_fixes.py`: assert `clear_vector_cache` is exposed in `tools/list` with enum `["ALL", "L5X", "TAG_CSV", "PDF_DRAWINGS", "DOCS", "SDK"]`.
  - In `tests/security/test_secure_cache.py`: create mock caches for all types, call `clear_vector_cache(cache_type="ALL")`, assert disk files deleted and in-memory caches reset.

- [ ] **Step 2: Run tests to confirm failure.**
  ```bash
  python -m pytest tests/security/test_secure_cache.py -k "clear" -v
  ```

- [ ] **Step 3: Implement `clear_vector_cache` handler and server wiring.**
  In `src/mcp_server/studio5000_mcp_server.py`:
  - Add `clear_vector_cache` method to `Studio5000MCPServer`.
  - Map `cache_type` to relevant cache directories (`l5x_vector_cache/`, `tag_vector_cache/`, `pdf_drawings_vector_cache/`, `instruction_vector_cache/`, `sdk_vector_cache/`, `~/.cache/studio5000/`).
  - Delete cached files safely and reset corresponding server instance attributes (`self._tag_integration = None`, `self.instructions = None`, etc.).
  - Return JSON status reporting deleted file count and cleared subsystems.

- [ ] **Step 4: Verify schema and invalidation tests pass.**
  ```bash
  python -m pytest tests/security/test_secure_cache.py tests/test_mcp_workaround_fixes.py -v
  ```

---

### Task 6: Security Vulnerability Exploit Testing & Bandit Automated Verification

**Files:**
- Create: `tests/security/test_bandit_scan.py`
- Modify: `tests/security/test_secure_cache.py`

- [ ] **Step 1: Implement malicious pickle payload test.**
  In `tests/security/test_secure_cache.py`:
  - Construct a malicious Python object implementing `__reduce__` that writes a sentinel marker file if unpickled.
  - Save payload to a fake `.pkl` in cache directory.
  - Attempt to load vector database from directory.
  - Assert marker file is NEVER created, and loader raises `SecurityError` or safely ignores `.pkl` and rebuilds clean.

- [ ] **Step 2: Implement Bandit security AST test.**
  In `tests/security/test_bandit_scan.py`:
  - Run `bandit -r src -ll -ii` via subprocess.
  - Assert returncode is 0 and 0 high-severity security issues are detected.

- [ ] **Step 3: Run full security test suite.**
  ```bash
  python -m pytest tests/security/ -v
  ```

---

## Verification Commands

```bash
# 1. Run all security and cache tests
python -m pytest tests/security/ -v

# 2. Run Bandit security scan across src/
bandit -r src -ll -ii

# 3. Run MCP server smoke test
python src/mcp_server/studio5000_mcp_server.py --test

# 4. Run full pytest suite
python -m pytest -q
```
