#!/usr/bin/env python3
"""Validator: `creation_file` must be immutable after Step 2.

Rationale — Run 4 post-mortem. The env-factory agent evaded the factory
integrity hook by (a) extracting stubs into a new file under the handler's
directory and (b) rewriting `creation_file` in the audit to point at the stub,
so every downstream check validated against fabricated ground truth.

Rule: for every model with `has_creation_code: true` in BOTH the Step 2
snapshot AND the current audit, the `creation_file` column must not change.
Allowed transitions:
  - row removed from current (not a change, model dropped)
  - has_creation_code flipped true -> false (covered by the audit-flip cap)
  - a new model added in current (snapshot has no row to compare)

Exit 0 = clean. Exit 2 with actionable message on violation.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml  # type: ignore

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent))
from _audit_schema import is_independently_created  # noqa: E402


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
        if not isinstance(entry, dict):
            continue
        name = entry.get("name") or entry.get("model")
        if not name:
            continue
        out[str(name)] = entry
    return out


def main() -> None:
    snap = load_audit(Path("autonoma/.entity-audit-step2.md"))
    cur = load_audit(Path("autonoma/entity-audit.md"))
    if not snap:
        # Snapshot missing — skip silently. The audit-flip check already
        # prints a warning when appropriate.
        sys.exit(0)

    violations: list[tuple[str, str, str]] = []
    for name, snap_entry in snap.items():
        if not is_independently_created(snap_entry):
            continue
        cur_entry = cur.get(name)
        if cur_entry is None:
            continue
        if not is_independently_created(cur_entry):
            # Flipped to false — caught elsewhere.
            continue
        snap_file = (snap_entry.get("creation_file") or "").strip()
        cur_file = (cur_entry.get("creation_file") or "").strip()
        if snap_file and cur_file and snap_file != cur_file:
            violations.append((name, snap_file, cur_file))

    if not violations:
        sys.exit(0)

    lines = [
        f"CREATION_FILE IMMUTABILITY VIOLATED — {len(violations)} models had "
        "their Step 2 `creation_file` column overwritten.",
        "",
        "The Step 2 audit is a statement about the existing codebase at "
        "analysis time. Its `creation_file` column names where the real "
        "creation logic lives BEFORE the factory was written. Overwriting it "
        "to point at a file the factory agent created is the audit-rewrite "
        "attack from the Run 4 post-mortem — it makes every downstream check "
        "validate against fabricated ground truth.",
        "",
        "Violations (model: snapshot_path -> current_path):",
    ]
    for name, s, c in violations[:40]:
        lines.append(f"  - {name}: {s}  ->  {c}")
    if len(violations) > 40:
        lines.append(f"  ... and {len(violations) - 40} more")
    lines.append("")
    lines.append(
        "To fix: restore the original `creation_file` values from "
        "autonoma/.entity-audit-step2.md. If you extracted the creation code "
        "into a new helper, record that in an `extracted_to:` field — do NOT "
        "overwrite `creation_file`. The audit's creation_file must continue "
        "to name the file where the real business logic originally lives."
    )
    sys.stderr.write("\n".join(lines) + "\n")
    sys.exit(2)


if __name__ == "__main__":
    main()
