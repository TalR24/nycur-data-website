#!/usr/bin/env python3
"""Long-law WINDOWS through the Anthropic Message Batches API (Nov 12 2026).

BILLING: this calls the API (billed per token outside Claude Max). Run it only after Tal approves the spend; --max-usd refuses to submit
when the projection passes the cap. One request per window: the same fixed prompt as a Max window packet (prompt v2), the window text
with the LONG_NOTE, custom_id "<key>__w<i>". Answers that parse and fit SCHEMA_V2 are saved to cache/api/long/results/<key>__w<i>.json;
import_long_answers.py copies them into cache/packets/{Y}/long/results/, where ingest_long reads them. Nothing here ingests or commits.

  api_long_windows.py [--keys FILE] [--limit-windows N] [--max-usd X] [--canary N]   submit (one batch per chunk), then collect
  api_long_windows.py --resume                                                       collect batches a previous run left pending
Env NYS_THINKING (default | medium | low | off) picks the model effort, as for extract_duties.py.
"""
import argparse, json, os, sys, time
from pathlib import Path

HERE = Path(os.path.abspath(__file__)).parent
sys.path.insert(0, str(HERE))
import extract_duties as ed   # noqa: E402  (read-only use)
import extract_obligations as eo   # noqa: E402

sys.path.insert(0, str(HERE.parent.parent.parent / "pipeline"))
OUT_DIR = HERE / "cache" / "api" / "long"
STATE = HERE / "batch_state_long.json"
STATE_CHUNK = "batch_state_long_%03d.json"
OUT_TOKENS = {"default": 4050, "medium": 1529, "low": 909, "off": 600}   # per window; default measured on the first window pilots


def cid(key, i):
    return "%s__w%d" % (key, i)


def pick_windows(cands, keys=None, out_dir=None, packets_dir=None):
    """[(law, key, i, window_text)] for the unanswered windows of the candidates (nb.long_candidates() rows), in candidate order.
    A window is skipped when a valid answer exists in out_dir or in the packets dir already."""
    out_dir = Path(out_dir or OUT_DIR)
    out = []
    for c in cands:
        if keys is not None and c["key"] not in keys:
            continue
        wins = ed.split_long(c["text"])
        _, done = ed.long_state(c["key"], packets_dir)
        n_pk = ed.long_state(c["key"], packets_dir)[0]
        for i, w in enumerate(wins, 1):
            if n_pk == len(wins) and i in done:
                continue
            if (out_dir / "results" / (cid(c["key"], i) + ".json")).exists():
                continue
            out.append((c["law"], c["key"], i, w))
    return out


def build_window_request(law, i, window, fixed, ttl="1h"):
    """(custom_id, params): extract_duties.build_request's parameter shape (model, max_tokens, thinking or effort), with the v2 fixed prompt,
    the window prompt and SCHEMA_V2."""
    import claude_batch
    key, params = ed.build_request(law, window, ttl=ttl)          # thinking / effort from NYS_THINKING, model, max_tokens
    params["messages"] = [{"role": "user", "content": claude_batch.cached_content(fixed, ed.render_window(law, window), ttl=ttl)}]
    params["output_config"]["format"] = {"type": "json_schema", "schema": ed.SCHEMA_V2}
    return cid(law["key"], i), params


def project(windows, fixed, mode=None):
    """Projected batch dollars from the real window sizes (characters / 3.8 tokens) and the per-window output tokens of the thinking mode."""
    mode = mode or os.environ.get("NYS_THINKING", "default")
    out_tok = OUT_TOKENS.get(mode, OUT_TOKENS["default"])
    n = len(windows)
    avg_in = sum(len(ed.render_window(l, w)) for l, _, _, w in windows) / max(1, n) / 3.8
    return ed.project_cost(n, avg_in, out_tok, len(fixed) / 3.8)


def save_window(cid_, msg, out_dir=None):
    """Write one answer when it parsed, was not cut at max_tokens and fits SCHEMA_V2; returns True when saved."""
    d = Path(out_dir or OUT_DIR) / "results"
    if getattr(msg, "stop_reason", None) == "max_tokens":
        return False
    try:
        raw = json.loads(next(b.text for b in msg.content if b.type == "text"))
    except Exception:  # noqa: BLE001
        return False
    if not eo.validate_against_schema(raw, ed.SCHEMA_V2):
        return False
    d.mkdir(parents=True, exist_ok=True)
    (d / (cid_ + ".json")).write_text(json.dumps(raw))
    return True


