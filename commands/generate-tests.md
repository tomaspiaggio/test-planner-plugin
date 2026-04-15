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

Create the output directory and save the project root (subagents change working directory, so we need an absolute path reference):
```bash
AUTONOMA_ROOT="$(pwd)"
echo "$AUTONOMA_ROOT" > /tmp/autonoma-project-root
mkdir -p autonoma/skills autonoma/qa-tests
```

Read the environment variables. These are required for reporting progress back to Autonoma:
- `AUTONOMA_API_KEY` — your Autonoma API key
- `AUTONOMA_PROJECT_ID` — your Autonoma project ID
- `AUTONOMA_API_URL` — Autonoma API base URL

Before creating the record, derive a clean human-readable application name from the repository. Look at the git remote URL, the directory name, and any `package.json` / `pyproject.toml` / `README.md` to infer what the product is actually called. Prefer the product name over the repo slug (e.g. "My App" not "my-app-v2-final"). Store it in `APP_NAME`.

Create the generation record so the dashboard can track progress in real time:
```bash
RESPONSE=$(curl -s -w "\nHTTP_STATUS:%{http_code}" -X POST "${AUTONOMA_API_URL}/v1/setup/setups" \
  -H "Authorization: Bearer ${AUTONOMA_API_KEY}" \
  -H "Content-Type: application/json" \
  -d "{\"applicationId\":\"${AUTONOMA_PROJECT_ID}\",\"repoName\":\"${APP_NAME}\"}")
HTTP_STATUS=$(echo "$RESPONSE" | grep -o "HTTP_STATUS:[0-9]*" | cut -d: -f2)
BODY=$(echo "$RESPONSE" | sed '/HTTP_STATUS:/d')
echo "Setup API response (HTTP $HTTP_STATUS): $BODY"
GENERATION_ID=$(echo "$BODY" | python3 -c "import json,sys; print(json.load(sys.stdin).get('id',''))" 2>/dev/null || echo '')
mkdir -p autonoma
echo "$GENERATION_ID" > autonoma/.generation-id
echo "Generation ID: $GENERATION_ID"
```

If `GENERATION_ID` is empty, log the HTTP status and response body above for debugging, then continue anyway — reporting is best-effort and must never block test generation.

## Step 1: Generate Knowledge Base

Report step start:
```bash
AUTONOMA_ROOT=$(cat /tmp/autonoma-project-root 2>/dev/null || echo '.')
GENERATION_ID=$(cat "$AUTONOMA_ROOT/autonoma/.generation-id" 2>/dev/null || echo '')
echo "GENERATION_ID=${GENERATION_ID:-<empty>}"
[ -n "$GENERATION_ID" ] && curl -f -X POST "${AUTONOMA_API_URL}/v1/setup/setups/${GENERATION_ID}/events" \
  -H "Authorization: Bearer ${AUTONOMA_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"type":"step.started","data":{"step":0,"name":"Knowledge Base"}}' || true
[ -n "$GENERATION_ID" ] && curl -f -X POST "${AUTONOMA_API_URL}/v1/setup/setups/${GENERATION_ID}/events" \
  -H "Authorization: Bearer ${AUTONOMA_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"type":"log","data":{"message":"Analyzing codebase structure and identifying features..."}}' || true
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
AUTONOMA_ROOT=$(cat /tmp/autonoma-project-root 2>/dev/null || echo '.')
GENERATION_ID=$(cat "$AUTONOMA_ROOT/autonoma/.generation-id" 2>/dev/null || echo '')
echo "GENERATION_ID=${GENERATION_ID:-<empty>}"
SKILL_COUNT=$(ls "$AUTONOMA_ROOT/autonoma/skills/"*.md 2>/dev/null | wc -l | tr -d ' ')
[ -n "$GENERATION_ID" ] && curl -f -X POST "${AUTONOMA_API_URL}/v1/setup/setups/${GENERATION_ID}/events" \
  -H "Authorization: Bearer ${AUTONOMA_API_KEY}" \
  -H "Content-Type: application/json" \
  -d "{\"type\":\"log\",\"data\":{\"message\":\"Knowledge base complete. Generated ${SKILL_COUNT} skills. Uploading to dashboard...\"}}" || true

[ -n "$GENERATION_ID" ] && curl -f -X POST "${AUTONOMA_API_URL}/v1/setup/setups/${GENERATION_ID}/events" \
  -H "Authorization: Bearer ${AUTONOMA_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"type":"step.completed","data":{"step":0,"name":"Knowledge Base"}}' || true

[ -n "$GENERATION_ID" ] && python3 -c "
import os, json, sys
root = open('/tmp/autonoma-project-root').read().strip() if os.path.exists('/tmp/autonoma-project-root') else '.'
skills = []
d = os.path.join(root, 'autonoma/skills')
if os.path.isdir(d):
    for f in os.listdir(d):
        if f.endswith('.md'):
            with open(os.path.join(d, f)) as fh:
                skills.append({'name': f, 'content': fh.read()})
print(json.dumps({'skills': skills}))
" | curl -f -X POST "${AUTONOMA_API_URL}/v1/setup/setups/${GENERATION_ID}/artifacts" \
  -H "Authorization: Bearer ${AUTONOMA_API_KEY}" \
  -H "Content-Type: application/json" \
  -d @- || true
```

