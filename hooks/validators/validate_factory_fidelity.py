#!/usr/bin/env python3
"""Validator: semantic per-model factory fidelity using claude -p.

Rationale — Run 4 post-mortem. Heuristic hooks have been bypassed three runs
in a row. The agent found factorings that satisfy every regex while still
producing bare-insert stubs. Only a model that can read the diff between the
Step 2 snapshot and the current code can tell a faithful extraction apart
from a stub.

How it works:
  1. Fetch the factory-fidelity rubric + prompt template from
     $(cat autonoma/.docs-url)/llms/test-planner/factory-fidelity-rubric.txt
  2. Load the Step 2 audit snapshot (ground truth) and the current audit.
  3. For every model with independently_created: true in the snapshot, build a
     prompt with: Step 2 entry, current entry, factory block, helper (if
     imported), original creation_function snippet.
  4. Run `claude -p --output-format json "<prompt>"` in parallel (bounded
     concurrency). Each subprocess inherits the parent's model/provider
     config via env.
  5. Parse JSON verdicts. If any fail, block the sentinel and return the
     compiled feedback to the env-factory agent.

Exit 0 = all verdicts pass (or no models to check).
Exit 2 = one or more verdicts failed; stderr contains the feedback the
         agent should use to self-correct.
Exit 0 with a stderr warning = environment not configured to run the check
         (missing docs URL, claude CLI not found). We do NOT block in that
         case — the cheap hooks remain the primary gate.
"""

from __future__ import annotations

import concurrent.futures as futures
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Optional

import yaml  # type: ignore

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _audit_schema import is_independently_created  # noqa: E402

CONCURRENCY = int(os.environ.get("AUTONOMA_FIDELITY_CONCURRENCY", "6"))
PER_MODEL_TIMEOUT = int(os.environ.get("AUTONOMA_FIDELITY_TIMEOUT", "180"))
MAX_MODELS = int(os.environ.get("AUTONOMA_FIDELITY_MAX_MODELS", "60"))
SNIPPET_MAX_LINES = 200
DOCS_SLUG = "llms/test-planner/factory-fidelity-rubric.txt"


def warn(msg: str) -> None:
    sys.stderr.write(f"[fidelity-validator] {msg}\n")


