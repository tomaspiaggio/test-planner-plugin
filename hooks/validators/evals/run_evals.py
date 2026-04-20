#!/usr/bin/env python3
"""Evals for the semantic factory-fidelity validator + the entity-audit
validator's schema invariants.

Each fixture is a self-contained JSON blob. The kind of fixture is chosen by
`expected_verdict` (or by the `kind` field for non-LLM fixtures):

- `expected_verdict: "pass" | "fail"` — LLM fixture. Feeds the prompt to
  `claude -p`, parses the JSON verdict, and asserts verdict + failing
  criteria match.
- `expected_verdict: "skip"` — filter fixture. Asserts that the fidelity
  validator's model selector would NOT include this model (i.e. the audit
  entry is pure dependent / legacy false). No LLM call, no cost.
- `kind: "audit_validator"` — audit-validator fixture. Synthesises a
  minimal entity-audit.md from `audit_frontmatter`, runs
  `validate_entity_audit.py` as a subprocess, and asserts the exit code +
  stderr substring.

Run:
    AUTONOMA_DOCS_URL=http://localhost:4321 python3 hooks/validators/evals/run_evals.py

    # single fixture:
    ... run_evals.py --only good_uses_service

Exits 0 on success, 1 on any mismatch.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
VALIDATORS = HERE.parent
sys.path.insert(0, str(VALIDATORS))

import validate_factory_fidelity as v  # noqa: E402
from _audit_schema import is_independently_created  # noqa: E402


def load_fixture(path: Path) -> dict:
    return json.loads(path.read_text())


def render_prompt(fixture: dict, rubric: str, tpl: str) -> str:
    return (
        tpl.replace("{{RUBRIC}}", rubric)
        .replace("{{MODEL}}", fixture["model"])
        .replace("{{STEP2_AUDIT_ENTRY}}", fixture["step2_audit_entry"])
        .replace("{{CURRENT_AUDIT_ENTRY}}", fixture["current_audit_entry"])
        .replace("{{HANDLER_PATH}}", fixture.get("handler_path", "(fixture)"))
        .replace("{{FACTORY_BLOCK}}", fixture["factory_block"])
        .replace("{{HELPER_SECTION}}", fixture.get("helper_section", "(The factory does not call an external helper.)"))
        .replace("{{ORIGINAL_CREATION_FILE}}", fixture.get("original_creation_file", "(unknown)"))
        .replace("{{ORIGINAL_CREATION_SNIPPET}}", fixture.get("original_creation_snippet", ""))
    )


def run_skip_fixture(fixture: dict) -> tuple[bool, str]:
    """Parse fixture's step2_audit_entry as a single-model YAML list and assert
    is_independently_created() returns False (so the fidelity validator would skip it)."""
    import yaml
    try:
        parsed = yaml.safe_load(fixture["step2_audit_entry"])
    except yaml.YAMLError as e:
        return False, f"could not parse step2_audit_entry: {e}"
    if not isinstance(parsed, list) or not parsed or not isinstance(parsed[0], dict):
        return False, "step2_audit_entry must be a single-entry YAML list"
    entry = parsed[0]
    if is_independently_created(entry):
        return False, (
            f"fidelity validator would NOT skip this model — is_independently_created "
            f"returned True for entry {entry!r}"
        )
    return True, "ok"


def run_audit_validator_fixture(fixture: dict) -> tuple[bool, str]:
    fm = fixture["audit_frontmatter"]
    expected_exit = int(fixture.get("expected_exit", 1))
    expected_substr = fixture.get("expected_stderr_substring", "")
    with tempfile.TemporaryDirectory() as td:
        audit = Path(td) / "entity-audit.md"
        audit.write_text("---\n" + fm + "---\nBody\n")
        proc = subprocess.run(
            [sys.executable, str(VALIDATORS / "validate_entity_audit.py"), str(audit)],
            capture_output=True, text=True, timeout=30,
        )
    if proc.returncode != expected_exit:
        return False, (
            f"exit mismatch: expected={expected_exit} observed={proc.returncode} "
            f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
        )
    combined = (proc.stdout or "") + (proc.stderr or "")
    if expected_substr and expected_substr not in combined:
        return False, f"expected stderr substring {expected_substr!r} not in output:\n{combined}"
    return True, "ok"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="Run a single fixture by name (no extension)")
    ap.add_argument("--write-prompt", action="store_true", help="Write the rendered prompt for each LLM fixture to stdout and exit without calling claude")
    args = ap.parse_args()

    os.chdir(VALIDATORS.parent.parent)
    Path("autonoma").mkdir(exist_ok=True)
    url_file = Path("autonoma/.docs-url")
    restore = url_file.exists()
    prior = url_file.read_text() if restore else None
    docs = os.environ.get("AUTONOMA_DOCS_URL")
    if docs:
        url_file.write_text(docs.strip())

    fixtures_dir = HERE / "fixtures"
    fixtures = sorted(fixtures_dir.glob("*.json"))
    if args.only:
        fixtures = [f for f in fixtures if f.stem == args.only]
        if not fixtures:
            print(f"no fixture named {args.only}", file=sys.stderr)
            return 1

    # Only fetch rubric if we have any LLM fixtures left in the run list
    needs_llm = any(
        load_fixture(fp).get("expected_verdict") in ("pass", "fail")
        for fp in fixtures
    )
    rubric = tpl = None
    try:
        if needs_llm:
            pair = v.fetch_rubric()
            if not pair:
                print("could not fetch rubric — set AUTONOMA_DOCS_URL", file=sys.stderr)
                return 1
            rubric, tpl = pair
    finally:
        if restore:
            url_file.write_text(prior or "")
        elif docs:
            try:
                url_file.unlink()
            except OSError:
                pass

    fails: list[str] = []
    for fp in fixtures:
        fixture = load_fixture(fp)
        kind = fixture.get("kind")
        expected = fixture.get("expected_verdict")

        if kind == "audit_validator":
            ok, detail = run_audit_validator_fixture(fixture)
            tag = "PASS" if ok else "FAIL"
            print(f"{tag} {fp.stem}: audit_validator")
            if not ok:
                print(f"    reason: {detail}")
                fails.append(fp.stem)
            continue

        if expected == "skip":
            ok, detail = run_skip_fixture(fixture)
            tag = "PASS" if ok else "FAIL"
            print(f"{tag} {fp.stem}: expected=skip observed={'skip' if ok else 'NOT-skipped'}")
            if not ok:
                print(f"    reason: {detail}")
                fails.append(fp.stem)
            continue

        # LLM fixture
        if args.write_prompt:
            print(f"── {fp.stem} ──")
            print(render_prompt(fixture, rubric, tpl))
            print()
            continue
        verdict = v.run_claude(render_prompt(fixture, rubric, tpl))
        observed = verdict.get("verdict", "error")
        matched = observed == expected
        detail_ok = True
        if expected == "fail" and observed == "fail":
            expected_fails = set(fixture.get("expected_fail_criteria") or [])
            if expected_fails:
                observed_fails = {c.get("id") for c in (verdict.get("criteria") or []) if c.get("status") == "fail"}
                missing = expected_fails - observed_fails
                if missing:
                    detail_ok = False
        ok = matched and detail_ok
        tag = "PASS" if ok else "FAIL"
        print(f"{tag} {fp.stem}: expected={expected} observed={observed}")
        if not ok:
            print(f"    reason: expected criteria={fixture.get('expected_fail_criteria')} observed={[c for c in (verdict.get('criteria') or [])]}")
            print(f"    fix_hint: {verdict.get('fix_hint','')}")
            fails.append(fp.stem)

    if fails:
        print(f"\n{len(fails)} eval failure(s): {', '.join(fails)}", file=sys.stderr)
        return 1
    print("\nall evals passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
