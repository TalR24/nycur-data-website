"""Cost helpers for every pipeline that calls the Anthropic API (Tal, Sep 28 2026).

BILLING: API calls are billed per token outside Claude Max (global CLAUDE.md,
"Billing"). Two levers live here:

1. Message Batches API: half price for every token, results usually within an
   hour and always within 24. The monthly refreshes run unattended, so nothing
   there needs a synchronous answer. `run_batch()` submits once, polls, and
   keeps the batch id in a state file so a run that times out can be resumed
   by the next run instead of paying for the same requests twice.
2. Prompt caching: the fixed instructions go first in their own block with a
   cache breakpoint and the per-document text goes last, so every request
   after the first reads the instructions at ~0.1x the input price
   (`cached_content()`). Minimum cacheable prefix: 1,024 tokens on Sonnet 5,
   512 on Opus 5; shorter prefixes silently do not cache.

`usage_summary()` totals the usage fields, the only proof caching works:
cache_read_input_tokens must be > 0 after the first request.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request


def cached_content(fixed: str, variable: str, ttl: str | None = None) -> list[dict]:
    """User-message content: the fixed instructions as a cached block, then the
    per-document text. ttl "1h" inside batches (requests run spread over up to
    an hour); default 5 minutes for synchronous runs."""
    cc = {"type": "ephemeral", **({"ttl": ttl} if ttl else {})}
    return [{"type": "text", "text": fixed, "cache_control": cc},
            {"type": "text", "text": variable}]


class Usage:
    """Running totals of the usage fields across calls."""

    def __init__(self) -> None:
        self.calls = 0
        self.input = self.output = self.cache_read = self.cache_write = 0

    def add(self, msg) -> None:
        u = getattr(msg, "usage", None)
        if u is None:
            return
        self.calls += 1
        self.input += getattr(u, "input_tokens", 0) or 0
        self.output += getattr(u, "output_tokens", 0) or 0
        self.cache_read += getattr(u, "cache_read_input_tokens", 0) or 0
        self.cache_write += getattr(u, "cache_creation_input_tokens", 0) or 0

    def line(self) -> str:
        return (f"usage: {self.calls} calls, input {self.input:,} uncached + "
                f"{self.cache_read:,} cache reads + {self.cache_write:,} cache writes, "
                f"output {self.output:,}"
                + ("" if self.calls < 2 or self.cache_read else
                   "  WARNING: no cache reads; the fixed prefix is not caching"))


def usage_summary(messages) -> str:
    u = Usage()
    for m in messages:
        u.add(m)
    return u.line()


def run_batch(client, requests: list[tuple[str, dict]], state_path: Path,
              max_wait_s: int = 2 * 3600, poll_s: int = 60) -> dict | None:
    """Submit `requests` [(custom_id, params)] as one Message Batch and wait.

    Returns {custom_id: ("succeeded", message) | (result_type, error)} when the
    batch has ended, or None when max_wait_s passed first: the batch id stays in
    state_path and the next call with the same state_path resumes it (the
    requests argument is then ignored). The state file is removed once results
    are collected."""
    state = json.loads(state_path.read_text()) if state_path.exists() else None
    if state:
        batch_id = state["batch_id"]
        print(f"resuming pending batch {batch_id} ({state.get('count')} requests, "
              f"created {state.get('created')})")
    else:
        if not requests:
            return {}
        batch = client.messages.batches.create(requests=[
            Request(custom_id=cid, params=MessageCreateParamsNonStreaming(**params))
            for cid, params in requests])
        batch_id = batch.id
        state_path.write_text(json.dumps({
            "batch_id": batch_id, "count": len(requests),
            "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, indent=1) + "\n")
        print(f"submitted batch {batch_id}: {len(requests)} requests")
    start = time.time()
    while True:
        batch = client.messages.batches.retrieve(batch_id)
        if batch.processing_status == "ended":
            break
        if time.time() - start > max_wait_s:
            print(f"batch {batch_id} still {batch.processing_status} after "
                  f"{max_wait_s // 60} min; left in {state_path.name} for the next run")
            return None
        time.sleep(poll_s)
    out: dict = {}
    usage = Usage()
    for r in client.messages.batches.results(batch_id):
        if r.result.type == "succeeded":
            out[r.custom_id] = ("succeeded", r.result.message)
            usage.add(r.result.message)
        else:
            out[r.custom_id] = (r.result.type, getattr(r.result, "error", None))
    counts = batch.request_counts
    print(f"batch {batch_id} ended: {counts.succeeded} succeeded, {counts.errored} errored, "
          f"{counts.expired} expired, {counts.canceled} canceled; {usage.line()}")
    # the state file stays until the caller has saved the results: a crash in
    # post-processing must not lose a paid batch (review, Sep 28 2026). Call
    # clear_state() after the outputs are written.
    return out


def clear_state(state_path: Path) -> None:
    """Remove the state file once the batch's results are saved. The workflow
    must stage the deletion (`git add -A -- <path>`), or the next run resumes a
    finished batch forever."""
    state_path.unlink(missing_ok=True)


def message_text(msg) -> str:
    return next((b.text for b in msg.content if b.type == "text"), "")
