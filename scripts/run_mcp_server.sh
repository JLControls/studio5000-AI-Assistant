#!/usr/bin/env bash
# Launcher for the Studio5000 AI Assistant MCP server.
#
# Picks the right Python interpreter and Studio 5000 doc/SDK paths for
# whichever environment this script is actually running in (WSL, native
# Windows via Git Bash/MSYS, or plain Linux), so the same .mcp.json works
# no matter which shell Claude Code spawns it from. Repo root is derived
# from this script's own location, so it works correctly regardless of
# which clone (WSL-native checkout vs Windows checkout) it lives in.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Studio 5000 is Windows-only software; these are the well-known install
# locations, expressed per-environment below.
DOC_SUBPATH="Program Files (x86)/Rockwell Software/Studio 5000/Logix Designer/ENU/v36/Bin/Help/ENU/rs5000"
SDK_SUBPATH="Users/Public/Documents/Studio 5000/Logix Designer SDK/python"

if grep -qiE 'microsoft|wsl' /proc/version 2>/dev/null; then
    # Running under WSL: use the WSL-native venv, reach Windows-only
    # Studio 5000 install through the /mnt/c interop mount.
    ENVIRONMENT="wsl"
    PYTHON="${REPO_ROOT}/venv/bin/python"
    DOC_PATH="/mnt/c/${DOC_SUBPATH}"
    SDK_PATH="/mnt/c/${SDK_SUBPATH}"
elif [[ "$(uname -s)" =~ MINGW|MSYS|CYGWIN ]]; then
    # Git Bash / MSYS on native Windows: use the Windows venv's
    # Scripts/python.exe and native C:\ paths.
    ENVIRONMENT="windows"
    PYTHON="${REPO_ROOT}/venv/Scripts/python.exe"
    DOC_PATH="C:\\${DOC_SUBPATH//\//\\}"
    SDK_PATH="C:\\${SDK_SUBPATH//\//\\}"
else
    # Plain Linux, no Windows install reachable. Studio 5000 docs/SDK are
    # unavailable here; leave the paths unset (server tolerates this —
    # doc indexing/SDK features simply won't have anything to find).
    ENVIRONMENT="linux"
    PYTHON="${REPO_ROOT}/venv/bin/python"
    DOC_PATH=""
    SDK_PATH=""
fi

if [[ ! -x "${PYTHON}" ]]; then
    echo "run_mcp_server.sh: no venv python at ${PYTHON} (environment: ${ENVIRONMENT})." >&2
    echo "  Create it with: python3 -m venv venv && ./venv/bin/pip install -r requirements.txt" >&2
    exit 1
fi

export STUDIO5000_DOC_PATH="${DOC_PATH}"
export STUDIO5000_SDK_PATH="${SDK_PATH}"
export PYTHONIOENCODING="utf-8"
export PYTHONPATH="${REPO_ROOT}/src"
export STUDIO5000_SDK_ENABLED="false"

cd "${REPO_ROOT}"
exec "${PYTHON}" "${REPO_ROOT}/src/mcp_server/studio5000_mcp_server.py" "$@"
