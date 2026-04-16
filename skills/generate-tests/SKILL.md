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

## Before Starting

Create the output directory:
```bash
mkdir -p autonoma/skills autonoma/qa-tests
```

Read the environment variables. These are required for reporting progress back to Autonoma:
- `AUTONOMA_API_KEY` — your Autonoma API key
- `AUTONOMA_PROJECT_ID` — your Autonoma project ID
- `AUTONOMA_API_URL` — Autonoma API base URL

Create the generation record so the dashboard can track progress in real time:
```bash
RESPONSE=$(curl -sf -X POST "${AUTONOMA_API_URL}/v1/generation/generations" \
  -H "Authorization: Bearer ${AUTONOMA_API_KEY}" \
  -H "Content-Type: application/json" \
  -d "{\"applicationId\":\"${AUTONOMA_PROJECT_ID}\"}" 2>/dev/null || echo '{}')
GENERATION_ID=$(echo "$RESPONSE" | python3 -c "import json,sys; print(json.load(sys.stdin).get('id',''))" 2>/dev/null || echo '')
mkdir -p autonoma
echo "$GENERATION_ID" > autonoma/.generation-id
echo "Generation ID: $GENERATION_ID"
```

If `GENERATION_ID` is empty, continue anyway — reporting is best-effort and must never block test generation.

## Step 1: Generate Knowledge Base

Report step start:
```bash
GENERATION_ID=$(cat autonoma/.generation-id 2>/dev/null || echo '')
[ -n "$GENERATION_ID" ] && curl -sf -X POST "${AUTONOMA_API_URL}/v1/generation/generations/${GENERATION_ID}/events" \
  -H "Authorization: Bearer ${AUTONOMA_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"type":"step.started","data":{"step":0,"name":"Knowledge Base"}}' 2>/dev/null || true
```

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

Report step complete and upload skills:
```bash
GENERATION_ID=$(cat autonoma/.generation-id 2>/dev/null || echo '')
[ -n "$GENERATION_ID" ] && curl -sf -X POST "${AUTONOMA_API_URL}/v1/generation/generations/${GENERATION_ID}/events" \
  -H "Authorization: Bearer ${AUTONOMA_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"type":"step.completed","data":{"step":0,"name":"Knowledge Base"}}' 2>/dev/null || true

[ -n "$GENERATION_ID" ] && python3 -c "
import os, json
skills = []
d = 'autonoma/skills'
if os.path.isdir(d):
    for f in os.listdir(d):
        if f.endswith('.md'):
            with open(os.path.join(d, f)) as fh:
                skills.append({'name': f, 'content': fh.read()})
print(json.dumps({'skills': skills}))
" | curl -sf -X POST "${AUTONOMA_API_URL}/v1/generation/generations/${GENERATION_ID}/artifacts" \
  -H "Authorization: Bearer ${AUTONOMA_API_KEY}" \
  -H "Content-Type: application/json" \
  -d @- 2>/dev/null || true
```

4. Call `AskUserQuestion` with:
   - question: "Does this core flows table look correct? These flows determine how the test budget is distributed."
   - options: ["Yes, proceed to Step 2", "I want to suggest changes"]
5. Wait for the user's response before proceeding.

## Step 2: Entity Creation Audit

Report step start:
```bash
GENERATION_ID=$(cat autonoma/.generation-id 2>/dev/null || echo '')
[ -n "$GENERATION_ID" ] && curl -sf -X POST "${AUTONOMA_API_URL}/v1/generation/generations/${GENERATION_ID}/events" \
  -H "Authorization: Bearer ${AUTONOMA_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"type":"step.started","data":{"step":1,"name":"Entity Audit"}}' 2>/dev/null || true
```

Spawn the `entity-audit-generator` subagent with the following task:

> Read the knowledge base from `autonoma/AUTONOMA.md` and `autonoma/skills/`.
> Audit how each database model is created in the codebase. For every model, find the service,
> repository, or function that creates it. Read the actual creation code and identify side effects
> (password hashing, S3 uploads, external API calls, slug generation, derived fields, etc.).
> Output to `autonoma/entity-audit.md` with YAML frontmatter listing each model, whether it
> needs a factory, the creation file/function, and what side effects exist.
> Fetch the latest instructions from http://localhost:4321/llms/test-planner/step-2-entity-audit.txt first.

