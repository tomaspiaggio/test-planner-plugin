#!/usr/bin/env python3
"""Evals for the semantic factory-fidelity validator.

Each fixture is a self-contained mini-case with: the Step 2 audit entry, the
current audit entry, the factory block the handler registered, the helper
(optional), and the original creation function snippet. Each fixture declares
an expected verdict (`pass` or `fail`) and, for fails, the set of criteria
IDs we expect to be marked `fail`.

The harness fetches the live rubric from quarita docs (same URL the
`.endpoint-implemented` hook uses), builds the prompt, runs `claude -p` once
per fixture, and compares the returned verdict to the expectation. A mismatch
is a test failure.

Run:
    AUTONOMA_DOCS_URL=http://localhost:4321 python3 hooks/validators/evals/run_evals.py
    # or against the deployed docs:
    AUTONOMA_DOCS_URL=https://autonoma.ai/docs python3 hooks/validators/evals/run_evals.py

    # single fixture:
    ... run_evals.py --only good_uses_service

Exits 0 if every fixture's observed verdict matches its expectation, 1 otherwise.

This is intentionally a script, not a pytest file — we want to run it ad-hoc
against different docs URLs and against different claude CLI models, and
skipping the expensive CLI in a normal test suite is awkward without env
plumbing pytest doesn't have out of the box.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
VALIDATORS = HERE.parent
sys.path.insert(0, str(VALIDATORS))

import validate_factory_fidelity as v  # noqa: E402


def load_fixture(path: Path) -> dict:
    return json.loads(path.read_text())


def run_one(fixture: dict, rubric: str, tpl: str) -> dict:
    prompt = (
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
    return v.run_claude(prompt)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="Run a single fixture by name (no extension)")
    ap.add_argument("--write-prompt", action="store_true", help="Write the rendered prompt for each fixture to stdout and exit without calling claude")
    args = ap.parse_args()

    os.chdir(VALIDATORS.parent.parent)
    Path("autonoma").mkdir(exist_ok=True)
    url_file = Path("autonoma/.docs-url")
    restore = url_file.exists()
    prior = url_file.read_text() if restore else None
    docs = os.environ.get("AUTONOMA_DOCS_URL")
    if docs:
        url_file.write_text(docs.strip())
    try:
        pair = v.fetch_rubric()
    finally:
        if restore:
            url_file.write_text(prior or "")
        elif docs:
            try:
                url_file.unlink()
            except OSError:
                pass
    if not pair:
        print("could not fetch rubric — set AUTONOMA_DOCS_URL", file=sys.stderr)
        return 1
    rubric, tpl = pair

    fixtures_dir = HERE / "fixtures"
    fixtures = sorted(fixtures_dir.glob("*.json"))
    if args.only:
        fixtures = [f for f in fixtures if f.stem == args.only]
        if not fixtures:
            print(f"no fixture named {args.only}", file=sys.stderr)
            return 1

    fails: list[str] = []
    for fp in fixtures:
        fixture = load_fixture(fp)
        if args.write_prompt:
            rendered = (
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
            print(f"── {fp.stem} ──")
            print(rendered)
            print()
            continue
        verdict = run_one(fixture, rubric, tpl)
        observed = verdict.get("verdict", "error")
        expected = fixture["expected_verdict"]
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
