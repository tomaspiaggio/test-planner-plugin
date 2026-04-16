#!/usr/bin/env python3
"""Streams Claude Code session transcript events to the Autonoma dashboard.

Spawned as a detached background process by pipeline-kickoff.sh when a
/generate-tests run starts. Tails the session JSONL as Claude appends to it,
extracts assistant text + thinking + tool calls + tool results, and POSTs
each as a `transcript` event to /v1/setup/setups/{id}/events so the dashboard
can render a live activity log.

Self-terminates after IDLE_SECONDS of no new transcript data. Safe to kill
at any time — the daemon is stateless and holds no locks.

Usage:
  python3 transcript-streamer.py <transcript_path> <generation_id> <api_url> <api_key>
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

POLL_INTERVAL = 0.75
IDLE_SECONDS = 1800  # 30 min with no new lines → daemon exits
MAX_TEXT_CHARS = 4000
MAX_PREVIEW_CHARS = 500
HTTP_TIMEOUT = 2.0


def main() -> None:
    if len(sys.argv) != 5:
        sys.exit(2)
    transcript_path, generation_id, api_url, api_key = sys.argv[1:5]
    if not all([transcript_path, generation_id, api_url, api_key]):
        sys.exit(0)

    path = Path(transcript_path)
    # Start at end of file. Anything written before this daemon launched was
    # already visible in the terminal before the dashboard existed — don't
    # replay it.
    last_size = path.stat().st_size if path.exists() else 0
    idle = 0.0
    log(f"streamer up transcript={transcript_path} generation_id={generation_id} api_url={api_url} start_offset={last_size}")

    while idle < IDLE_SECONDS:
        if not path.exists():
            time.sleep(POLL_INTERVAL)
            idle += POLL_INTERVAL
            continue

        size = path.stat().st_size
        if size < last_size:
            # File was rotated/truncated — reset.
            last_size = 0
        if size == last_size:
            time.sleep(POLL_INTERVAL)
            idle += POLL_INTERVAL
            continue

        idle = 0.0
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            fh.seek(last_size)
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                payload = extract_event(entry)
                if payload is not None:
                    forward(payload, generation_id, api_url, api_key)
            last_size = fh.tell()


def extract_event(entry: dict) -> dict | None:
    """Turn a transcript line into a dashboard event, or None to skip."""
    etype = entry.get("type")
    is_sidechain = bool(entry.get("isSidechain", False))
    uuid = entry.get("uuid")

    if etype == "assistant":
        msg = entry.get("message") or {}
        content = msg.get("content") or []
        texts: list[str] = []
        tool_uses: list[dict] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text":
                t = (block.get("text") or "").strip()
                if t:
                    texts.append(t)
            elif btype == "thinking":
                t = (block.get("thinking") or "").strip()
                if t:
                    texts.append(f"[thinking] {t}")
            elif btype == "tool_use":
                tool_uses.append({
                    "name": block.get("name") or "unknown",
                    "input_preview": _preview(block.get("input") or {}),
                })
        if not texts and not tool_uses:
            return None
        data: dict = {"role": "assistant", "is_sidechain": is_sidechain}
        if uuid:
            data["uuid"] = uuid
        if texts:
            data["text"] = "\n".join(texts)[:MAX_TEXT_CHARS]
        if tool_uses:
            data["tool_uses"] = tool_uses
        return {"type": "transcript", "data": data}

    if etype == "user":
        msg = entry.get("message") or {}
        content = msg.get("content")
        # Tool results arrive as user messages whose content is a list of
        # tool_result blocks. Raw text user messages (the original prompt)
        # are skipped — they're already visible to the dashboard.
        if not isinstance(content, list):
            return None
        results: list[dict] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") != "tool_result":
                continue
            body = _flatten_tool_result(block.get("content"))
            entry_out: dict = {"is_error": bool(block.get("is_error"))}
            if body:
                entry_out["preview"] = body[:MAX_PREVIEW_CHARS]
            results.append(entry_out)
        if not results:
            return None
        data = {"role": "tool_result", "is_sidechain": is_sidechain, "results": results}
        if uuid:
            data["uuid"] = uuid
        return {"type": "transcript", "data": data}

    return None


def _flatten_tool_result(raw) -> str:
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        parts: list[str] = []
        for c in raw:
            if isinstance(c, dict) and c.get("type") == "text":
                parts.append(c.get("text", ""))
            elif isinstance(c, str):
                parts.append(c)
        return "\n".join(parts)
    return ""


def _preview(obj) -> str:
    try:
        s = json.dumps(obj, default=str, ensure_ascii=False)
    except Exception:
        s = str(obj)
    return s[:MAX_PREVIEW_CHARS]


def forward(payload: dict, generation_id: str, api_url: str, api_key: str) -> None:
    url = f"{api_url.rstrip('/')}/v1/setup/setups/{generation_id}/events"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            resp.read()
            log(f"POST {resp.status} {payload.get('type')} {_summarize(payload)}")
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            pass
        log(f"POST {e.code} {payload.get('type')} body={body}")
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        log(f"POST network-error {payload.get('type')} err={e!r}")
    except Exception as e:
        log(f"POST unknown-error {payload.get('type')} err={e!r}")


def _summarize(payload: dict) -> str:
    data = payload.get("data") or {}
    role = data.get("role")
    if role == "assistant":
        snippet = (data.get("text") or "").replace("\n", " ")[:80]
        tools = ",".join(t.get("name", "?") for t in data.get("tool_uses") or [])
        return f"role=assistant text={snippet!r} tools=[{tools}]"
    if role == "tool_result":
        return f"role=tool_result n_results={len(data.get('results') or [])}"
    return ""


def log(msg: str) -> None:
    # Emit to stderr which is redirected to autonoma/.streamer.log by the kickoff hook.
    try:
        print(f"[{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)
    except Exception:
        pass


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception:
        # Daemon must never propagate — swallow and exit clean so nothing
        # surfaces in the user's terminal.
        pass