def load_audit(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    text = path.read_text()
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    try:
        fm = yaml.safe_load(text[3:end])
    except yaml.YAMLError:
        return {}
    out: dict[str, dict] = {}
    for entry in (fm.get("models") or []):
        if isinstance(entry, dict):
            name = entry.get("name") or entry.get("model")
            if name:
                out[str(name)] = entry
    return out


def fetch_rubric() -> Optional[tuple[str, str]]:
    """Return (rubric_text, prompt_template) or None if unavailable."""
    url_file = Path("autonoma/.docs-url")
    if not url_file.exists():
        warn("autonoma/.docs-url missing — skipping semantic validation.")
        return None
    base = url_file.read_text().strip().rstrip("/")
    url = f"{base}/{DOCS_SLUG}"
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:
            content = resp.read().decode("utf-8")
    except Exception as e:
        warn(f"failed to fetch rubric from {url}: {e} — skipping.")
        return None
    # Split at "## Prompt template"
    parts = content.split("## Prompt template", 1)
    if len(parts) != 2:
        warn("rubric page is missing '## Prompt template' section — skipping.")
        return None
    rubric_md = parts[0]
    # The prompt template lives between explicit HTML-comment delimiters to
    # avoid clashing with the inner ``` fences the template itself contains.
    tpl_match = re.search(
        r"<!--\s*prompt:begin\s*-->\s*\n(.*?)\n<!--\s*prompt:end\s*-->",
        parts[1],
        re.DOTALL,
    )
    if not tpl_match:
        warn("rubric page missing <!-- prompt:begin --> / <!-- prompt:end --> markers — skipping.")
        return None
    return rubric_md.strip(), tpl_match.group(1)


def resolve_handler_path(sentinel_path: str) -> Optional[Path]:
    body = Path(sentinel_path).read_text()
    m = re.search(r"handler(?:_path)?:\s*(\S+)", body, re.IGNORECASE)
    candidates: list[str] = []
    if m:
        candidates.append(m.group(1).rstrip(".,;:"))
    for tok in re.findall(r"[\w./\\-]+\.(?:ts|tsx|js|mjs|cjs|py|rb|php|java|go|rs|ex|exs)", body):
        candidates.append(tok.rstrip(".,;:"))
    for cand in candidates:
        p = Path(cand)
        if not p.is_absolute():
            p = Path.cwd() / cand
        if p.is_file():
            return p
    return None


def find_factory_block(handler_src: str, model: str) -> str:
    header = re.search(rf"\b{re.escape(model)}\s*:\s*defineFactory\s*\(\s*\{{", handler_src)
    if not header:
        return ""
    brace = handler_src.find("{", header.end() - 1)
    if brace < 0:
        return ""
    depth = 0
    i = brace
    n = len(handler_src)
    while i < n:
        c = handler_src[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                start = handler_src.rfind("\n", 0, header.start()) + 1
                return handler_src[start : i + 1]
        i += 1
    return ""


def find_helper(handler_src: str, handler_path: Path, model: str, factory_block: str) -> Optional[tuple[Path, str, str]]:
    """Return (helper_path, helper_function_name, helper_source_snippet) if the
    factory calls a named helper imported into the handler."""
    body = factory_block
    # Look for return <name>( or await <name>( patterns
    call = re.search(r"\b(?:return|await)\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", body)
    if not call:
        return None
    fn_name = call.group(1)
    # Find the import for that name in the handler file
    imp = re.search(
        rf"import\s+(?:type\s+)?\{{[^}}]*\b{re.escape(fn_name)}\b[^}}]*\}}\s+from\s+['\"]([^'\"]+)['\"]",
        handler_src,
    )
    if not imp:
        return None
    rel = imp.group(1)
    base = handler_path.parent
    for ext in (".ts", ".tsx", ".js", ".mjs", "/index.ts", "/index.js", ""):
        p = (base / f"{rel}{ext}").resolve()
        if p.is_file():
            try:
                text = p.read_text()
            except OSError:
                continue
            snippet = extract_fn_snippet(text, fn_name)
            if snippet:
                return p, fn_name, snippet
            return p, fn_name, text[:4000]
    return None


def extract_fn_snippet(src: str, fn_name: str) -> str:
    """Find `export (async )?function fn_name(` or `fn_name =` and return body."""
    patterns = [
        rf"export\s+(?:async\s+)?function\s+{re.escape(fn_name)}\s*\(",
        rf"export\s+const\s+{re.escape(fn_name)}\s*=",
        rf"(?:async\s+)?function\s+{re.escape(fn_name)}\s*\(",
    ]
    for pat in patterns:
        m = re.search(pat, src)
        if not m:
            continue
        # Grab until the matching closing brace of the first "{" after m.end()
        brace = src.find("{", m.end())
        if brace < 0:
            continue
        depth = 0
        i = brace
        n = len(src)
        while i < n:
            c = src[i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    start = src.rfind("\n", 0, m.start()) + 1
                    snippet = src[start : i + 1]
                    return "\n".join(snippet.splitlines()[:SNIPPET_MAX_LINES])
            i += 1
    return ""


def load_original_snippet(snap_entry: dict) -> tuple[str, str]:
    """Return (file_path_str, snippet)."""
    cfile = (snap_entry.get("creation_file") or "").strip()
    cfn = (snap_entry.get("creation_function") or "").strip()
    if not cfile:
        return "", "(Step 2 audit did not record a creation_file)"
    p = Path(cfile)
    if not p.is_absolute():
        p = Path.cwd() / cfile
    if not p.is_file():
        return cfile, f"(file not found at {p})"
    try:
        text = p.read_text()
    except OSError as e:
        return cfile, f"(could not read file: {e})"
    if cfn:
        snip = extract_fn_snippet(text, cfn)
        if snip:
            return cfile, snip
    return cfile, "\n".join(text.splitlines()[:SNIPPET_MAX_LINES])


def yaml_entry(entry: dict) -> str:
    return yaml.safe_dump([entry], sort_keys=False).rstrip()


def fill_template(
    tpl: str,
    rubric: str,
    model: str,
    snap_entry: dict,
    cur_entry: Optional[dict],
    handler_path: Path,
    factory_block: str,
    helper: Optional[tuple[Path, str, str]],
    orig_path: str,
    orig_snippet: str,
) -> str:
    helper_section = (
        f"File: {helper[0]}\nFunction: {helper[1]}\n\n```\n{helper[2]}\n```"
        if helper
        else "(The factory does not call an external helper.)"
    )
    return (
        tpl.replace("{{RUBRIC}}", rubric)
        .replace("{{MODEL}}", model)
        .replace("{{STEP2_AUDIT_ENTRY}}", yaml_entry(snap_entry))
        .replace(
            "{{CURRENT_AUDIT_ENTRY}}",
            yaml_entry(cur_entry) if cur_entry else "(model not present in current audit)",
        )
        .replace("{{HANDLER_PATH}}", str(handler_path))
        .replace("{{FACTORY_BLOCK}}", factory_block or "(factory registration not found)")
        .replace("{{HELPER_SECTION}}", helper_section)
        .replace("{{ORIGINAL_CREATION_FILE}}", orig_path or "(unknown)")
        .replace("{{ORIGINAL_CREATION_SNIPPET}}", orig_snippet)
    )


def run_claude(prompt: str) -> dict:
    """Spawn `claude -p --output-format json` with the prompt on stdin.

    Model is configurable via AUTONOMA_FIDELITY_MODEL (defaults to "sonnet",
    which is cheap, fast, and reliable for bounded rubric tasks). Set to empty
    string to inherit whatever model the CLI picks.
    """
    cmd = ["claude", "-p", "--output-format", "json"]
    model = os.environ.get("AUTONOMA_FIDELITY_MODEL", "sonnet")
    if model:
        cmd.extend(["--model", model])
    try:
        proc = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=PER_MODEL_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return {"verdict": "error", "error": "timeout"}
    except FileNotFoundError:
        return {"verdict": "error", "error": "claude CLI not found"}
    if proc.returncode != 0:
        return {"verdict": "error", "error": f"claude exit {proc.returncode}: {proc.stderr[:400]}"}
    out = proc.stdout.strip()
    # Outer envelope from `claude -p --output-format json` wraps the assistant
    # response in a JSON object with a "result" field containing the text.
    try:
        envelope = json.loads(out)
    except json.JSONDecodeError:
        # Assume raw stdout is the JSON we asked for.
        return parse_verdict(out)
    inner = envelope.get("result") or envelope.get("text") or envelope.get("output") or ""
    if isinstance(inner, list):
        inner = "\n".join(str(x) for x in inner)
    return parse_verdict(str(inner))


def parse_verdict(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n", "", text)
        text = re.sub(r"\n```\s*$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
        return {"verdict": "error", "error": f"could not parse verdict: {text[:300]}"}


def validate_one(task: dict) -> dict:
    verdict = run_claude(task["prompt"])
    verdict["model"] = task["model"]
    return verdict


def main() -> None:
    if os.environ.get("AUTONOMA_SKIP_FIDELITY") == "1":
        warn("AUTONOMA_SKIP_FIDELITY=1 — skipping.")
        sys.exit(0)

    if shutil.which("claude") is None:
        warn("`claude` CLI not on PATH — skipping semantic validation.")
        sys.exit(0)

    if len(sys.argv) < 2:
        warn("no sentinel path provided")
        sys.exit(0)
    sentinel = sys.argv[1]

    rubric_pair = fetch_rubric()
    if not rubric_pair:
        sys.exit(0)
    rubric, tpl = rubric_pair

    snap = load_audit(Path("autonoma/.entity-audit-step2.md"))
    cur = load_audit(Path("autonoma/entity-audit.md"))
    if not snap:
        warn("Step 2 snapshot missing — skipping.")
        sys.exit(0)

    handler_path = resolve_handler_path(sentinel)
    if handler_path is None:
        warn("handler path not resolvable from sentinel — skipping.")
        sys.exit(0)
    handler_src = handler_path.read_text()

    models = [name for name, entry in snap.items() if is_independently_created(entry)]
    if not models:
        sys.exit(0)
    if len(models) > MAX_MODELS:
        warn(f"truncating from {len(models)} to {MAX_MODELS} models (override via AUTONOMA_FIDELITY_MAX_MODELS).")
        models = models[:MAX_MODELS]

    tasks = []
    for model in models:
        snap_entry = snap[model]
        cur_entry = cur.get(model)
        factory_block = find_factory_block(handler_src, model)
        helper = find_helper(handler_src, handler_path, model, factory_block) if factory_block else None
        orig_path, orig_snippet = load_original_snippet(snap_entry)
        prompt = fill_template(
            tpl, rubric, model, snap_entry, cur_entry, handler_path,
            factory_block, helper, orig_path, orig_snippet,
        )
        tasks.append({"model": model, "prompt": prompt})

    t0 = time.time()
    warn(f"running semantic validation for {len(tasks)} models (concurrency={CONCURRENCY}).")

    results: list[dict] = []
    with futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
        for res in ex.map(validate_one, tasks):
            results.append(res)

    elapsed = time.time() - t0
    warn(f"semantic validation complete in {elapsed:.1f}s.")

    failures = [r for r in results if r.get("verdict") == "fail"]
    errors = [r for r in results if r.get("verdict") == "error"]
    passes = [r for r in results if r.get("verdict") == "pass"]

    warn(f"results: {len(passes)} pass, {len(failures)} fail, {len(errors)} error.")

    if errors and not failures:
        # Don't block on our own infra errors; log and allow.
        warn("no hard failures; transient errors will not block the sentinel.")
        for e in errors[:5]:
            warn(f"  - {e.get('model','?')}: {e.get('error','')[:200]}")
        sys.exit(0)

    if not failures:
        sys.exit(0)

    lines = [
        f"FACTORY FIDELITY CHECK FAILED — {len(failures)} of {len(results)} models "
        "do not faithfully reproduce their Step 2 creation behaviour.",
        "",
        "This is the semantic check. It reads the Step 2 snapshot (ground truth), "
        "the current audit, the factory registration, and the original creation "
        "function, then applies the rubric at:",
        "  $(cat autonoma/.docs-url)/llms/test-planner/factory-fidelity-rubric.txt",
        "",
        "Per-model feedback:",
        "",
    ]
    for r in failures:
        model = r.get("model", "?")
        lines.append(f"── {model} ──")
        for c in r.get("criteria", []) or []:
            if c.get("status") == "fail":
                lines.append(f"  ✗ Criterion {c.get('id')}: {c.get('reason','')}")
        fix = r.get("fix_hint", "")
        if fix:
            lines.append(f"  → Fix: {fix}")
        lines.append("")
    lines.append(
        "To fix: for each failing model, either (a) call the original "
        "creation_function from the Step 2 audit (the one in the APPLICATION "
        "codebase, not the helper the factory wrote), or (b) make the helper a "
        "thin wrapper that calls that function. Do NOT leave bare ORM inserts "
        "in the helper. If a side effect truly conflicts with the SDK's "
        "scenario tree (e.g. sibling rows get created twice), document in a "
        "comment which sibling factory owns that row and reference it."
    )
    sys.stderr.write("\n".join(lines) + "\n")
    sys.exit(2)


if __name__ == "__main__":
    main()
