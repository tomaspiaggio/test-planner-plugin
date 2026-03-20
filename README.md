# Autonoma Test Planner

A Claude Code plugin that generates comprehensive E2E test suites for your codebase through a validated 4-step pipeline.

Each step runs in an isolated subagent with deterministic validation — shell scripts check the output format before the pipeline advances. No hallucinated validations, no cascading errors.

## Install

**Step 1:** Add the marketplace:

```
/plugin marketplace add Autonoma-AI/test-planner-plugin
```

**Step 2:** Install the plugin:

```
/plugin install autonoma-test-planner@autonoma
```

## Usage

Inside any project with Claude Code:

```
/autonoma-test-planner:generate-tests
```

The plugin walks you through 4 steps, asking for confirmation at each checkpoint before proceeding.

## How it works

### Step 1: Knowledge Base

Analyzes your frontend codebase and produces `autonoma/AUTONOMA.md` — a user-perspective map of every page, flow, and feature. The file includes YAML frontmatter with a core flows table that determines how test coverage is distributed.

**You review**: the core flows table. If a flow is marked `core: true`, it gets 50-60% of test coverage.

### Step 2: Scenarios

Reads the knowledge base and your backend data model to design three test data environments: `standard` (realistic variety), `empty` (empty states), and `large` (pagination/performance). Outputs `autonoma/scenarios.md` with frontmatter summarizing each scenario.

**You review**: entity names, counts, and relationships. These become hard assertions in your tests.

### Step 3: E2E Tests

Generates markdown test files organized by feature in `autonoma/qa-tests/`. Each test has frontmatter (title, description, criticality, scenario, flow) and uses only natural-language steps: click, scroll, type, assert.

An `INDEX.md` tracks total test count, folder breakdown, and coverage correlation with your codebase size.

**You review**: test distribution and coverage correlation. Test count should roughly match 3-5x your route/feature count.

### Step 4: Environment Factory

Implements an endpoint in your backend that creates and tears down isolated test data for each scenario. Handles `discover`, `up`, and `down` actions with HMAC-SHA256 request signing and JWT-signed refs for safe teardown.

**You review**: implementation plan before any code is written. The endpoint never modifies existing data.

## Validation

Every output file has YAML frontmatter validated by shell scripts (not prompts). If validation fails, Claude sees the error and must fix it before proceeding.

| File | What's validated |
|------|-----------------|
| `AUTONOMA.md` | core_flows table, app description, feature/skill counts |
| `scenarios.md` | scenario count, required scenarios (standard/empty/large), entity types |
| `INDEX.md` | test totals match folder sums, criticality counts sum correctly, test count within expected range |
| Each test file | title, description, criticality (critical/high/mid/low), scenario, flow |

## Environment Variables (Step 4)

Step 4 requires two secrets for the Environment Factory endpoint:

```bash
# Generate secrets
openssl rand -hex 32  # AUTONOMA_SIGNING_SECRET
openssl rand -hex 32  # AUTONOMA_JWT_SECRET
```

Add to your `.env`:
```
AUTONOMA_SIGNING_SECRET=<first-value>
AUTONOMA_JWT_SECRET=<second-value>
```

## Requirements

- Claude Code
- Python 3 (ships with macOS/Linux)
- PyYAML (auto-installed if missing)

## Local Development

```bash
# Test locally without installing
claude --plugin-dir ./

# Validate plugin structure
claude plugin validate ./
```

## Project Structure

```
autonoma-test-planner/
├── .claude-plugin/
│   ├── plugin.json                     # Plugin manifest
│   └── marketplace.json                # Marketplace catalog
├── skills/generate-tests/SKILL.md      # /generate-tests orchestrator
├── agents/
│   ├── kb-generator.md                 # Step 1 subagent
│   ├── scenario-generator.md           # Step 2 subagent
│   ├── test-case-generator.md          # Step 3 subagent
│   └── env-factory-generator.md        # Step 4 subagent
├── hooks/
│   ├── hooks.json                      # PostToolUse hook config
│   ├── validate-pipeline-output.sh     # Validation dispatcher
│   └── validators/
│       ├── validate_kb.py
│       ├── validate_scenarios.py
│       ├── validate_test_index.py
│       └── validate_test_file.py
├── LICENSE
└── README.md
```

## Documentation

Full prompt documentation: [docs.agent.autonoma.app/llms.txt](https://docs.agent.autonoma.app/llms.txt)

## License

MIT