**After the subagent completes:**
1. Verify `autonoma/entity-audit.md` exists and is non-empty
2. The PostToolUse hook will have validated the frontmatter schema automatically (model_count, factory_count, models array with name/needs_factory/reason/creation_file/side_effects)
3. Read the file and present the frontmatter to the user — specifically which models need factories and why

Report step complete:
```bash
GENERATION_ID=$(cat autonoma/.generation-id 2>/dev/null || echo '')
[ -n "$GENERATION_ID" ] && curl -sf -X POST "${AUTONOMA_API_URL}/v1/generation/generations/${GENERATION_ID}/events" \
  -H "Authorization: Bearer ${AUTONOMA_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"type":"step.completed","data":{"step":1,"name":"Entity Audit"}}' 2>/dev/null || true
```

4. Call `AskUserQuestion` with:
   - question: "Does this entity audit look correct? Models marked as needing factories will use your repositories/services instead of raw SQL."
   - options: ["Yes, proceed to Step 3", "I want to suggest changes"]
5. Wait for the user's response before proceeding.

## Step 3: Generate Scenarios

Report step start:
```bash
GENERATION_ID=$(cat autonoma/.generation-id 2>/dev/null || echo '')
[ -n "$GENERATION_ID" ] && curl -sf -X POST "${AUTONOMA_API_URL}/v1/generation/generations/${GENERATION_ID}/events" \
  -H "Authorization: Bearer ${AUTONOMA_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"type":"step.started","data":{"step":2,"name":"Scenarios"}}' 2>/dev/null || true
```

Spawn the `scenario-generator` subagent with the following task:

> Read the knowledge base from `autonoma/AUTONOMA.md` and `autonoma/skills/`.
> Generate test data scenarios. Write the output to `autonoma/scenarios.md`.
> The file MUST have YAML frontmatter with scenario_count, scenarios summary, and entity_types.
> Fetch the latest instructions from https://docs.agent.autonoma.app/llms/test-planner/step-2-scenarios.txt first.

**After the subagent completes:**
1. Verify `autonoma/scenarios.md` exists and is non-empty
2. The PostToolUse hook will have validated the frontmatter format automatically
3. Read the file and present the frontmatter summary to the user — scenario names, entity counts, entity types

Report step complete:
```bash
GENERATION_ID=$(cat autonoma/.generation-id 2>/dev/null || echo '')
[ -n "$GENERATION_ID" ] && curl -sf -X POST "${AUTONOMA_API_URL}/v1/generation/generations/${GENERATION_ID}/events" \
  -H "Authorization: Bearer ${AUTONOMA_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"type":"step.completed","data":{"step":2,"name":"Scenarios"}}' 2>/dev/null || true
```

4. Call `AskUserQuestion` with:
   - question: "Do these scenarios look correct? The standard scenario data becomes hard assertions in your tests."
   - options: ["Yes, proceed to Step 4 (implement scenarios)", "I want to suggest changes"]
5. Wait for the user's response before proceeding.

## Step 4: Implement & Validate Environment Factory

Report step start:
```bash
GENERATION_ID=$(cat autonoma/.generation-id 2>/dev/null || echo '')
[ -n "$GENERATION_ID" ] && curl -sf -X POST "${AUTONOMA_API_URL}/v1/generation/generations/${GENERATION_ID}/events" \
  -H "Authorization: Bearer ${AUTONOMA_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"type":"step.started","data":{"step":3,"name":"Environment Factory"}}' 2>/dev/null || true
```

Log: "Installing Autonoma SDK and validating scenario lifecycle..."

Spawn the `env-factory-generator` subagent with the following task:

> Read the scenarios from `autonoma/scenarios.md` and set up the Autonoma Environment Factory
> endpoint in the project's backend using the SDK. Install SDK packages, configure the handler
> with factories for models with business logic, and validate the full up/down lifecycle.
> Read the entity audit from `autonoma/entity-audit.md` to know which models need factories
> and what service/repository code to use for each.
> Fetch the latest instructions from https://docs.agent.autonoma.app/llms/test-planner/step-4-implement-scenarios.txt
> and https://docs.agent.autonoma.app/llms/guides/environment-factory.txt first.
> Use AUTONOMA_SHARED_SECRET and AUTONOMA_SIGNING_SECRET as environment variable names.