4. Call `AskUserQuestion` with:
   - question: "Does this core flows table look correct? These flows determine how the test budget is distributed."
   - options: ["Yes, proceed to Step 2", "I want to suggest changes"]
5. Wait for the user's response before proceeding.

## Step 2: Entity Creation Audit

Report step start:
```bash
AUTONOMA_ROOT=$(cat /tmp/autonoma-project-root 2>/dev/null || echo '.')
GENERATION_ID=$(cat "$AUTONOMA_ROOT/autonoma/.generation-id" 2>/dev/null || echo '')
echo "GENERATION_ID=${GENERATION_ID:-<empty>}"
[ -n "$GENERATION_ID" ] && curl -f -X POST "${AUTONOMA_API_URL}/v1/setup/setups/${GENERATION_ID}/events" \
  -H "Authorization: Bearer ${AUTONOMA_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"type":"step.started","data":{"step":1,"name":"Entity Audit"}}' || true
[ -n "$GENERATION_ID" ] && curl -f -X POST "${AUTONOMA_API_URL}/v1/setup/setups/${GENERATION_ID}/events" \
  -H "Authorization: Bearer ${AUTONOMA_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"type":"log","data":{"message":"Auditing model creation paths for side effects..."}}' || true
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
2. Read and present the frontmatter — specifically which models need factories and why
3. Report step complete

Report step complete:
```bash
AUTONOMA_ROOT=$(cat /tmp/autonoma-project-root 2>/dev/null || echo '.')
GENERATION_ID=$(cat "$AUTONOMA_ROOT/autonoma/.generation-id" 2>/dev/null || echo '')
echo "GENERATION_ID=${GENERATION_ID:-<empty>}"
[ -n "$GENERATION_ID" ] && curl -f -X POST "${AUTONOMA_API_URL}/v1/setup/setups/${GENERATION_ID}/events" \
  -H "Authorization: Bearer ${AUTONOMA_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"type":"log","data":{"message":"Entity audit complete. Models classified for factory vs raw SQL."}}' || true
[ -n "$GENERATION_ID" ] && curl -f -X POST "${AUTONOMA_API_URL}/v1/setup/setups/${GENERATION_ID}/events" \
  -H "Authorization: Bearer ${AUTONOMA_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"type":"step.completed","data":{"step":1,"name":"Entity Audit"}}' || true
```

4. Call `AskUserQuestion` with:
   - question: "Does this entity audit look correct? Models marked as needing factories will use your repositories/services instead of raw SQL."
   - options: ["Yes, proceed to Step 3", "I want to suggest changes"]
5. Wait for the user's response before proceeding.

## Step 3: Generate Scenarios

Report step start:
```bash
AUTONOMA_ROOT=$(cat /tmp/autonoma-project-root 2>/dev/null || echo '.')
GENERATION_ID=$(cat "$AUTONOMA_ROOT/autonoma/.generation-id" 2>/dev/null || echo '')
echo "GENERATION_ID=${GENERATION_ID:-<empty>}"
[ -n "$GENERATION_ID" ] && curl -f -X POST "${AUTONOMA_API_URL}/v1/setup/setups/${GENERATION_ID}/events" \
  -H "Authorization: Bearer ${AUTONOMA_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"type":"step.started","data":{"step":2,"name":"Scenarios"}}' || true
