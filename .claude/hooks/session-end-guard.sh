#!/usr/bin/env bash
# Stop-hook backstop for the repository-local session-end skill.
#
# If HEAD closes a governing issue but session-end has not recorded that HEAD
# in the local marker, ask the agent to run session-end before the turn stops.
# This hook only reminds; it never edits files, commits, pushes, or closes issues.

cd "${CLAUDE_PROJECT_DIR:-.}" 2>/dev/null || exit 0

input=$(cat)

# Loop guard: after this hook blocks once, allow the continued turn to stop.
python_cmd="${PYTHON_CMD:-python3}"
command -v "$python_cmd" >/dev/null 2>&1 || python_cmd=python
command -v "$python_cmd" >/dev/null 2>&1 || exit 0

active=$(printf '%s' "$input" | "$python_cmd" -c '
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    data = {}
print("1" if data.get("stop_hook_active") else "0")
' 2>/dev/null)
[ "$active" = "1" ] && exit 0

# Only meaningful inside a Git repository.
git rev-parse --git-dir >/dev/null 2>&1 || exit 0

message=$(git log -1 --pretty=%B 2>/dev/null)
printf '%s' "$message" | grep -Eqi 'closes[[:space:]]+#[0-9]+' || exit 0

head_sha=$(git rev-parse HEAD 2>/dev/null)
marker="$(git rev-parse --git-dir 2>/dev/null)/session-end-done"
if [ -f "$marker" ] && [ "$(cat "$marker" 2>/dev/null)" = "$head_sha" ]; then
    exit 0
fi

number=$(printf '%s' "$message" | grep -Eoi 'closes[[:space:]]+#[0-9]+' | grep -Eo '[0-9]+' | head -1)
reason="HEAD closes a governing issue (Closes #${number:-?}) but session-end has not run for this commit. Run the session-end skill now, then record .git/session-end-done as its final step."

"$python_cmd" -c '
import json, sys
print(json.dumps({"decision": "block", "reason": sys.argv[1]}))
' "$reason"
exit 0
