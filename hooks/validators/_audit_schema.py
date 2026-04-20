"""Shared helpers for reading the entity audit with backwards compatibility.

Two schemas exist on disk:

- v1 (legacy): each model entry has `has_creation_code: bool` and, when true,
  `creation_file` / `creation_function` / `side_effects`. Nothing about who
  else mints the model.
- v2 (current): each model entry has `independently_created: bool` plus a
  `created_by: [{owner, via, why}]` list.

The compat shim translates v1 into v2 on read so callers only reason about
`independently_created`. We never rewrite the on-disk file here — that's the
audit generator's job.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml  # type: ignore


def load_audit(path: Path) -> dict[str, dict]:
    """Return {model_name: normalized_entry}. Empty dict if the file is missing or malformed."""
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
        out[str(name)] = _normalize(entry)
    return out


def _normalize(entry: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of entry with `independently_created` + `created_by` populated.

    - If `independently_created` is already set, the entry is v2 — leave it alone
      (just default `created_by` to []).
    - Otherwise fall back to v1 `has_creation_code` and set `created_by: []`.
    """
    out = dict(entry)
    if "independently_created" not in out:
        out["independently_created"] = bool(out.get("has_creation_code"))
    if "created_by" not in out or out["created_by"] is None:
        out["created_by"] = []
    return out


def is_independently_created(entry: dict[str, Any]) -> bool:
    """True when the model has its own standalone creation path (factory-worthy)."""
    if "independently_created" in entry:
        return bool(entry["independently_created"])
    return bool(entry.get("has_creation_code"))
