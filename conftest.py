"""Pytest bootstrap: put the repo's ``src`` packages on ``sys.path``.

The project is laid out as ``src/<package>`` and is normally imported that way
by the MCP server (``sys.path.append('..')`` in ``studio5000_mcp_server.py``).
Tests import the same packages (``from l5x_analyzer... import ...``), so ``src``
must lead ``sys.path`` when running ``python -m pytest`` from the repo root.

Prepending (not appending) also makes the in-repo vendored ``src/acd`` shadow the
stale ``acd_tools`` distribution installed into the venv's site-packages.
"""

import os
import sys

_SRC = os.path.join(os.path.dirname(__file__), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