[ -n "$GENERATION_ID" ] && curl -f -X POST "${AUTONOMA_API_URL}/v1/setup/setups/${GENERATION_ID}/events" \
  -H "Authorization: Bearer ${AUTONOMA_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"type":"log","data":{"message":"Mapping data model and designing test data environments..."}}' || true
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
AUTONOMA_ROOT=$(cat /tmp/autonoma-project-root 2>/dev/null || echo '.')
GENERATION_ID=$(cat "$AUTONOMA_ROOT/autonoma/.generation-id" 2>/dev/null || echo '')
echo "GENERATION_ID=${GENERATION_ID:-<empty>}"
[ -n "$GENERATION_ID" ] && curl -f -X POST "${AUTONOMA_API_URL}/v1/setup/setups/${GENERATION_ID}/events" \
  -H "Authorization: Bearer ${AUTONOMA_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"type":"log","data":{"message":"Scenarios generated. 3 test data environments defined (standard, empty, large)."}}' || true
[ -n "$GENERATION_ID" ] && curl -f -X POST "${AUTONOMA_API_URL}/v1/setup/setups/${GENERATION_ID}/events" \
  -H "Authorization: Bearer ${AUTONOMA_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"type":"step.completed","data":{"step":2,"name":"Scenarios"}}' || true
```

4. Call `AskUserQuestion` with:
   - question: "Do these scenarios look correct? The standard scenario data becomes hard assertions in your tests."
   - options: ["Yes, proceed to Step 4 (implement scenarios)", "I want to suggest changes"]
5. Wait for the user's response before proceeding.

## Step 4: Implement & Validate Environment Factory

Report step start:
```bash
AUTONOMA_ROOT=$(cat /tmp/autonoma-project-root 2>/dev/null || echo '.')
GENERATION_ID=$(cat "$AUTONOMA_ROOT/autonoma/.generation-id" 2>/dev/null || echo '')
echo "GENERATION_ID=${GENERATION_ID:-<empty>}"
[ -n "$GENERATION_ID" ] && curl -f -X POST "${AUTONOMA_API_URL}/v1/setup/setups/${GENERATION_ID}/events" \
  -H "Authorization: Bearer ${AUTONOMA_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"type":"step.started","data":{"step":3,"name":"Environment Factory"}}' || true
[ -n "$GENERATION_ID" ] && curl -f -X POST "${AUTONOMA_API_URL}/v1/setup/setups/${GENERATION_ID}/events" \
  -H "Authorization: Bearer ${AUTONOMA_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"type":"log","data":{"message":"Installing Autonoma SDK and validating scenario lifecycle..."}}' || true
```

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
1. Verify the endpoint was created and the lifecycle validation passed
2. Present the results to the user — packages installed, factories registered, validation results
3. Report any issues that need manual attention

Report step complete:
```bash
AUTONOMA_ROOT=$(cat /tmp/autonoma-project-root 2>/dev/null || echo '.')
GENERATION_ID=$(cat "$AUTONOMA_ROOT/autonoma/.generation-id" 2>/dev/null || echo '')
echo "GENERATION_ID=${GENERATION_ID:-<empty>}"
[ -n "$GENERATION_ID" ] && curl -f -X POST "${AUTONOMA_API_URL}/v1/setup/setups/${GENERATION_ID}/events" \
  -H "Authorization: Bearer ${AUTONOMA_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"type":"log","data":{"message":"Environment Factory installed and lifecycle validated."}}' || true
[ -n "$GENERATION_ID" ] && curl -f -X POST "${AUTONOMA_API_URL}/v1/setup/setups/${GENERATION_ID}/events" \
  -H "Authorization: Bearer ${AUTONOMA_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"type":"step.completed","data":{"step":3,"name":"Environment Factory"}}' || true
