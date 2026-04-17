# Autonoma Test Planner Plugin

Claude Code plugin that generates E2E test suites through a deterministic 5-step pipeline.

## Project Structure

```text
.claude-plugin/              # Plugin manifest
commands/generate-tests.md   # Command entry
skills/generate-tests/SKILL.md
agents/
  sdk-integrator.md          # Step 1: SDK integration
  kb-generator.md            # Step 2: Knowledge base
  scenario-generator.md      # Step 3: Scenarios
  test-case-generator.md     # Step 4: E2E tests
  scenario-validator.md      # Step 5: Scenario validation
hooks/
  hooks.json
  validate-pipeline-output.sh
  preflight_scenario_recipes.py
  validators/
tests/
```

## Pipeline

1. SDK Integration
2. Knowledge Base
3. Scenarios
4. E2E Tests
5. Scenario Validation

The canonical launch mode is `AUTONOMA_AUTO_ADVANCE=true`. If you are still using the older flag,
`AUTONOMA_REQUIRE_CONFIRMATION=false` is treated as the same auto-advance behavior. Step 5 is final.

## Validation

Validators are in `hooks/validators/`.

| Validator | File matched | Key checks |
|-----------|-------------|------------|
| `validate_kb.py` | `*/autonoma/AUTONOMA.md` | app_name, app_description, core_flows |
| `validate_discover.py` | `*/autonoma/discover.json` | schema object, models, edges, relations, scopeField |
| `validate_sdk_endpoint.py` | `*/autonoma/.sdk-endpoint` | absolute http/https URL |
| `validate_sdk_integration.py` | `*/autonoma/.sdk-integration.json` | Step 1 handoff contract |
| `validate_features.py` | `*/autonoma/features.json` | feature inventory schema |
| `validate_scenarios.py` | `*/autonoma/scenarios.md` | scenario count and metadata |
| `validate_scenario_validation.py` | `*/autonoma/.scenario-validation.json` | Step 5 terminal-state contract |
| `validate_scenario_recipes.py` | `*/autonoma/scenario-recipes.json` | recipe schema |
| `validate_test_index.py` | `*/autonoma/qa-tests/INDEX.md` | test totals and folder sums |
| `validate_test_file.py` | `*/autonoma/qa-tests/*/[!I]*.md` | test frontmatter |

Scenario recipes also run live endpoint preflight through `hooks/preflight_scenario_recipes.py`.

## Development

```bash
claude --plugin-dir ./
claude plugin validate ./
pytest
```

## Notes

- Step 1 installs the SDK from package managers only.
- The SDK reference repo is read-only context.
- Step 5 validates the live integration and does not edit backend code.
