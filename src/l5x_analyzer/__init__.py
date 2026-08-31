#!/usr/bin/env python3
"""
L5X Analyzer Package

This package provides AI-powered analysis and modification capabilities for Studio 5000 L5X files
using vector databases and the official Studio 5000 SDK for production-scale projects.

Package-level names are re-exported lazily (PEP 562) so that lightweight
consumers — e.g. the offline ACD->L5X converter used by the documentation
pipeline — can import their submodules without pulling in the vector-DB
stack (torch / faiss / sentence-transformers).
"""

import importlib

_LAZY_EXPORTS = {
    "L5XChunk": ".l5x_chunk",
    "L5XChunkType": ".l5x_chunk",
    "SDKPoweredL5XAnalyzer": ".sdk_powered_analyzer",
    "L5XVectorDatabase": ".l5x_vector_db",
    "L5XSearchResult": ".l5x_vector_db",
    "L5XSDKMCPIntegration": ".l5x_mcp_integration",
    "L5XMCPTools": ".l5x_mcp_integration",
}

__all__ = list(_LAZY_EXPORTS)

__version__ = "1.0.0"


def __getattr__(name):
    if name in _LAZY_EXPORTS:
        module = importlib.import_module(_LAZY_EXPORTS[name], __name__)
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