```

4. Call `AskUserQuestion` with:
   - question: "The Environment Factory is set up and the scenario lifecycle has been validated. Does everything look correct?"
   - options: ["Yes, proceed to Step 5 (generate tests)", "I want to suggest changes"]
5. Wait for the user's response before proceeding.

## Step 5: Generate E2E Test Cases

Report step start:
```bash
AUTONOMA_ROOT=$(cat /tmp/autonoma-project-root 2>/dev/null || echo '.')
GENERATION_ID=$(cat "$AUTONOMA_ROOT/autonoma/.generation-id" 2>/dev/null || echo '')
echo "GENERATION_ID=${GENERATION_ID:-<empty>}"
[ -n "$GENERATION_ID" ] && curl -f -X POST "${AUTONOMA_API_URL}/v1/setup/setups/${GENERATION_ID}/events" \
  -H "Authorization: Bearer ${AUTONOMA_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"type":"step.started","data":{"step":4,"name":"E2E Tests"}}' || true
[ -n "$GENERATION_ID" ] && curl -f -X POST "${AUTONOMA_API_URL}/v1/setup/setups/${GENERATION_ID}/events" \
  -H "Authorization: Bearer ${AUTONOMA_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"type":"log","data":{"message":"Generating E2E test cases from knowledge base and validated scenarios..."}}' || true
```

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
AUTONOMA_ROOT=$(cat /tmp/autonoma-project-root 2>/dev/null || echo '.')
GENERATION_ID=$(cat "$AUTONOMA_ROOT/autonoma/.generation-id" 2>/dev/null || echo '')
echo "GENERATION_ID=${GENERATION_ID:-<empty>}"
TEST_COUNT=$(find "$AUTONOMA_ROOT/autonoma/qa-tests" -name '*.md' ! -name 'INDEX.md' 2>/dev/null | wc -l | tr -d ' ')
[ -n "$GENERATION_ID" ] && curl -f -X POST "${AUTONOMA_API_URL}/v1/setup/setups/${GENERATION_ID}/events" \
  -H "Authorization: Bearer ${AUTONOMA_API_KEY}" \
  -H "Content-Type: application/json" \
  -d "{\"type\":\"log\",\"data\":{\"message\":\"Generated ${TEST_COUNT} test cases. Uploading to dashboard...\"}}" || true

[ -n "$GENERATION_ID" ] && curl -f -X POST "${AUTONOMA_API_URL}/v1/setup/setups/${GENERATION_ID}/events" \
  -H "Authorization: Bearer ${AUTONOMA_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"type":"step.completed","data":{"step":4,"name":"E2E Tests"}}' || true

[ -n "$GENERATION_ID" ] && python3 -c "
import os, json
proj_root = open('/tmp/autonoma-project-root').read().strip() if os.path.exists('/tmp/autonoma-project-root') else '.'
qa_dir = os.path.join(proj_root, 'autonoma/qa-tests')
test_cases = []
for root, dirs, files in os.walk(qa_dir):
    for f in files:
        if f.endswith('.md') and f != 'INDEX.md':
            path = os.path.join(root, f)
            folder = os.path.relpath(root, qa_dir)
            with open(path) as fh:
                content = fh.read()
            entry = {'name': f, 'content': content}
            if folder != '.':
                entry['folder'] = folder
            test_cases.append(entry)
print(json.dumps({'testCases': test_cases}))
" | curl -f -X POST "${AUTONOMA_API_URL}/v1/setup/setups/${GENERATION_ID}/artifacts" \
  -H "Authorization: Bearer ${AUTONOMA_API_KEY}" \
  -H "Content-Type: application/json" \
  -d @- || true
```

## Completion

After all steps complete, summarize:
- **Step 1**: Knowledge base location and core flow count
- **Step 2**: Entity audit — models audited, how many need factories, key side effects found
- **Step 3**: Scenario count and entity types covered
- **Step 4**: Endpoint location, packages installed, factories registered, validation results
- **Step 5**: Total test count, folder breakdown, coverage correlation
