---
name: generate-tests
description: >
  Generates E2E test cases for a codebase through a validated multi-step pipeline.
  Each step runs in an isolated subagent and must pass deterministic validation
  before the next step begins. Use when the user wants to generate tests, create
  test scenarios, or build a test suite for their project.
---

# Autonoma E2E Test Generation Pipeline

You are orchestrating a 4-step test generation pipeline. Each step runs as an isolated subagent.
**Every step MUST complete successfully and pass validation before the next step begins.**
Do NOT skip steps. Do NOT proceed if validation fails.

## CRITICAL: User Confirmation Between Steps

<<<<<<< tomaspiaggio/features-json
After each step (1, 2, and 3), you MUST present the summary and then ask the user for
confirmation using the `AskUserQuestion` tool. This creates an interactive
UI prompt that makes it clear the user needs to respond before the pipeline continues.

After calling `AskUserQuestion`, wait for the user's response.
Only proceed to the next step after they confirm.
=======
After each step (1, 2, and 3), you MUST stop and wait for the user to respond before proceeding.
This means: present the summary, ask the confirmation question, and then **end your turn**.
Do NOT call any more tools. Do NOT spawn the next subagent. Do NOT continue with any work.
Your message must END with the confirmation question. The user's next message is their answer.
Only after the user explicitly confirms should you proceed to the next step.
>>>>>>> main

## Before Starting

Create the output directory:
```bash
mkdir -p autonoma/skills autonoma/qa-tests
```

## Step 1: Generate Knowledge Base

Spawn the `kb-generator` subagent with the following task:

> Analyze the codebase and generate the knowledge base. Write the output to `autonoma/AUTONOMA.md`
> and create skill files in `autonoma/skills/`. The file MUST have YAML frontmatter with
> app_name, app_description, core_flows (feature/description/core table), feature_count, and skill_count.
> You MUST also write `autonoma/features.json` — a machine-readable inventory of every feature discovered.
> It must have: features array (each with name, type, path, core), total_features, total_routes, total_api_routes.
> Fetch the latest instructions from https://docs.agent.autonoma.app/llms/test-planner/step-1-knowledge-base.txt first.

**After the subagent completes:**
1. Verify `autonoma/AUTONOMA.md` and `autonoma/features.json` exist and are non-empty
2. The PostToolUse hook will have validated the frontmatter and features.json schema automatically
3. Read the file and present the frontmatter to the user — specifically the core_flows table
<<<<<<< tomaspiaggio/features-json
4. Call `AskUserQuestion` with:
   - question: "Does this core flows table look correct? These flows determine how the test budget is distributed."
   - options: ["Yes, proceed to Step 2", "I want to suggest changes"]
5. Wait for the user's response before proceeding.
=======
4. End your message with exactly this question: **"Does this core flows table look correct? These flows determine how the test budget is distributed. Please confirm or suggest changes before I proceed to Step 2."**
5. **STOP. End your turn. Do NOT call any tools or spawn any agents. Wait for the user to reply.**
>>>>>>> main

## Step 2: Generate Scenarios

Spawn the `scenario-generator` subagent with the following task:

> Read the knowledge base from `autonoma/AUTONOMA.md` and `autonoma/skills/`.
> Generate test data scenarios. Write the output to `autonoma/scenarios.md`.
> The file MUST have YAML frontmatter with scenario_count, scenarios summary, and entity_types.
> Fetch the latest instructions from https://docs.agent.autonoma.app/llms/test-planner/step-2-scenarios.txt first.

**After the subagent completes:**
1. Verify `autonoma/scenarios.md` exists and is non-empty
2. The PostToolUse hook will have validated the frontmatter format automatically
3. Read the file and present the frontmatter summary to the user — scenario names, entity counts, entity types
<<<<<<< tomaspiaggio/features-json
4. Call `AskUserQuestion` with:
   - question: "Do these scenarios look correct? The standard scenario data becomes hard assertions in your tests."
   - options: ["Yes, proceed to Step 3", "I want to suggest changes"]
5. Wait for the user's response before proceeding.
=======
4. End your message with exactly this question: **"Do these scenarios look correct? The standard scenario data becomes hard assertions in your tests. Please confirm or suggest changes before I proceed to Step 3."**
5. **STOP. End your turn. Do NOT call any tools or spawn any agents. Wait for the user to reply.**
>>>>>>> main

## Step 3: Generate E2E Test Cases

Spawn the `test-case-generator` subagent with the following task:

> Read the knowledge base from `autonoma/AUTONOMA.md`, skills from `autonoma/skills/`,
> and scenarios from `autonoma/scenarios.md`.
> Generate complete E2E test cases as markdown files in `autonoma/qa-tests/`.
> You MUST create `autonoma/qa-tests/INDEX.md` with frontmatter containing total_tests,
> total_folders, folder breakdown, and coverage_correlation.
> Each test file MUST have frontmatter with title, description, criticality, scenario, and flow.
> Fetch the latest instructions from https://docs.agent.autonoma.app/llms/test-planner/step-3-e2e-tests.txt first.

**After the subagent completes:**
1. Verify `autonoma/qa-tests/INDEX.md` exists and is non-empty
2. The PostToolUse hook will have validated the INDEX frontmatter and individual test file frontmatter
3. Read the INDEX.md and present the summary to the user — total tests, folder breakdown, coverage correlation
<<<<<<< tomaspiaggio/features-json
4. Call `AskUserQuestion` with:
   - question: "Does this test distribution look correct? The total test count should roughly correlate with the number of routes/features in your app."
   - options: ["Yes, proceed to Step 4", "I want to suggest changes"]
5. Wait for the user's response before proceeding.
=======
4. End your message with exactly this question: **"Does this test distribution look correct? The total test count should roughly correlate with the number of routes/features in your app. Please confirm or suggest changes before I proceed to Step 4."**
5. **STOP. End your turn. Do NOT call any tools or spawn any agents. Wait for the user to reply.**
>>>>>>> main

## Step 4: Implement Environment Factory

Spawn the `env-factory-generator` subagent with the following task:

> Read the scenarios from `autonoma/scenarios.md` and implement the Autonoma Environment Factory
> endpoint in the project's backend. The endpoint handles discover/up/down actions.
> Fetch the latest instructions from https://docs.agent.autonoma.app/llms/test-planner/step-4-implement-scenarios.txt
> and https://docs.agent.autonoma.app/llms/guides/environment-factory.txt first.
> After implementing, run integration tests to verify the endpoint works.
> Use AUTONOMA_SIGNING_SECRET and AUTONOMA_JWT_SECRET as environment variable names.

**After the subagent completes:**
1. Verify the endpoint was created and tests pass
2. Present the results to the user — what was implemented, where, test results
3. Report any issues that need manual attention

## Completion

After all steps complete, summarize:
- **Step 1**: Knowledge base location and core flow count
- **Step 2**: Scenario count and entity types covered
- **Step 3**: Total test count, folder breakdown, coverage correlation
- **Step 4**: Endpoint location, test results, env var setup instructions
