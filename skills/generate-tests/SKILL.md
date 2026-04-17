---
name: generate-tests
description: >
  Generates E2E test cases for a codebase through a validated multi-step pipeline.
  Each step runs in an isolated subagent and must pass deterministic validation
  before the next step begins. Use when the user wants to generate tests, create
  test scenarios, or build a test suite for their project.
---

# Autonoma E2E Test Generation Pipeline

You are orchestrating a 6-step test generation pipeline. Each step runs as an isolated subagent.
**Every step MUST complete successfully and pass validation before the next step begins.**
Do NOT skip steps. Do NOT proceed if validation fails.

## CRITICAL: User Confirmation Between Steps

After steps 1, 2, 3, 4, and 5 you MUST present the summary and ask the user for confirmation
using `AskUserQuestion`. After calling it, wait for the response. Only proceed after they confirm.

## How lifecycle reporting works

You do NOT issue `curl` commands to report step start/complete/uploads. Plugin hooks do that:

- `UserPromptSubmit` (`pipeline-kickoff.sh`) creates the setup record on `/generate-tests`.
- `PostToolUse` (`validate-pipeline-output.sh`) runs after every `Write`. It validates output,
  emits `step.completed`/`step.started`, uploads artifacts, and enforces the validation gate
  (test files cannot be written until `autonoma/.endpoint-validated` exists).

## Before Starting

```bash
mkdir -p autonoma/skills autonoma/qa-tests
```

The kickoff hook has already written `autonoma/.docs-url` and `autonoma/.generation-id`.

## Step 1: Generate Knowledge Base

Spawn `kb-generator`:

> Analyze the codebase and generate the knowledge base. Write `autonoma/AUTONOMA.md` with YAML
> frontmatter (app_name, app_description, core_flows, feature_count, skill_count), create skill
> files in `autonoma/skills/`, and write `autonoma/features.json` (features array + totals).
> Fetch instructions first: `curl -sSfL "$(cat autonoma/.docs-url)/llms/test-planner/step-1-knowledge-base.txt"`.

After completion: verify files exist, present core_flows table, `AskUserQuestion`, then `Write` `autonoma/.step-1-ack` (single character body).

## Step 2: Entity Creation Audit

Spawn `entity-audit-generator`:

> Read the knowledge base. Audit how each database model is created. For every model, find the
> dedicated creation function in a service/repository/helper. Classify as `has_creation_code: true`
> (factory) or `false` (raw SQL fallback). Record side_effects (informational). Output
> `autonoma/entity-audit.md` with frontmatter listing each model.
> Fetch: `curl -sSfL "$(cat autonoma/.docs-url)/llms/test-planner/step-2-entity-audit.txt"`.

After completion: present the audit, `AskUserQuestion`, `Write` `autonoma/.step-2-ack`.

## Step 3: Generate Scenarios

Spawn `scenario-generator`:

> Read the knowledge base. Generate test data scenarios. Write `autonoma/scenarios.md` with
> frontmatter (scenario_count, scenarios summary, entity_types).
> Fetch: `curl -sSfL "$(cat autonoma/.docs-url)/llms/test-planner/step-2-scenarios.txt"`.

After completion: present scenarios, `AskUserQuestion`, `Write` `autonoma/.step-3-ack`.

## Step 4: Implement Environment Factory

Spawn `env-factory-generator`:

> Read `autonoma/entity-audit.md` and `autonoma/scenarios.md`. Install SDK packages and configure
> the handler. Register a factory for every model with `has_creation_code: true` (call the audit's
> `creation_file`/`creation_function` — never reimplement inline). Implement the auth callback
> using the app's real session/token creation. Run a `discover` smoke test. Run the factory-integrity
> check. Then `Write` `autonoma/.endpoint-implemented` with a short summary. Do NOT run `up`/`down`
> — that is step 5.
> Fetch: `curl -sSfL "$(cat autonoma/.docs-url)/llms/test-planner/step-4-implement-scenarios.txt"`
> and `curl -sSfL "$(cat autonoma/.docs-url)/llms/guides/environment-factory.txt"`.
> Use `AUTONOMA_SHARED_SECRET` and `AUTONOMA_SIGNING_SECRET` as env var names.

After completion: verify `autonoma/.endpoint-implemented` exists, present implementation summary,
`AskUserQuestion` ("Ready to validate the full up/down lifecycle?"), `Write` `autonoma/.step-4-ack`.

## Step 5: Validate Scenario Lifecycle

Spawn `scenario-validator`:

> Read `autonoma/entity-audit.md`, `autonoma/scenarios.md`, and the handler created in step 4.
> Run `discover`/`up`/`down` against every scenario with HMAC-signed curl. Iterate (up to 5
> times): if a scenario fails because of a handler bug, fix the handler and retry; if it fails
> because the scenario itself is wrong/unfeasible, edit `scenarios.md` to match reality. On
> success for every scenario, `Write` `autonoma/.endpoint-validated` with a summary. If you
> hit the iteration cap, STOP and report — do NOT write the sentinel.
> Verify: every audited model appears in `discover.schema.models`, every `has_creation_code`
> model has a registered factory, `auth` is non-empty, and DB state is correct before and after
> `down`.

After completion:
1. If `autonoma/.endpoint-validated` exists: present validation summary (scenarios passed,
   any edits made to `scenarios.md`), `AskUserQuestion`, `Write` `autonoma/.step-5-ack`.
2. If it does NOT exist: the agent failed — surface the failure report to the user and STOP.
   Do NOT proceed to step 6. The validation gate in the hook will also block test file writes.

## Step 6: Generate E2E Test Cases

Spawn `test-case-generator`:

> Read `autonoma/AUTONOMA.md`, `autonoma/skills/`, and `autonoma/scenarios.md` (the latter has
> been reconciled with reality in step 5 — use it as the source of truth). Generate test cases
> in `autonoma/qa-tests/`. Write `autonoma/qa-tests/INDEX.md` with frontmatter (total_tests,
> total_folders, folder breakdown, coverage_correlation). Each test file needs frontmatter
> (title, description, criticality, scenario, flow).
> Fetch: `curl -sSfL "$(cat autonoma/.docs-url)/llms/test-planner/step-3-e2e-tests.txt"`.

After completion:
1. Verify `autonoma/qa-tests/INDEX.md` exists
2. Present INDEX summary
3. `Write` `autonoma/.pipeline-complete` with a short summary. The hook emits `step.completed`
   for the final step, marking the setup complete.

## Completion

Summarize each step:
- **Step 1**: KB location, core flows
- **Step 2**: entity audit — factories vs raw SQL
- **Step 3**: scenarios generated
- **Step 4**: endpoint implemented (handler path, packages, factories registered)
- **Step 5**: lifecycle validated, scenarios.md edits (if any)
- **Step 6**: test count, folder breakdown
