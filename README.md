# Autonoma Test Planner

A Claude Code plugin that generates comprehensive E2E test suites for your codebase through a validated 5-step pipeline.

Each step runs in an isolated subagent with deterministic validation. The first step now integrates the Autonoma SDK directly into the target project, and the final step validates scenarios against that live endpoint without editing backend code.

## Install

```text
/plugin marketplace add Autonoma-AI/test-planner-plugin
/plugin install autonoma-test-planner@autonoma
```

## Usage

Inside any project with Claude Code:

```text
/autonoma-test-planner:generate-tests
```

The canonical launch mode is `AUTONOMA_AUTO_ADVANCE=true`, which keeps the plugin moving after
Steps 1-4. If you are still using the older confirmation flag, `AUTONOMA_REQUIRE_CONFIRMATION=false`
is treated as the same auto-advance behavior.

## Pipeline

### Step 1: SDK Integration

Detects the project stack, installs the Autonoma SDK from package managers, wires the endpoint, ensures secrets exist, starts or reuses a local dev server, verifies signed `discover` / `up` / `down`, and writes `autonoma/.sdk-endpoint` plus `autonoma/.sdk-integration.json`.

It may also create a branch, commit the integration, and open a PR when `gh` is available.

**You review**: detected stack, installed packages, endpoint URL, generated env vars, and PR status.

### Step 2: Knowledge Base

Analyzes the app and produces `autonoma/AUTONOMA.md` and `autonoma/features.json`.

**You review**: the core flows table.

### Step 3: Scenarios

Fetches `discover` from the Step 1 endpoint and produces `autonoma/discover.json` plus `autonoma/scenarios.md`.

**You review**: entity names, counts, relationships, and which values should stay concrete versus variable.

### Step 4: E2E Tests

Generates markdown test files in `autonoma/qa-tests/` plus `INDEX.md`.

**You review**: test distribution and coverage correlation.

### Step 5: Scenario Validation

Validates `standard`, `empty`, and `large` against the live SDK endpoint, writes `autonoma/scenario-recipes.json` plus `autonoma/.scenario-validation.json`, runs endpoint preflight, and uploads the approved recipes to the setup API only after all checks pass.

This step does **not** implement backend code. It only validates the existing integration.

## Key Outputs

- `autonoma/.sdk-endpoint`: validated SDK endpoint URL
- `autonoma/.sdk-integration.json`: Step 1 machine-readable handoff
- `autonoma/AUTONOMA.md`
- `autonoma/features.json`
- `autonoma/discover.json`
- `autonoma/scenarios.md`
- `autonoma/qa-tests/INDEX.md`
- `autonoma/.scenario-validation.json`: Step 5 terminal-state artifact
- `autonoma/scenario-recipes.json`

## Ad Hoc Test Generation

The same plugin includes a `generate-adhoc-tests` command that generates tests focused on a specific topic without regenerating your full test suite.

### Usage

Pass your focus description directly after the command:

```
/autonoma-test-planner:generate-adhoc-tests description
```

Or invoke without arguments and the command will suggest focus areas based on your codebase:

```
/autonoma-test-planner:generate-adhoc-tests
```

### How it works

**Subsequent runs** (scenarios already configured in Autonoma): fetches scenarios and existing tests from the Autonoma, then runs only focused test generation (Step 3). Steps 1, 2, and 4 are skipped.

Tests are written to `autonoma/qa-tests/{focus-slug}/` so they sit alongside your existing test suite without overwriting it.

### Running multiple focus areas

Each focus area run writes to its own subfolder and tracks its own generation ID file. Multiple topics can run in parallel:

```
autonoma/qa-tests/
├── canvas-interactions/      ← autonoma/.generation-id-canvas-interactions
└── signatures-and-documents/ ← autonoma/.generation-id-signatures-and-documents
```

## Environment Variables

Provide these before running the plugin:

```bash
AUTONOMA_API_KEY=<api key>
AUTONOMA_PROJECT_ID=<application id>
AUTONOMA_API_URL=<setup api base url>
```

Canonical:

```bash
AUTONOMA_AUTO_ADVANCE=true
```

Compatibility alias:

```bash
AUTONOMA_REQUIRE_CONFIRMATION=false
```

You no longer need to pre-provide `AUTONOMA_SDK_ENDPOINT` or `AUTONOMA_SHARED_SECRET`. Step 1 creates or discovers them in the target project.

The integration step updates `.env` and `.env.example` in the target repo with:

```bash
AUTONOMA_SHARED_SECRET=<shared hmac secret>
AUTONOMA_SIGNING_SECRET=<private signing secret>
```

Those changes still need to be deployed after PR creation or merge.

## Validation

Every pipeline output is validated by shell-dispatched Python validators.

| File | Validation |
| --- | --- |
| `AUTONOMA.md` | frontmatter and core-flow structure |
| `features.json` | feature inventory schema |
| `discover.json` | SDK discover schema |
| `.sdk-endpoint` | absolute `http` or `https` URL |
| `.sdk-integration.json` | Step 1 handoff contract |
| `scenarios.md` | scenario schema and required sections |
| `.scenario-validation.json` | Step 5 terminal-state contract |
| `scenario-recipes.json` | recipe schema plus live endpoint preflight |
| `INDEX.md` | test totals and folder breakdown |
| test files | required frontmatter |

## Local Development

```bash
claude --plugin-dir ./
claude plugin validate ./
pytest
```

## Project Structure

```text
autonoma-test-planner/
├── .claude-plugin/
├── commands/generate-tests.md
├── skills/generate-tests/SKILL.md
├── agents/
│   ├── sdk-integrator.md
│   ├── kb-generator.md
│   ├── scenario-generator.md
│   ├── test-case-generator.md
│   └── scenario-validator.md
├── hooks/
│   ├── validate-pipeline-output.sh
│   ├── preflight_scenario_recipes.py
│   └── validators/
├── adhoc/
│   ├── .claude-plugin/
│   ├── skills/generate-adhoc-tests/SKILL.md
│   ├── commands/generate-adhoc-tests.md
│   ├── agents/focused-test-case-generator.md
│   └── hooks/
│       ├── hooks.json
│       ├── validate-pipeline-output.sh
│       └── validators/
└── tests/
```

## License

MIT
