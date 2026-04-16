---
name: generate-tests
description: >
  Generates E2E test cases for a codebase through a validated multi-step pipeline.
  Each step runs in an isolated subagent and must pass deterministic validation
  before the next step begins. Use when the user wants to generate tests, create
  test scenarios, or build a test suite for their project.
---

# Autonoma E2E Test Generation Pipeline

You are orchestrating a 5-step test generation pipeline. Each step runs as an isolated subagent.
**Every step MUST complete successfully and pass validation before the next step begins.**
Do NOT skip steps. Do NOT proceed if validation fails.

## CRITICAL: User Confirmation Between Steps

After each step (1, 2, 3, and 4), you MUST present the summary and then ask the user for
confirmation using the `AskUserQuestion` tool. This creates an interactive
UI prompt that makes it clear the user needs to respond before the pipeline continues.

After calling `AskUserQuestion`, wait for the user's response.
Only proceed to the next step after they confirm.

## How lifecycle reporting works

You do NOT issue `curl` commands to report step start/complete/uploads. That is handled
automatically by plugin hooks:

- The `UserPromptSubmit` hook (`pipeline-kickoff.sh`) runs when the user invokes
  `/generate-tests`. It creates the setup record, writes `autonoma/.generation-id` and
  `autonoma/.docs-url`, and emits `step.started` for step 0.
- The `PostToolUse` hook (`validate-pipeline-output.sh`) runs after every `Write`. It
  validates output files, emits `step.completed` + `step.started` for the next step,
  and uploads artifacts (skills after step 1, test cases after step 5). Idempotent —
  each transition fires at most once per generation.
- The env-factory agent (step 4) writes a sentinel file `autonoma/.env-factory-validated`
  after it finishes validating the up/down lifecycle. The hook sees that file and emits
  `step.completed` for step 3 and `step.started` for step 4.

Your job is to spawn subagents and gate between them with `AskUserQuestion`. Reporting is
hook territory — do not duplicate it.

## Before Starting

Create the output directory:
```bash
mkdir -p autonoma/skills autonoma/qa-tests
```

The kickoff hook has already written `autonoma/.docs-url` and `autonoma/.generation-id`.
Subagents read the docs URL from that file; you don't need to pass it through.

## Step 1: Generate Knowledge Base

Spawn the `kb-generator` subagent with the following task:

> Analyze the codebase and generate the knowledge base. Write the output to `autonoma/AUTONOMA.md`
> and create skill files in `autonoma/skills/`. The file MUST have YAML frontmatter with
> app_name, app_description, core_flows (feature/description/core table), feature_count, and skill_count.
> You MUST also write `autonoma/features.json` — a machine-readable inventory of every feature discovered.
> It must have: features array (each with name, type, path, core), total_features, total_routes, total_api_routes.
> Fetch the latest instructions by running `curl -sSfL "$(cat autonoma/.docs-url)/llms/test-planner/step-1-knowledge-base.txt"` in the Bash tool first. If curl fails, stop and report — do not substitute any other URL.

**After the subagent completes:**
1. Verify `autonoma/AUTONOMA.md` and `autonoma/features.json` exist and are non-empty
2. The PostToolUse hook will have validated the frontmatter and features.json schema automatically, emitted `step.completed` for step 0, and uploaded the generated skills. `step.started` for step 1 fires only after the user confirms (see step 6).
3. Read the file and present the frontmatter to the user — specifically the core_flows table
4. Call `AskUserQuestion` with:
   - question: "Does this core flows table look correct? These flows determine how the test budget is distributed."
   - options: ["Yes, proceed to Step 2", "I want to suggest changes"]
5. Wait for the user's response before proceeding.
6. After the user confirms, use the `Write` tool to create `autonoma/.step-1-ack` with a single-character body (e.g. `.`). The hook converts that into `step.started` for step 1, advancing the UI indicator. Do NOT use `touch` — the hook only fires on `Write`/`Edit`.

## Step 2: Entity Creation Audit

Spawn the `entity-audit-generator` subagent with the following task:

> Read the knowledge base from `autonoma/AUTONOMA.md` and `autonoma/skills/`.
> Audit how each database model is created in the codebase. For every model, find the dedicated
> creation function (in a service, repository, or helper) that will be used to instantiate it.
> Classify each model as `has_creation_code: true` (a dedicated create function exists → factory)
> or `has_creation_code: false` (no dedicated function, only inline ORM calls → raw SQL fallback).
> The rule is structural — a thin wrapper still gets `has_creation_code: true` because the user
> might add business logic later. Record any side effects (password hashing, slug generation, etc.)
> as `side_effects` — informational only, they do NOT affect classification.
> Output to `autonoma/entity-audit.md` with YAML frontmatter listing each model with name,
> has_creation_code, reason, creation_file, creation_function, and optional side_effects.
> Fetch the latest instructions by running `curl -sSfL "$(cat autonoma/.docs-url)/llms/test-planner/step-2-entity-audit.txt"` in the Bash tool first. If curl fails, stop and report — do not substitute any other URL.

**After the subagent completes:**
1. Verify `autonoma/entity-audit.md` exists and is non-empty
2. The PostToolUse hook will have validated the frontmatter schema automatically and emitted `step.completed` for step 1. `step.started` for step 2 fires only after the user confirms (see step 6).
3. Read the file and present the frontmatter to the user — specifically which models have creation code (and will get factories) and which will fall back to raw SQL
4. Call `AskUserQuestion` with:
   - question: "Does this entity audit look correct? Models with `has_creation_code: true` will get factories that call your real create function. Models with `has_creation_code: false` will use raw SQL INSERT."
   - options: ["Yes, proceed to Step 3", "I want to suggest changes"]
