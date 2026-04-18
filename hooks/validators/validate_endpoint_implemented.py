#!/usr/bin/env python3
"""Validator for autonoma/.endpoint-implemented.

Blocks the sentinel write when the handler file contains an inline ORM write
inside a defineFactory({ create }) body for a model the entity audit marked
has_creation_code: true. This is the #1 bug the env-factory agent ships and
the agent's self-policing factory-integrity check has proven insufficient.

Inputs: path to .endpoint-implemented (via validate-pipeline-output.sh).
Reads:
  - autonoma/entity-audit.md (frontmatter: models with has_creation_code true/false)
  - the handler file path recorded in .endpoint-implemented body (first match of "handler: <path>")

Exit codes:
  0 — clean
  2 — anti-pattern found; prints a Claude-facing error message on stderr

The regex set mirrors the language list in agents/env-factory-generator.md's
"The one thing you MUST NOT do" section. Raw SQL literal INSERTs are not
matched here because distinguishing them from teardown DELETE strings in the
same factory block requires full parsing — the grep-level anti-pattern
detection catches the >95% case.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import yaml  # type: ignore

SENTINEL_PATH = sys.argv[1] if len(sys.argv) > 1 else ""

# Max number of models allowed to flip from has_creation_code: true to false
# between the Step 2 snapshot and the audit at .endpoint-implemented time.
# Overridable via env for unusual migrations; default 5 matches the agent's
# own recommendation in the third-run post-mortem.
AUDIT_FLIP_CAP = int(os.environ.get("AUTONOMA_AUDIT_FLIP_CAP", "5"))

# Standalone server patterns: when the handler directory contains a file that
# starts its own HTTP server instead of exporting a router mounted on the main
# app, we block. This is the second bug from the third-run post-mortem.
STANDALONE_SERVER_PATTERNS = [
    re.compile(r"\bserve\s*\(\s*\{[^}]*\bfetch\b", re.DOTALL),  # @hono/node-server
    re.compile(r"\bapp\.listen\s*\("),                              # express / hono-node
    re.compile(r"\bhttp\.createServer\s*\("),                       # raw node
    re.compile(r"\buvicorn\.run\s*\("),                             # python
    re.compile(r"\bFlask\s*\([^)]*\)[^\n]*\.run\s*\("),         # flask
    re.compile(r"\brun!\s*$", re.MULTILINE),                          # ruby sinatra-ish
]

# Anti-pattern: ORM create/insert/upsert calls that almost certainly belong to
# a raw ORM write rather than a service/repository method call.
ORM_ANTI_PATTERN = re.compile(
    r"\b(prisma|db|tx|ctx\.executor)\."        # ORM root
    r"[a-zA-Z_][a-zA-Z0-9_]*\."                # model accessor
    r"(create|createMany|insert|insertMany|upsert)\s*\(",
    re.IGNORECASE,
)

# A second class: Drizzle-style `tx.insert(xTable)` / `db.insert(xTable)`.
DRIZZLE_INSERT = re.compile(
    r"\b(tx|db|ctx\.executor)\.insert\s*\(",
)

FACTORY_HEADER = re.compile(
    r"([A-Z][A-Za-z0-9_]*)\s*:\s*defineFactory\s*\(\s*\{",
)


def fail(message: str) -> None:
    sys.stderr.write(message + "\n")
    sys.exit(2)


def find_matching_brace(src: str, open_idx: int) -> int:
    """Given index of `{`, return index of matching `}`.

    Naive balancer — ignores strings/comments. Good enough for generated
    handler files that follow the standard shape.
    """
    depth = 0
    i = open_idx
    n = len(src)
    while i < n:
        c = src[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def extract_factory_bodies(src: str) -> list[tuple[str, str]]:
    """Return list of (model_name, factory_inner_src)."""
    out: list[tuple[str, str]] = []
    for m in FACTORY_HEADER.finditer(src):
        model = m.group(1)
        brace_open = src.find("{", m.end() - 1)
        if brace_open < 0:
            continue
        brace_close = find_matching_brace(src, brace_open)
        if brace_close < 0:
            continue
        out.append((model, src[brace_open + 1 : brace_close]))
    return out


def extract_create_body(factory_src: str) -> str:
    """Find the `create:` or `create(` body inside a factory config object."""
    # Pattern: create(data, ctx) { ... }  OR  create: async (data, ctx) => { ... }
    # OR create: (data, ctx) => { ... }
    create_start = re.search(r"\bcreate\s*[(:]", factory_src)
    if not create_start:
        return ""
    # Find the first `{` after create_start.
    brace_open = factory_src.find("{", create_start.end())
    if brace_open < 0:
        return ""
    brace_close = find_matching_brace(factory_src, brace_open)
    if brace_close < 0:
        return ""
    return factory_src[brace_open + 1 : brace_close]


def parse_audit() -> dict[str, bool]:
    """Return {model_name: has_creation_code}."""
    audit_path = Path("autonoma/entity-audit.md")
    if not audit_path.exists():
        fail("Missing autonoma/entity-audit.md — cannot verify factory integrity.")
    text = audit_path.read_text()
    if not text.startswith("---"):
        fail("autonoma/entity-audit.md missing YAML frontmatter.")
    end = text.find("\n---", 3)
    if end < 0:
        fail("autonoma/entity-audit.md frontmatter not terminated.")
    try:
        fm = yaml.safe_load(text[3:end])
    except yaml.YAMLError as e:
        fail(f"autonoma/entity-audit.md frontmatter not valid YAML: {e}")
    models = fm.get("models") or []
    out: dict[str, bool] = {}
    for entry in models:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name") or entry.get("model")
        if not name:
            continue
        out[str(name)] = bool(entry.get("has_creation_code"))
    return out


def resolve_handler_path() -> Path:
    """Read the handler path recorded in .endpoint-implemented body."""
    if not SENTINEL_PATH or not Path(SENTINEL_PATH).exists():
        fail(".endpoint-implemented sentinel path not provided or missing.")
    body = Path(SENTINEL_PATH).read_text()

    candidates: list[str] = []
    m = re.search(r"handler:\s*(\S+)", body, re.IGNORECASE)
    if m:
        candidates.append(m.group(1).rstrip(".,;:"))
    # Fallback: extract every path-looking token ending in a source extension.
    for tok in re.findall(r"[\w./\\-]+\.(?:ts|tsx|js|mjs|cjs|py|rb|php|java|go|rs|ex|exs)", body):
        candidates.append(tok.rstrip(".,;:"))

    seen: set[str] = set()
    for cand in candidates:
        if cand in seen:
            continue
        seen.add(cand)
        p = Path(cand)
        if not p.is_absolute():
            p = Path.cwd() / cand
        if p.exists() and p.is_file():
            return p

    fail(
        ".endpoint-implemented body must name the handler file (e.g. a line "
        "'handler: apps/api/src/routes/autonoma/autonoma.handler.ts') so the "
        "factory-integrity validator can locate it. Checked: "
        + ", ".join(candidates[:8] or ["(no path tokens found)"])
    )
    return Path()  # unreachable


def check_audit_flip() -> list[str]:
    """Compare the Step 2 snapshot to the current audit; return error lines.

    Enforces a cap on how many models may flip from has_creation_code: true
    to false between Step 2 ack and .endpoint-implemented. If no snapshot
    exists (older projects that started before this hook shipped) we skip
    silently — the snapshot is created automatically on .step-2-ack.
    """
    snapshot = Path("autonoma/.entity-audit-step2.md")
    current = Path("autonoma/entity-audit.md")
    if not snapshot.exists() or not current.exists():
        return []

    def _true_set(path: Path) -> set[str]:
        text = path.read_text()
        if not text.startswith("---"):
            return set()
        end = text.find("\n---", 3)
        if end < 0:
            return set()
        try:
            fm = yaml.safe_load(text[3:end])
        except yaml.YAMLError:
            return set()
        out: set[str] = set()
        for entry in (fm.get("models") or []):
            if not isinstance(entry, dict):
                continue
            name = entry.get("name") or entry.get("model")
            if name and bool(entry.get("has_creation_code")):
                out.add(str(name))
        return out

    before = _true_set(snapshot)
    after = _true_set(current)
    flipped = sorted(before - after)
    if len(flipped) <= AUDIT_FLIP_CAP:
        return []

    lines = [
        f"AUDIT FLIP CAP EXCEEDED — {len(flipped)} models flipped from "
        f"has_creation_code: true to false since Step 2 (cap: {AUDIT_FLIP_CAP}).",
        "",
        "The env-factory agent is editing ground truth to dodge the factory "
        "integrity check. Branch 3 (\"audit is factually wrong\") is for cases "
        "where the audit's creation_function does NOT exist or creates NOTHING "
        "— not for cases where calling it is inconvenient (complex DI, external "
        "side effects, Temporal workflows, bulk orchestrators). Those are "
        "Branch 2 problems: extract helpers, wire constructor deps, or guard "
        "external calls in the service itself.",
        "",
        "Models flipped (showing first 40):",
    ]
    for name in flipped[:40]:
        lines.append(f"  - {name}")
    if len(flipped) > 40:
        lines.append(f"  ... and {len(flipped) - 40} more")
    lines.append("")
    lines.append(
        "To proceed: (a) restore has_creation_code: true for the models above "
        "and write real factories per the Per-model decision tree, or (b) if "
        "you truly believe a subset should flip, ask the user to raise "
        "AUTONOMA_AUDIT_FLIP_CAP and confirm the diff."
    )
    return lines


def check_handler_mount(handler_path: Path) -> list[str]:
    """Return error lines if the handler isn't mounted on the main app.

    Two checks:
      1. No sibling file in the handler directory starts its own server.
      2. Somewhere in the backend source tree, a file imports the handler
         (by relative path, module path, or file basename).
    """
    handler_dir = handler_path.parent
    errors: list[str] = []

    # 1) Detect standalone server files in the handler directory.
    standalone_hits: list[tuple[Path, str]] = []
    for sibling in handler_dir.iterdir():
        if not sibling.is_file():
            continue
        if sibling == handler_path:
            continue
        if sibling.name.endswith((".test.ts", ".test.js", ".spec.ts", ".spec.js")):
            continue
        if sibling.suffix not in {".ts", ".tsx", ".js", ".mjs", ".py", ".rb", ".go", ".rs", ".java"}:
            continue
        try:
            text = sibling.read_text()
        except OSError:
            continue
        for pat in STANDALONE_SERVER_PATTERNS:
            if pat.search(text):
                standalone_hits.append((sibling, pat.pattern))
                break

    if standalone_hits:
        errors.append(
            "STANDALONE SERVER DETECTED — the Autonoma handler must be mounted "
            "as a route on the existing application, not run as its own HTTP "
            "server. The following files bind their own port:"
        )
        errors.append("")
        for p, pat in standalone_hits:
            errors.append(f"  - {p} (matched: {pat})")
        errors.append("")
        errors.append(
            "Fix: delete the standalone server file and mount the handler as a "
            "route on the main app, following the same pattern every other "
            "feature uses (e.g. `app.route(\"/api/autonoma\", router)` in Hono, "
            "`app.use(\"/api/autonoma\", router)` in Express, or the equivalent "
            "for your framework). Read the main app entry file first and copy "
            "its existing routing pattern."
        )
        errors.append("")

    # 2) Verify the handler is imported from somewhere reachable. We use the
    # last two path segments (parent-dir/file-stem) to avoid false positives
    # from unrelated packages that happen to share the parent-dir name (e.g.
    # `@autonoma/logger` vs the local `autonoma/handler`).
    handler_basename = handler_path.stem              # e.g. "handler"
    handler_parent_dir = handler_dir.name             # e.g. "autonoma"
    specific_fragment = f"{handler_parent_dir}/{handler_basename}"  # "autonoma/handler"
    # Also accept any file in the same parent directory (routes on the router
    # file next to handler.ts still count as mounting — e.g. autonoma/router.ts
    # is imported by app.ts and imports handler.ts).
    import_patterns = [
        re.compile(rf"['\"][^'\"]*{re.escape(specific_fragment)}(?:['\"]|\.[a-z]+['\"])"),
        re.compile(rf"\bfrom\s+[\w.]*{re.escape(handler_parent_dir)}\.{re.escape(handler_basename)}\b"),  # python
    ]
    found_import = False
    root = Path.cwd()
    # Only scan source dirs with reasonable extensions.
    source_exts = {".ts", ".tsx", ".js", ".mjs", ".cjs", ".py", ".rb", ".go", ".rs", ".java", ".ex", ".exs", ".php"}
    skip_dirs = {"node_modules", ".git", "dist", "build", ".next", ".turbo", "target", "vendor", "__pycache__", "autonoma"}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs and not d.startswith(".")]
        for fn in filenames:
            if not any(fn.endswith(ext) for ext in source_exts):
                continue
            fp = Path(dirpath) / fn
            if fp.resolve() == handler_path.resolve():
                continue
            if fp.parent.resolve() == handler_path.parent.resolve():
                # Don't count imports inside the handler's own directory — the
                # standalone server.ts imports handler.ts but that isn't
                # "reachable from the main app".
                continue
            try:
                text = fp.read_text()
            except OSError:
                continue
            for pat in import_patterns:
                if pat.search(text):
                    found_import = True
                    break
            if found_import:
                break
        if found_import:
            break

    if not found_import:
        errors.append(
            f"HANDLER NOT MOUNTED — no file outside {handler_dir} imports the "
            f"Autonoma handler. The endpoint is unreachable from the main "
            f"application's routes."
        )
        errors.append("")
        errors.append(
            "Fix: import the handler (or its router) from the main app's entry "
            "file (e.g. apps/api/src/app.ts) and mount it on a route. The "
            "Autonoma platform sends HMAC-signed requests to the main API's "
            "public URL — a handler that nothing imports is dead code."
        )
        errors.append("")

    return errors


def main() -> None:
    audit = parse_audit()
    handler_path = resolve_handler_path()
    src = handler_path.read_text()

    violations: list[tuple[str, int, str]] = []
    factories = extract_factory_bodies(src)

    seen_models: set[str] = set()
    for model, factory_src in factories:
        seen_models.add(model)
        if not audit.get(model):
            # has_creation_code: false or unknown — ORM fallback is legitimate.
            continue
        create_body = extract_create_body(factory_src)
        if not create_body:
            continue
        for m in ORM_ANTI_PATTERN.finditer(create_body):
            line_no = create_body[: m.start()].count("\n") + 1
            snippet = create_body.splitlines()[line_no - 1].strip()
            violations.append((model, line_no, snippet))
        for m in DRIZZLE_INSERT.finditer(create_body):
            line_no = create_body[: m.start()].count("\n") + 1
            snippet = create_body.splitlines()[line_no - 1].strip()
            violations.append((model, line_no, snippet))

    # Flag audited models missing a factory entirely.
    missing_factories = [
        name for name, has_code in audit.items() if has_code and name not in seen_models
    ]

    audit_flip_errors = check_audit_flip()
    mount_errors = check_handler_mount(handler_path)

    if not violations and not missing_factories and not audit_flip_errors and not mount_errors:
        sys.exit(0)

    lines = [
        "FACTORY INTEGRITY CHECK FAILED — .endpoint-implemented will NOT be written.",
        "",
        f"Handler inspected: {handler_path}",
        "",
    ]
    if violations:
        lines.append(
            "The following factories contain inline ORM writes for models the audit "
            "marked has_creation_code: true. This is the #1 trap the env-factory "
            "agent is warned about. You MUST call the audited creation_function "
            "(extracting it first if needs_extraction: true). See the Per-model "
            "decision tree and DI playbook in the env-factory prompt."
        )
        lines.append("")
        for model, line_no, snippet in violations:
            lines.append(f"  - {model} factory body: line {line_no}: {snippet}")
        lines.append("")
    if missing_factories:
        lines.append(
            "The following models are has_creation_code: true in the audit but have "
            "no defineFactory registration in the handler:"
        )
        for name in missing_factories:
            lines.append(f"  - {name}")
        lines.append("")
    if audit_flip_errors:
        lines.extend(audit_flip_errors)
    if mount_errors:
        lines.extend(mount_errors)
    if violations or missing_factories:
        lines.append(
            "To fix: re-run the Per-model decision tree for every failing model. If the "
            "creation function is inline in a route/framework hook, extract it into a "
            "named exported function, update entity-audit.md in place (clear "
            "needs_extraction), then call the new function from the factory."
        )
    fail("\n".join(lines))


if __name__ == "__main__":
    main()
