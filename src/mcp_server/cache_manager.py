#!/usr/bin/env python3
"""
Optimized cache manager for Studio 5000 MCP Server vector databases
Provides shared caching strategies and optimizations across all vector databases
"""

import os
import time
import threading
from pathlib import Path
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

class SharedCacheManager:
    """Optimized cache manager with shared strategies for better performance"""
    
    def __init__(self):
        self._cache_locks = {}
        self._cache_stats = {}
        self._global_lock = threading.Lock()
        
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
