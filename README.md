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

Reads the knowledge base and the SDK `discover` response from your backend Environment Factory to design three test data environments: `standard` (realistic variety), `empty` (empty states), and `large` (pagination/performance). Outputs `autonoma/discover.json` plus `autonoma/scenarios.md`, preserving the legacy scenario summary while adding schema metadata and minimal variable-field planning.

**You review**: entity names, counts, relationships, and which values truly must stay generated. Fixed values are preferred because they become stable test assertions; if uniqueness is needed, the planner should first prefer concrete hardcoded values with a discriminator. Variable fields are exceptions used only for genuinely dynamic values. Generator hints are optional and are not tied to `faker`.

### Step 3: E2E Tests

Generates markdown test files organized by feature in `autonoma/qa-tests/`. Each test has frontmatter (title, description, criticality, scenario, flow) and uses only natural-language steps: click, scroll, type, assert.

An `INDEX.md` tracks total test count, folder breakdown, and coverage correlation with your codebase size.

`scenarios.md` is fixture input for this step, not the subject under test. Step 3 should not spend test budget verifying seeded counts or Environment Factory correctness.

**You review**: test distribution and coverage correlation. Test count should roughly match 3-5x your route/feature count.

### Step 4: Environment Factory

Implements or completes the backend Environment Factory so the planned scenarios can actually be created and torn down through the current SDK contract. Step 4 includes backend wiring plus validation: `discover`, `up`, `down`, request signing, refs signing, a smoke-tested lifecycle, and validation of the planned scenarios with `autonoma/scenario-recipes.json`. After validation, the plugin uploads the parsed recipe document to the setup API through the dedicated `scenario-recipe-versions` route so Step 04 in `agent` can persist normalized scenario data directly.

**You review**: where the Environment Factory lives, what changed, whether a smoke `discover` → `up` → `down` check passed, and whether `standard`, `empty`, and `large` all passed lifecycle validation.

---

## Autonoma Ad Hoc Planner

A second plugin in this repository that runs the same 4-step pipeline but scopes Step 3 to a user-defined focus area. Use it when you want targeted test coverage for a specific feature without regenerating your full test suite.

### Install

**Step 1:** The marketplace is the same as above. If you've already added it, skip this:

```
/plugin marketplace add Autonoma-AI/test-planner-plugin
```

**Step 2:** Install the ad hoc plugin:

```
/plugin install autonoma-adhoc-planner@autonoma
```

### Usage

Inside any project with Claude Code:

Pass your focus description directly after the command:

```
/autonoma-adhoc-planner:generate-adhoc-tests description
```

Or invoke without arguments and the plugin will suggest focus areas based on your codebase:

```
/autonoma-adhoc-planner:generate-adhoc-tests
```

The plugin walks you through 4 steps, asking for confirmation at each checkpoint before proceeding.

## How it works

### How it differs from the main planner

Steps 1, 2, and 4 run identically to the main planner. Step 3 is scoped:

| Step | Main planner | Ad hoc planner |
|------|-------------|----------------|
| 1 — Knowledge Base | Full codebase | Full codebase |
| 2 — Scenarios | Full data model | Full data model |
| 3 — E2E Tests | All features | **Focus area only** |
| 4 — Environment Factory | All scenarios | All scenarios |

Tests are written to `autonoma/qa-tests/{focus-slug}/` so they sit alongside your existing test suite without overwriting it. Running the ad hoc planner twice with different focus areas produces two separate subfolders.

### Running multiple focus areas

You can run the ad hoc planner multiple times for different topics, including simultaneously. Each run writes to its own subfolder and tracks its own generation ID file.

```
autonoma/qa-tests/
├── canvas-interactions/      ← autonoma/.generation-id-canvas-interactions
└── signatures-and-documents/ ← autonoma/.generation-id-signatures-and-documents
```


---

## Scenario Recipes

`autonoma/scenario-recipes.json` is the validated handoff between planning and execution. It is produced in Step 4 after the Environment Factory has been implemented or verified and after each scenario has passed lifecycle validation.

The file contains:

- top-level metadata: `version`, `source`, and `validationMode`
- one recipe per named scenario, usually `standard`, `empty`, and `large`
- for each recipe:
  - `name` and `description`
  - `create`: the inline data graph Autonoma will send to the SDK `up` action
  - `validation`: proof that the recipe passed `checkScenario`, `checkAllScenarios`, or endpoint lifecycle validation

Conceptually, a scenario recipe is not a test case. It is a data fixture definition for the Environment Factory. The `create` payload describes which records should exist before a run starts, including nested records and references such as `_alias` and `_ref`.

Example shape:

```json
{
  "version": 1,
  "source": {
    "discoverPath": "autonoma/discover.json",
    "scenariosPath": "autonoma/scenarios.md"
  },
  "validationMode": "sdk-check",
  "recipes": [
    {
      "name": "standard",
      "description": "Realistic baseline workspace",
      "create": {
        "User": [{ "email": "{{owner_email}}" }]
      },
      "variables": {
        "owner_email": {
          "strategy": "derived",
          "source": "testRunId",
          "format": "owner+{testRunId}@example.com"
        }
      },
      "validation": {
        "status": "validated",
        "method": "checkScenario",
        "phase": "ok"
      }
    }
  ]
}
```

Persisted recipes store tokenized `create` payloads plus `variables` metadata — never resolved concrete values. The `variables` field defines how each `{{token}}` is resolved at runtime using one of three strategies: `literal`, `derived` (from `testRunId`), or `faker`. This allows the `agent` to resolve the same tokens later for real runs.

During Step 4, the plugin runs a preflight check that resolves tokens into transient concrete payloads and sends signed `up`/`down` requests to the live SDK endpoint. The write hook also enforces that same preflight before a final `autonoma/scenario-recipes.json` write is accepted. These transient values are never persisted.

Storage semantics:

- in this plugin repo, `autonoma/scenario-recipes.json` is a local output artifact so the user and validators can inspect it
- when uploaded to `agent`, the backend does not keep the raw JSON file as text
- instead, `agent` parses the document and stores the approved scenario recipe data in its scenario JSONB storage through the `scenario-recipe-versions` setup endpoint

Runtime semantics:

- the planner still thinks in named scenarios like `standard`, `empty`, and `large`
- the SDK protocol does not require those names on the wire
- before a run, Autonoma resolves the active stored recipe version for the selected scenario and sends its `create` payload to the Environment Factory `up` action
- after the run, Autonoma calls `down` using the returned teardown refs/token

## Validation

Every output file has YAML frontmatter validated by shell scripts (not prompts). If validation fails, Claude sees the error and must fix it before proceeding.

| File | What's validated |
|------|-----------------|
| `AUTONOMA.md` | core_flows table, app description, feature/skill counts |
| `discover.json` | SDK discover schema shape: models, edges, relations, scopeField, and supported `type` formats |
| `scenarios.md` | scenario count, required scenarios (standard/empty/large), entity types, discover metadata, minimal variable fields |
| `scenario-recipes.json` | validated recipe file, discover-aware model/field/type parity, required scenarios, optional variables consistency, and mandatory live endpoint preflight |
| `INDEX.md` | test totals match folder sums, criticality counts sum correctly, test count within expected range |
| Each test file | title, description, criticality (critical/high/mid/low), scenario, flow |

## Environment Variables

Step 2 and Step 4 use the live SDK endpoint when fetching `discover` or validating through HTTP:

```bash
AUTONOMA_SDK_ENDPOINT=<your sdk endpoint url>
AUTONOMA_SHARED_SECRET=<shared HMAC secret>
```

Step 4 backend implementation uses the current SDK secret names:

```bash
AUTONOMA_SHARED_SECRET=<shared HMAC secret>
AUTONOMA_SIGNING_SECRET=<private refs signing secret>
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
│   ├── plugin.json                     # Plugin manifest (autonoma-test-planner)
│   └── marketplace.json                # Marketplace catalog (lists both plugins)
├── skills/generate-tests/SKILL.md      # /generate-tests orchestrator
├── commands/generate-tests.md          # /generate-tests command
├── agents/
│   ├── kb-generator.md                 # Step 1 subagent
│   ├── scenario-generator.md           # Step 2 subagent
│   ├── test-case-generator.md          # Step 3 subagent
│   └── env-factory-generator.md        # Step 4 subagent
├── hooks/
│   ├── hooks.json                      # PostToolUse hook config
│   ├── validate-pipeline-output.sh     # Validation dispatcher
│   ├── preflight_scenario_recipes.py   # Preflight resolver + endpoint lifecycle checker
│   └── validators/
│       ├── validate_kb.py
│       ├── validate_discover.py
│       ├── validate_scenario_recipes.py
│       ├── validate_scenarios.py
│       ├── validate_test_index.py
│       └── validate_test_file.py
├── adhoc/                              # autonoma-adhoc-planner plugin root
│   ├── .claude-plugin/
│   │   └── plugin.json                 # Plugin manifest (autonoma-adhoc-planner)
│   ├── skills/generate-adhoc-tests/
│   │   └── SKILL.md                    # /generate-adhoc-tests orchestrator
│   ├── commands/
│   │   └── generate-adhoc-tests.md     # /generate-adhoc-tests command
│   ├── agents/
│   │   └── focused-test-case-generator.md  # Step 3 focused subagent
│   └── hooks/
│       ├── hooks.json                  # PostToolUse hook config
│       ├── validate-pipeline-output.sh # Validation dispatcher
│       └── validators/
│           ├── validate_test_file.py
│           ├── validate_test_index.py
│           └── validate_directory_structure.py
├── LICENSE
└── README.md
```

## Documentation

Full prompt documentation: [docs.agent.autonoma.app/llms.txt](https://docs.agent.autonoma.app/llms.txt)

## License

MIT