def collect(client, state_dir, out_dir, max_wait_s):
    """Collect every pending chunk listed in the manifest; returns (saved, unusable, pending chunks)."""
    import claude_batch
    manifest = Path(state_dir) / STATE.name
    state = json.loads(manifest.read_text()) if manifest.exists() else {"chunks": []}
    usage = claude_batch.Usage()
    start = time.time()
    saved = bad = 0
    left = []
    for c in state["chunks"]:
        sp = Path(state_dir) / c["state"]
        if not sp.exists():
            continue
        out = claude_batch.run_batch(client, [], sp, max_wait_s=max(0, max_wait_s - int(time.time() - start)))
        if out is None:
            left.append(c)
            continue
        b = 0
        for k, (status, payload) in out.items():
            if status == "succeeded":
                usage.add(payload)
                if save_window(k, payload, out_dir):
                    saved += 1
                    continue
            b += 1
        bad += b
        print("chunk %s: %d results, %d unusable (they stay unanswered; pick them up with a later run)" % (c["state"], len(out), b))
        claude_batch.clear_state(sp)
    state["chunks"] = left
    if left:
        manifest.write_text(json.dumps(state, indent=1))
    else:
        manifest.unlink(missing_ok=True)
    print(usage.line())
    print("windows saved %d, unusable %d, batch chunks still pending %d" % (saved, bad, len(left)))
    return saved, bad, left


def submit(client, windows, fixed, state_dir):
    """Submit the windows as batch chunks (extract_duties.chunks_of limits), recording them in the long manifest. Returns the chunk count."""
    import claude_batch
    manifest = Path(state_dir) / STATE.name
    state = json.loads(manifest.read_text()) if manifest.exists() else {"chunks": []}
    in_flight = {k for c in state["chunks"] for k in c["keys"]}
    reqs = [build_window_request(l, i, w, fixed) for l, k, i, w in windows if cid(k, i) not in in_flight]
    for cs in ed.chunks_of(reqs):
        n = len(state["chunks"]) + 1
        sp = Path(state_dir) / (STATE_CHUNK % n)
        claude_batch.run_batch(client, cs, sp, max_wait_s=0)
        state["chunks"].append({"state": sp.name, "keys": [c for c, _ in cs]})
        manifest.write_text(json.dumps(state, indent=1))
    return len(reqs)


def main(argv=None, client=None, cands=None, state_dir=None, out_dir=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--keys", metavar="FILE", help="JSON list of law keys (default: every long candidate)")
    ap.add_argument("--limit-windows", type=int, metavar="N")
    ap.add_argument("--canary", type=int, metavar="N", help="the first N windows only, one batch")
    ap.add_argument("--max-usd", type=float, metavar="X", help="refuse to submit when the projection passes X dollars")
    ap.add_argument("--resume", action="store_true", help="collect pending batches, submit nothing")
    ap.add_argument("--max-wait-min", type=int, default=300)
    a = ap.parse_args(argv)
    state_dir = Path(state_dir or HERE)
    out_dir = Path(out_dir or OUT_DIR)
    if client is None:
        import anthropic
        if not os.environ.get("ANTHROPIC_API_KEY"):
            sys.exit("ANTHROPIC_API_KEY not set")
        client = anthropic.Anthropic()
    start = time.time()
    if not a.resume:
        if cands is None:
            import next_packet_batch as nb
            cands = nb.long_candidates()
        keys = set(json.load(open(a.keys))) if a.keys else None
        windows = pick_windows(cands, keys, out_dir)
        n_cut = a.canary if a.canary else a.limit_windows
        if n_cut:
            windows = windows[:n_cut]
        print("laws with text: %d; windows to send: %d" % (len({k for _, k, _, _ in windows}), len(windows)))
        if not windows:
            print("nothing to send")
        else:
            fixed = ed.build_prompt(2)[0]
            proj = project(windows, fixed)
            mode = os.environ.get("NYS_THINKING", "default")
            print("projected batch cost: $%.2f for %d windows, thinking %s (cap %s)" % (proj, len(windows), mode, a.max_usd if a.max_usd is not None else "none"))
            if a.max_usd is not None and proj > a.max_usd:
                sys.exit("projected cost $%.2f exceeds --max-usd %.2f: nothing submitted" % (proj, a.max_usd))
            print("submitted %d requests" % submit(client, windows, fixed, state_dir))
    return collect(client, state_dir, out_dir, max(0, a.max_wait_min * 60 - int(time.time() - start)))


if __name__ == "__main__":
    main()
