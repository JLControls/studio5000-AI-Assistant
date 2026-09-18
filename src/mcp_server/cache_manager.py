#!/usr/bin/env python3
"""
Optimized cache manager for Studio 5000 MCP Server vector databases
Provides shared caching strategies and optimizations across all vector databases
"""

import json
import os
import tempfile
import time
import threading
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
import logging

logger = logging.getLogger(__name__)


class CacheSecurityError(RuntimeError):
    """Raised when a cache contains an unsafe legacy serialization format."""


class SecureVectorCache:
    """Serialize vector-cache data without Python object deserialization.

    The class deliberately imports NumPy and FAISS only inside the methods that
    need them.  This keeps the MCP server's lightweight startup path usable
    when optional vector-search dependencies are not installed.
    """

    LEGACY_SUFFIXES = {".pkl", ".pickle"}
    SAFE_CACHE_FILENAMES = {
        "index.faiss",
        "embeddings.npy",
        "metadata.json",
        "instruction_index.faiss",
        "instruction_embeddings.npy",
        "instruction_data.json",
        "instruction_index_cache.json",
        "pdf_index.faiss",
        "pdf_embeddings.npy",
        "pdf_chunks.json",
        "pdf_metadata.json",
        "sdk_index.faiss",
        "sdk_embeddings.npy",
        "sdk_operations.json",
        "l5x_index.faiss",
        "l5x_embeddings.npy",
        "l5x_chunks.json",
        "l5x_metadata.json",
        "tag_index.faiss",
        "tag_embeddings.npy",
        "tag_chunks.json",
        "tag_metadata.json",
    }

    @staticmethod
    def _validate_metadata_filename(filename: str) -> None:
        path = Path(filename)
        if path.name != filename or path.suffix.lower() != ".json":
            raise ValueError("metadata_filename must be a single .json filename")

    @classmethod
    def legacy_files(cls, cache_dir: Path) -> List[Path]:
        """Return legacy pickle files without opening or deserializing them."""
        cache_path = Path(cache_dir)
        if not cache_path.exists() or not cache_path.is_dir():
            return []
        return sorted(
            path for path in cache_path.iterdir()
            if path.is_file() and path.suffix.lower() in cls.LEGACY_SUFFIXES
        )

    @classmethod
    def reject_legacy_cache(cls, cache_dir: Path) -> None:
        """Reject legacy cache files before any cache content is read."""
        legacy = cls.legacy_files(cache_dir)
        if legacy:
            names = ", ".join(path.name for path in legacy)
            raise CacheSecurityError(
                f"Refusing to load legacy pickle cache file(s): {names}"
            )

    @classmethod
    def _atomic_write_named(cls, cache_dir: Path, filename: str, writer) -> None:
        """Atomically write a named cache file without NumPy suffix surprises."""
        cache_dir = Path(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        destination = cache_dir / filename
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", prefix=f".{filename}.", dir=cache_dir, delete=False
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
            writer(temporary_path)
            with temporary_path.open("r+b") as completed_file:
                os.fsync(completed_file.fileno())
            temporary_path.replace(destination)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    @classmethod
    def save(
        cls,
        cache_dir: Path,
        index,
        embeddings,
        metadata: Any,
        metadata_filename: str = "metadata.json",
    ) -> None:
        """Atomically save FAISS, NumPy, and JSON cache artifacts."""
        cache_dir = Path(cache_dir)
        if cache_dir.is_symlink():
            raise ValueError(f"Refusing symlink cache directory: {cache_dir}")
        cls._validate_metadata_filename(metadata_filename)
        cache_dir.mkdir(parents=True, exist_ok=True)

        if index is not None:
            import faiss

            cls._atomic_write_named(
                cache_dir,
                "index.faiss",
                lambda path: faiss.write_index(index, str(path)),
            )
        if embeddings is not None:
            import numpy as np

            def write_embeddings(path):
                with path.open("wb") as stream:
                    np.save(stream, embeddings, allow_pickle=False)

            cls._atomic_write_named(
                cache_dir,
                "embeddings.npy",
                write_embeddings,
            )

        def write_metadata(path):
            text = json.dumps(metadata, ensure_ascii=False, indent=2)
            path.write_text(text, encoding="utf-8")

        cls._atomic_write_named(cache_dir, metadata_filename, write_metadata)

    @classmethod
    def load(
        cls,
        cache_dir: Path,
        metadata_filename: str = "metadata.json",
        load_index: bool = True,
        load_embeddings: bool = True,
    ) -> Tuple[Optional[Any], Optional[Any], Any]:
        """Load cache artifacts using only native/JSON formats."""
        cache_dir = Path(cache_dir)
        if cache_dir.is_symlink():
            raise ValueError(f"Refusing symlink cache directory: {cache_dir}")
        cls._validate_metadata_filename(metadata_filename)
        cls.reject_legacy_cache(cache_dir)

        metadata_path = cache_dir / metadata_filename
        with metadata_path.open("r", encoding="utf-8") as stream:
            metadata = json.load(stream)

        index = None
        if load_index and (cache_dir / "index.faiss").exists():
            import faiss

            index = faiss.read_index(str(cache_dir / "index.faiss"))

        embeddings = None
        if load_embeddings and (cache_dir / "embeddings.npy").exists():
            import numpy as np

            embeddings = np.load(cache_dir / "embeddings.npy", allow_pickle=False)

        return index, embeddings, metadata

    @classmethod
    def is_cache_valid(
        cls,
        cache_dir: Path,
        metadata_filename: str = "metadata.json",
        max_age_days: int = 30,
    ) -> bool:
        """Check age and format without opening serialized cache content."""
        try:
            cache_dir = Path(cache_dir)
            if cls.legacy_files(cache_dir):
                return False
            metadata_path = cache_dir / metadata_filename
            if not metadata_path.is_file():
                return False
            age = time.time() - metadata_path.stat().st_mtime
            return age < max_age_days * 24 * 3600
        except (OSError, ValueError):
            return False

    @classmethod
    def clear(cls, cache_dir: Path) -> int:
        """Remove known cache artifacts directly inside one explicit directory."""
        cache_dir = Path(cache_dir)
        if cache_dir.is_symlink() or not cache_dir.is_dir():
            raise ValueError(f"Refusing unsafe cache directory: {cache_dir}")

        deleted = 0
        for path in cache_dir.iterdir():
            if path.is_symlink() or not path.is_file():
                continue
            if path.name not in cls.SAFE_CACHE_FILENAMES and path.suffix.lower() not in cls.LEGACY_SUFFIXES:
                continue
            path.unlink()
            deleted += 1
        return deleted

class SharedCacheManager:
    """Optimized cache manager with shared strategies for better performance"""
    
    def __init__(self):
        self._cache_locks = {}
        self._cache_stats = {}
        self._registered_cache_dirs = set()
        self._global_lock = threading.Lock()

    def register_cache_dir(self, cache_dir: Path) -> Path:
        """Register one concrete cache directory for controlled cleanup."""
        cache_path = Path(cache_dir)
        if cache_path.is_symlink():
            raise ValueError(f"Refusing symlink cache directory: {cache_path}")
        cache_path.mkdir(parents=True, exist_ok=True)
        resolved = cache_path.resolve()
        with self._global_lock:
            self._registered_cache_dirs.add(resolved)
        return resolved

    @staticmethod
    def has_legacy_cache(cache_dir: Path) -> bool:
        return bool(SecureVectorCache.legacy_files(cache_dir))

    @staticmethod
    def reject_legacy_cache(cache_dir: Path) -> None:
        SecureVectorCache.reject_legacy_cache(cache_dir)

    def clear_registered_caches(self) -> Dict[str, Any]:
        """Clear only explicitly registered cache directories."""
        with self._global_lock:
            cache_dirs = sorted(self._registered_cache_dirs, key=str)

        cleared = []
        deleted_files = 0
        for cache_dir in cache_dirs:
            deleted = SecureVectorCache.clear(cache_dir)
            deleted_files += deleted
            cleared.append({"cache_dir": str(cache_dir), "deleted_files": deleted})
        return {"deleted_files": deleted_files, "cache_dirs": cleared}
        
    def get_cache_lock(self, cache_name: str) -> threading.Lock:
        """Get or create a lock for a specific cache"""
        if cache_name not in self._cache_locks:
            with self._global_lock:
                if cache_name not in self._cache_locks:
                    self._cache_locks[cache_name] = threading.Lock()
        return self._cache_locks[cache_name]
    
    def is_cache_valid(self, cache_files: list, max_age_days: int = 30) -> bool:
        """
        Optimized cache validation with longer default age and batch checking
        
        Args:
            cache_files: List of cache file paths to check
            max_age_days: Maximum age in days (increased from 7 to 30 for Studio 5000 docs)
        """
        try:
            # Quick existence check first
            for cache_file in cache_files:
                if not Path(cache_file).exists():
                    return False
            
            # Batch age check - use the oldest file as reference
            oldest_time = float('inf')
            for cache_file in cache_files:
                try:
                    mtime = Path(cache_file).stat().st_mtime
                    oldest_time = min(oldest_time, mtime)
                except:
                    return False
            
            cache_age_seconds = time.time() - oldest_time
            max_age_seconds = max_age_days * 24 * 3600
            
            is_valid = cache_age_seconds < max_age_seconds
            
            # Track cache statistics
            cache_name = str(Path(cache_files[0]).parent.name)
            self._update_cache_stats(cache_name, is_valid, cache_age_seconds / 3600)
            
            return is_valid
            
        except Exception as e:
            logger.warning(f"Cache validation error: {e}")
            return False
    
    def _update_cache_stats(self, cache_name: str, hit: bool, age_hours: float):
        """Track cache performance statistics"""
        if cache_name not in self._cache_stats:
            self._cache_stats[cache_name] = {'hits': 0, 'misses': 0, 'avg_age': 0}
        
        stats = self._cache_stats[cache_name]
        if hit:
            stats['hits'] += 1
            # Update average age for hits
            total_hits = stats['hits']
            stats['avg_age'] = ((stats['avg_age'] * (total_hits - 1)) + age_hours) / total_hits
        else:
            stats['misses'] += 1
    
    def get_cache_statistics(self) -> Dict[str, Any]:
        """Get cache performance statistics"""
        total_requests = 0
        total_hits = 0
        
        stats = {}
        for cache_name, cache_stats in self._cache_stats.items():
            hits = cache_stats['hits']
            misses = cache_stats['misses']
            total_ops = hits + misses
            
            stats[cache_name] = {
                'hits': hits,
                'misses': misses,
                'hit_rate': hits / total_ops if total_ops > 0 else 0,
                'avg_age_hours': cache_stats['avg_age']
            }
            
            total_requests += total_ops
            total_hits += hits
        
        stats['overall'] = {
            'total_requests': total_requests,
            'total_hits': total_hits,
            'overall_hit_rate': total_hits / total_requests if total_requests > 0 else 0
        }
        
        return stats
    
    def optimize_cache_loading(self, cache_name: str):
        """
        Apply cache loading optimizations
        
        Returns context manager for optimized loading
        """
        return CacheLoadingContext(self, cache_name)
    
    def should_rebuild_cache(self, cache_files: list, force_rebuild: bool = False, 
                           check_source_files: Optional[list] = None) -> bool:
        """
        Intelligent decision on whether to rebuild cache
        
        Args:
            cache_files: List of cache file paths
            force_rebuild: Force rebuild regardless of cache state
            check_source_files: Source files to check for modifications
        """
        if force_rebuild:
            return True
        
        # Check if cache exists and is valid
        if not self.is_cache_valid(cache_files):
            return True
        
        # Check if source files are newer than cache (if provided)
        if check_source_files:
            try:
                cache_time = min(Path(f).stat().st_mtime for f in cache_files if Path(f).exists())
                source_time = max(Path(f).stat().st_mtime for f in check_source_files if Path(f).exists())
                
                if source_time > cache_time:
                    logger.info("Source files newer than cache, rebuilding...")
                    return True
            except Exception as e:
                logger.warning(f"Could not compare source/cache times: {e}")
        
        return False


class CacheLoadingContext:
    """Context manager for optimized cache loading operations"""
    
    def __init__(self, cache_manager: SharedCacheManager, cache_name: str):
        self.cache_manager = cache_manager
        self.cache_name = cache_name
        self.lock = cache_manager.get_cache_lock(cache_name)
        self.start_time = None
    
    def __enter__(self):
        self.start_time = time.time()
        self.lock.acquire()
        logger.info(f"Starting optimized cache loading for {self.cache_name}")
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            duration = time.time() - self.start_time
            if exc_type is None:
                logger.info(f"Cache loading completed for {self.cache_name} in {duration:.2f}s")
            else:
                logger.warning(f"Cache loading failed for {self.cache_name} after {duration:.2f}s: {exc_val}")
        finally:
            self.lock.release()


# Global shared cache manager instance
shared_cache_manager = SharedCacheManager()
