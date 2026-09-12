#!/usr/bin/env bash
# Resume every Claude Code session that was still active at last shutdown.
#
# Reads ~/.claude/active-claude-sessions.json (maintained by track-session.sh
# via the SessionStart/SessionEnd hooks) and reopens each session with
# `claude --resume <id>` in its own directory. Sessions that exited cleanly
# were removed from the registry by the SessionEnd hook, so only sessions cut
# off by a reboot or crash are resumed.
#
# Run it at boot/login, e.g.:
#   macOS:  a LaunchAgent, or `~/path/to/resume-sessions.sh` in your shell profile
#   Linux:  a systemd user unit, or your shell profile
#
# With tmux installed, each session gets a window in a `claude-resume` tmux
# session (attach with `tmux attach -t claude-resume`). Without tmux, the
# resume commands are printed for you to run in separate terminals, since
# several interactive sessions can't share one.
set -euo pipefail

REG="${HOME}/.claude/active-claude-sessions.json"
if [ ! -s "$REG" ]; then
    echo "resume-sessions: no active-session registry at $REG — nothing to resume"
    exit 0
fi

HAVE_TMUX=0
if command -v tmux >/dev/null 2>&1; then
    HAVE_TMUX=1
fi

count=0
while IFS=$'\t' read -r sid name dir; do
    [ -n "$sid" ] || continue
    if [ ! -d "$dir" ]; then
        echo "resume-sessions: skip $name ($sid): directory $dir is gone"
        continue
    fi
    if [ "$HAVE_TMUX" = 1 ]; then
        if ! tmux has-session -t claude-resume 2>/dev/null; then
            tmux new-session -d -s claude-resume -n "$name" -c "$dir" \
                "claude --resume '$sid'"
        else
            tmux new-window -t claude-resume -n "$name" -c "$dir" \
                "claude --resume '$sid'"
        fi
        echo "resume-sessions: resumed $name ($sid) in tmux session 'claude-resume'"
    else
        echo "cd '$dir' && claude --resume '$sid'   # $name"
    fi
    count=$((count + 1))
done < <(python3 - "$REG" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as f:
    reg = json.load(f)
for sid, entry in reg.items():
    print(f"{sid}\t{entry.get('name', sid)}\t{entry.get('directory', '')}")
PY
)

if [ "$count" -eq 0 ]; then
    echo "resume-sessions: registry is empty — nothing to resume"
elif [ "$HAVE_TMUX" = 1 ]; then
    echo "resume-sessions: attach with: tmux attach -t claude-resume"
else
    echo "resume-sessions: tmux not found — run the printed commands in separate terminals"
fi
