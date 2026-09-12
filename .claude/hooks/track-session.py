#!/usr/bin/env python3
"""Claude Code session registry hook.

Called by the SessionStart and SessionEnd hooks in .claude/settings.json with
the hook's JSON payload on stdin. Keeps ~/.claude/active-claude-sessions.json
as a map of session_id -> {name, directory, updated_at}.

    track-session.py start   upsert this session into the registry
    track-session.py end     remove it (a clean exit needs no boot-time resume)

Sessions that never fire SessionEnd (machine reboot, crash, power loss) stay
in the registry, which is exactly the set resume-sessions.sh restores on boot.
"""
import datetime
import json
import os
import sys


def main() -> None:
    action = sys.argv[1] if len(sys.argv) > 1 else "start"
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}
    sid = payload.get("session_id")
    if not sid:
        return

    reg_path = os.path.expanduser("~/.claude/active-claude-sessions.json")
    try:
        with open(reg_path, encoding="utf-8") as f:
            reg = json.load(f)
    except Exception:
        reg = {}

    if action == "start":
        cwd = payload.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
        # The hook payload carries no session title, so fall back to the
        # project directory's basename as the human-readable name.
        name = (payload.get("session_name") or payload.get("title")
                or os.path.basename(cwd.rstrip("/")) or sid)
        reg[sid] = {
            "name": name,
            "directory": cwd,
            "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        }
    else:
        reg.pop(sid, None)

    os.makedirs(os.path.dirname(reg_path), exist_ok=True)
    tmp = reg_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(reg, f, indent=1)
    os.replace(tmp, reg_path)


if __name__ == "__main__":
    main()