**After the subagent completes:**
1. Verify the endpoint was created and the lifecycle was validated
2. Present the results to the user — what was implemented, where, validation results
3. Report any issues that need manual attention

Report step complete:
```bash
GENERATION_ID=$(cat autonoma/.generation-id 2>/dev/null || echo '')
[ -n "$GENERATION_ID" ] && curl -sf -X POST "${AUTONOMA_API_URL}/v1/generation/generations/${GENERATION_ID}/events" \
  -H "Authorization: Bearer ${AUTONOMA_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"type":"step.completed","data":{"step":3,"name":"Environment Factory"}}' 2>/dev/null || true
```

4. Call `AskUserQuestion` with:
   - question: "The Environment Factory is set up and the scenario lifecycle has been validated. Does everything look correct?"
   - options: ["Yes, proceed to Step 5 (generate tests)", "I want to suggest changes"]
5. Wait for the user's response before proceeding.

## Step 5: Generate E2E Test Cases

Report step start:
```bash
GENERATION_ID=$(cat autonoma/.generation-id 2>/dev/null || echo '')
[ -n "$GENERATION_ID" ] && curl -sf -X POST "${AUTONOMA_API_URL}/v1/generation/generations/${GENERATION_ID}/events" \
  -H "Authorization: Bearer ${AUTONOMA_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"type":"step.started","data":{"step":4,"name":"E2E Tests"}}' 2>/dev/null || true
```

Log: "Generating E2E test cases from knowledge base and validated scenarios..."

Spawn the `test-case-generator` subagent with the following task:

> Read the knowledge base from `autonoma/AUTONOMA.md`, skills from `autonoma/skills/`,
> and scenarios from `autonoma/scenarios.md`.
> Generate complete E2E test cases as markdown files in `autonoma/qa-tests/`.
> You MUST create `autonoma/qa-tests/INDEX.md` with frontmatter containing total_tests,
> total_folders, folder breakdown, and coverage_correlation.
> Each test file MUST have frontmatter with title, description, criticality, scenario, and flow.
> Fetch the latest instructions from https://docs.agent.autonoma.app/llms/test-planner/step-3-e2e-tests.txt first.
> Note: The scenario data has been validated in Step 4 — the Environment Factory can create and tear down all entities.

**After the subagent completes:**
1. Verify `autonoma/qa-tests/INDEX.md` exists and is non-empty
2. The PostToolUse hook will have validated the INDEX frontmatter and individual test file frontmatter
3. Read the INDEX.md and present the summary to the user — total tests, folder breakdown, coverage correlation

Report step complete and upload test cases:
```bash
GENERATION_ID=$(cat autonoma/.generation-id 2>/dev/null || echo '')
[ -n "$GENERATION_ID" ] && curl -sf -X POST "${AUTONOMA_API_URL}/v1/generation/generations/${GENERATION_ID}/events" \
  -H "Authorization: Bearer ${AUTONOMA_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"type":"step.completed","data":{"step":4,"name":"E2E Tests"}}' 2>/dev/null || true

[ -n "$GENERATION_ID" ] && python3 -c "
import os, json
test_cases = []
for root, dirs, files in os.walk('autonoma/qa-tests'):
    for f in files:
        if f.endswith('.md') and f != 'INDEX.md':
            path = os.path.join(root, f)
            folder = os.path.relpath(root, 'autonoma/qa-tests')
            with open(path) as fh:
                content = fh.read()
            entry = {'name': f, 'content': content}
            if folder != '.':
                entry['folder'] = folder
            test_cases.append(entry)
print(json.dumps({'testCases': test_cases}))
" | curl -sf -X POST "${AUTONOMA_API_URL}/v1/generation/generations/${GENERATION_ID}/artifacts" \
  -H "Authorization: Bearer ${AUTONOMA_API_KEY}" \
  -H "Content-Type: application/json" \
  -d @- 2>/dev/null || true
```

## Completion

After all steps complete, summarize:
- **Step 1**: Knowledge base location and core flow count
- **Step 2**: Entity audit — models audited, how many need factories, key side effects found
- **Step 3**: Scenario count and entity types covered
- **Step 4**: Endpoint location, packages installed, factories registered, validation results
- **Step 5**: Total test count, folder breakdown, coverage correlation
