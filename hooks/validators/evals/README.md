# Factory-fidelity evals

Ad-hoc eval harness for the semantic validator in `../validate_factory_fidelity.py`.
Each fixture simulates one model's Step 2 audit entry, current audit entry,
factory block, helper (optional), and original creation snippet, then asserts
the verdict the rubric should produce.

## Run

```bash
# against a local Astro dev server
AUTONOMA_DOCS_URL=http://localhost:4321 \
    python3 hooks/validators/evals/run_evals.py

# single fixture
AUTONOMA_DOCS_URL=http://localhost:4321 \
    python3 hooks/validators/evals/run_evals.py --only good_uses_service

# dump the rendered prompt without calling claude (for debugging)
AUTONOMA_DOCS_URL=http://localhost:4321 \
    python3 hooks/validators/evals/run_evals.py --write-prompt
```

Requires the `claude` CLI on `PATH`. Model is configurable via
`AUTONOMA_FIDELITY_MODEL` (defaults to `sonnet`).

## Fixture schema

```json
{
  "model": "<PascalCase model name>",
  "expected_verdict": "pass" | "fail",
  "expected_fail_criteria": [1, 2, 3, 4],
  "step2_audit_entry": "<YAML list-item string for the snapshot>",
  "current_audit_entry": "<YAML list-item string for the current audit>",
  "handler_path": "<synthetic path>",
  "factory_block": "<defineFactory registration snippet>",
  "helper_section": "File: <path>\\nFunction: <name>\\n\\n```\\n<code>\\n```",
  "original_creation_file": "<path>",
  "original_creation_snippet": "<source of the Step 2 creation_function>"
}
```

Keep fixtures generic — placeholder names (`UserService`, `src/users/...`) only,
no references to real Autonoma-internal codebases. The rubric itself is generic;
evals that leak specific names would mask rubric bias.

## When to add a fixture

- New failure mode observed in the wild → add a `bad_*.json` that captures it
  with the smallest reproduction, and confirm the current rubric catches it.
- Rubric edit → run the full suite against the new rubric. A fixture flipping
  verdict is a signal that the criteria are ambiguous; tighten the wording.