5. Wait for the user's response before proceeding.
6. After the user confirms, use the `Write` tool to create `autonoma/.step-2-ack` with a single-character body (e.g. `.`). The hook converts that into `step.started` for step 2.

## Step 3: Generate Scenarios

Spawn the `scenario-generator` subagent with the following task:

> Read the knowledge base from `autonoma/AUTONOMA.md` and `autonoma/skills/`.
> Generate test data scenarios. Write the output to `autonoma/scenarios.md`.
> The file MUST have YAML frontmatter with scenario_count, scenarios summary, and entity_types.
> Fetch the latest instructions by running `curl -sSfL "$(cat autonoma/.docs-url)/llms/test-planner/step-2-scenarios.txt"` in the Bash tool first. If curl fails, stop and report — do not substitute any other URL.

**After the subagent completes:**
1. Verify `autonoma/scenarios.md` exists and is non-empty
2. The PostToolUse hook will have validated the frontmatter format automatically and emitted `step.completed` for step 2. `step.started` for step 3 fires only after the user confirms (see step 6).
3. Read the file and present the frontmatter summary to the user — scenario names, entity counts, entity types
4. Call `AskUserQuestion` with:
   - question: "Do these scenarios look correct? The standard scenario data becomes hard assertions in your tests."
   - options: ["Yes, proceed to Step 4 (implement scenarios)", "I want to suggest changes"]
5. Wait for the user's response before proceeding.
6. After the user confirms, use the `Write` tool to create `autonoma/.step-3-ack` with a single-character body (e.g. `.`). The hook converts that into `step.started` for step 3.

## Step 4: Implement & Validate Environment Factory

Spawn the `env-factory-generator` subagent with the following task:

> Read the entity audit from `autonoma/entity-audit.md` and the scenarios from `autonoma/scenarios.md`,
> then set up the Autonoma Environment Factory endpoint in the project's backend using the SDK.
> Install SDK packages and configure the handler. For every model with `has_creation_code: true`
> in the audit, register a factory that calls the audit's identified `creation_file` / `creation_function`
> — no exceptions, even for thin wrappers. Models with `has_creation_code: false` use the SDK's
> raw SQL fallback automatically (do not register factories for them). Validate the full up/down
> lifecycle with curl before completing. **After validation passes, write the sentinel file
> `autonoma/.env-factory-validated`** — the plugin hook watches for that file and uses it to
> mark step 3 complete.
> Fetch the latest instructions by running `curl -sSfL "$(cat autonoma/.docs-url)/llms/test-planner/step-4-implement-scenarios.txt"` and `curl -sSfL "$(cat autonoma/.docs-url)/llms/guides/environment-factory.txt"` in the Bash tool first. If either curl fails, stop and report — do not substitute any other URL.
> Use AUTONOMA_SHARED_SECRET and AUTONOMA_SIGNING_SECRET as environment variable names.

**After the subagent completes:**
1. Verify the endpoint was created and the lifecycle was validated
2. Verify `autonoma/.env-factory-validated` exists — if it doesn't, validation didn't pass and you must not proceed
3. The PostToolUse hook will have emitted `step.completed` for step 3 when the sentinel was written. `step.started` for step 4 fires only after the user confirms (see step 7).
4. Present the results to the user — what was implemented, where, validation results
5. Call `AskUserQuestion` with:
   - question: "The Environment Factory is set up and the scenario lifecycle has been validated. Does everything look correct?"
   - options: ["Yes, proceed to Step 5 (generate tests)", "I want to suggest changes"]
6. Wait for the user's response before proceeding.
7. After the user confirms, use the `Write` tool to create `autonoma/.step-4-ack` with a single-character body (e.g. `.`). The hook converts that into `step.started` for step 4.

## Step 5: Generate E2E Test Cases

Spawn the `test-case-generator` subagent with the following task:

> Read the knowledge base from `autonoma/AUTONOMA.md`, skills from `autonoma/skills/`,
> and scenarios from `autonoma/scenarios.md`.
> Generate complete E2E test cases as markdown files in `autonoma/qa-tests/`.
> You MUST create `autonoma/qa-tests/INDEX.md` with frontmatter containing total_tests,
> total_folders, folder breakdown, and coverage_correlation.
> Each test file MUST have frontmatter with title, description, criticality, scenario, and flow.
> Fetch the latest instructions by running `curl -sSfL "$(cat autonoma/.docs-url)/llms/test-planner/step-3-e2e-tests.txt"` in the Bash tool first. If curl fails, stop and report — do not substitute any other URL.
> Note: The scenario data has been validated in Step 4 — the Environment Factory can create and tear down all entities.

**After the subagent completes:**
1. Verify `autonoma/qa-tests/INDEX.md` exists and is non-empty
2. The PostToolUse hook will have validated the INDEX frontmatter, individual test file frontmatter, emitted step 4 completed, and uploaded the test cases to the dashboard
3. Read the INDEX.md and present the summary to the user — total tests, folder breakdown, coverage correlation

## Completion

After all steps complete, summarize:
- **Step 1**: Knowledge base location and core flow count
- **Step 2**: Entity audit — models audited, how many need factories, key side effects found
- **Step 3**: Scenario count and entity types covered
- **Step 4**: Endpoint location, packages installed, factories registered, validation results
- **Step 5**: Total test count, folder breakdown, coverage correlation
