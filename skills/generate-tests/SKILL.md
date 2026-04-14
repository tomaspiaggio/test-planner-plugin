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

## User Confirmation Between Steps

By default, after each step (1, 2, and 3), you MUST present the summary and then ask the user for
confirmation using the `AskUserQuestion` tool. This creates an interactive
UI prompt that makes it clear the user needs to respond before the pipeline continues.

After calling `AskUserQuestion`, wait for the user's response.
Only proceed to the next step after they confirm.

**Auto-advance mode:** If the environment variable `AUTONOMA_AUTO_ADVANCE` is set to `true`,
skip the `AskUserQuestion` calls and automatically proceed to the next step after presenting
the summary. The summaries are still displayed — only the confirmation prompt is skipped.

## Before Starting

Create the output directory and save the project root (subagents change working directory, so we need an absolute path reference):
```bash
AUTONOMA_ROOT="$(pwd)"
echo "$AUTONOMA_ROOT" > /tmp/autonoma-project-root
mkdir -p autonoma/skills autonoma/qa-tests
```

The plugin root path (where hooks, validators, and helper scripts live) is persisted to `/tmp/autonoma-plugin-root` automatically by the PostToolUse validation hook on the first Write. All bash snippets that need plugin-local files read it back:
```bash
PLUGIN_ROOT=$(cat /tmp/autonoma-plugin-root 2>/dev/null || echo '')
```

Read the environment variables. These are required for reporting progress back to Autonoma:
- `AUTONOMA_API_KEY` — your Autonoma API key
- `AUTONOMA_PROJECT_ID` — your Autonoma project ID
- `AUTONOMA_API_URL` — Autonoma API base URL
- `AUTONOMA_AUTO_ADVANCE` — (optional) set to `true` to skip user confirmation prompts between steps

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
[ -n "$GENERATION_ID" ] && curl -f -X POST "${AUTONOMA_API_URL}/v1/setup/setups/${GENERATION_ID}/events" \
  -H "Authorization: Bearer ${AUTONOMA_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"type":"step.completed","data":{"step":0,"name":"Knowledge Base"}}' || true

[ -n "$GENERATION_ID" ] && python3 -c "
import os, json
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

4. **If `AUTONOMA_AUTO_ADVANCE` is not `true`:** Call `AskUserQuestion` with:
   - question: "Does this core flows table look correct? These flows determine how the test budget is distributed."
   - options: ["Yes, proceed to Step 2", "I want to suggest changes"]
   Wait for the user's response before proceeding.
   **If `AUTONOMA_AUTO_ADVANCE=true`:** Skip the prompt and proceed directly to Step 2.

## Step 2: Generate Scenarios

Report step start:
```bash
AUTONOMA_ROOT=$(cat /tmp/autonoma-project-root 2>/dev/null || echo '.')
GENERATION_ID=$(cat "$AUTONOMA_ROOT/autonoma/.generation-id" 2>/dev/null || echo '')
echo "GENERATION_ID=${GENERATION_ID:-<empty>}"
[ -n "$GENERATION_ID" ] && curl -f -X POST "${AUTONOMA_API_URL}/v1/setup/setups/${GENERATION_ID}/events" \
  -H "Authorization: Bearer ${AUTONOMA_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"type":"step.started","data":{"step":1,"name":"Scenarios"}}' || true
```

Before spawning the Step 2 subagent, fetch the SDK discover artifact and save it to `autonoma/discover.json`.
This step requires these environment variables:
- `AUTONOMA_SDK_ENDPOINT` — full URL of the customer's SDK endpoint
- `AUTONOMA_SHARED_SECRET` — the HMAC shared secret used by the SDK endpoint

If either variable is missing, stop and tell the user that Step 2 now requires SDK discover access.
Do not suggest skipping ahead, reordering the pipeline, or continuing without a working Environment Factory endpoint.
State plainly that the endpoint and both environment variables are mandatory prerequisites for Step 2.

Fetch and validate the artifact:
```bash
mkdir -p autonoma
BODY='{"action":"discover"}'
SIG=$(echo -n "$BODY" | openssl dgst -sha256 -hmac "$AUTONOMA_SHARED_SECRET" | sed 's/.*= //')
RESPONSE=$(curl -sS -w "\nHTTP_STATUS:%{http_code}" -X POST "$AUTONOMA_SDK_ENDPOINT" \
  -H "Content-Type: application/json" \
  -H "x-signature: $SIG" \
  -d "$BODY")
HTTP_STATUS=$(echo "$RESPONSE" | grep -o "HTTP_STATUS:[0-9]*" | cut -d: -f2)
DISCOVER_BODY=$(echo "$RESPONSE" | sed '/HTTP_STATUS:/d')
if [ "$HTTP_STATUS" != "200" ]; then
  echo "SDK discover failed (HTTP $HTTP_STATUS): $DISCOVER_BODY"
  exit 1
fi
printf '%s\n' "$DISCOVER_BODY" > autonoma/discover.json
python3 "$(cat /tmp/autonoma-plugin-root)/hooks/validators/validate_discover.py" autonoma/discover.json
```

If the fetch fails or validation fails, stop the pipeline at Step 2.
Do not suggest skipping ahead. Tell the user to provide a working SDK endpoint and correct shared secret, then rerun the command.

Spawn the `scenario-generator` subagent with the following task:

> Read the knowledge base from `autonoma/AUTONOMA.md`, `autonoma/skills/`, and the SDK discover
> artifact from `autonoma/discover.json`.
> Generate test data scenarios. Write the output to `autonoma/scenarios.md`.
> The file MUST have YAML frontmatter with scenario_count, scenarios summary, entity_types,
> discover metadata, and variable_fields. Prefer fixed, reviewable seed values by default. If a
> field needs uniqueness, prefer a planner-chosen hardcoded literal plus a discriminator before
> introducing a variable placeholder. Use variable fields only for truly dynamic values such as
> backend-generated or time-based fields. `generator` is optional and must not default to `faker`.
> Fetch the latest instructions from https://docs.agent.autonoma.app/llms/test-planner/step-2-scenarios.txt first.

**After the subagent completes:**
1. Verify `autonoma/discover.json` and `autonoma/scenarios.md` exist and are non-empty
2. Validate `autonoma/discover.json` using the plugin's validator (path saved in `/tmp/autonoma-plugin-root`)
3. The PostToolUse hook will have validated the frontmatter format automatically
4. Read the file and present the frontmatter summary to the user — scenario names, entity counts,
   entity types, discover schema counts, and the minimal variable field tokens that remain dynamic

Report step complete:
```bash
AUTONOMA_ROOT=$(cat /tmp/autonoma-project-root 2>/dev/null || echo '.')
GENERATION_ID=$(cat "$AUTONOMA_ROOT/autonoma/.generation-id" 2>/dev/null || echo '')
echo "GENERATION_ID=${GENERATION_ID:-<empty>}"
[ -n "$GENERATION_ID" ] && curl -f -X POST "${AUTONOMA_API_URL}/v1/setup/setups/${GENERATION_ID}/events" \
  -H "Authorization: Bearer ${AUTONOMA_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"type":"step.completed","data":{"step":1,"name":"Scenarios"}}' || true
```

4. **If `AUTONOMA_AUTO_ADVANCE` is not `true`:** Call `AskUserQuestion` with:
   - question: "Do these scenarios look correct? Most seed values should stay concrete, ideally as planner-chosen literals with discriminators, and only truly dynamic values should remain variable for later tests."
   - options: ["Yes, proceed to Step 3", "I want to suggest changes"]
   Wait for the user's response before proceeding.
   **If `AUTONOMA_AUTO_ADVANCE=true`:** Skip the prompt and proceed directly to Step 3.

## Step 3: Generate E2E Test Cases

Report step start:
```bash
AUTONOMA_ROOT=$(cat /tmp/autonoma-project-root 2>/dev/null || echo '.')
GENERATION_ID=$(cat "$AUTONOMA_ROOT/autonoma/.generation-id" 2>/dev/null || echo '')
echo "GENERATION_ID=${GENERATION_ID:-<empty>}"
[ -n "$GENERATION_ID" ] && curl -f -X POST "${AUTONOMA_API_URL}/v1/setup/setups/${GENERATION_ID}/events" \
  -H "Authorization: Bearer ${AUTONOMA_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"type":"step.started","data":{"step":2,"name":"E2E Tests"}}' || true
```

Spawn the `test-case-generator` subagent with the following task:

> Read the knowledge base from `autonoma/AUTONOMA.md`, skills from `autonoma/skills/`,
> and scenarios from `autonoma/scenarios.md`.
> Generate complete E2E test cases as markdown files in `autonoma/qa-tests/`.
> You MUST create `autonoma/qa-tests/INDEX.md` with frontmatter containing total_tests,
> total_folders, folder breakdown, and coverage_correlation.
> Each test file MUST have frontmatter with title, description, criticality, scenario, and flow.
> Treat `scenarios.md` as fixture input only. Do not generate tests whose purpose is to verify
> scenario counts, seeded inventories, or Environment Factory correctness. Only reference
> scenario data when it is needed to test a real user-facing app behavior.
> Fetch the latest instructions from https://docs.agent.autonoma.app/llms/test-planner/step-3-e2e-tests.txt first.

**After the subagent completes:**
1. Verify `autonoma/qa-tests/INDEX.md` exists and is non-empty
2. The PostToolUse hook will have validated the INDEX frontmatter and individual test file frontmatter
3. Read the INDEX.md and present the summary to the user — total tests, folder breakdown, coverage correlation

Report step complete and upload test cases:
```bash
AUTONOMA_ROOT=$(cat /tmp/autonoma-project-root 2>/dev/null || echo '.')
GENERATION_ID=$(cat "$AUTONOMA_ROOT/autonoma/.generation-id" 2>/dev/null || echo '')
echo "GENERATION_ID=${GENERATION_ID:-<empty>}"
[ -n "$GENERATION_ID" ] && curl -f -X POST "${AUTONOMA_API_URL}/v1/setup/setups/${GENERATION_ID}/events" \
  -H "Authorization: Bearer ${AUTONOMA_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"type":"step.completed","data":{"step":2,"name":"E2E Tests"}}' || true

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

4. **If `AUTONOMA_AUTO_ADVANCE` is not `true`:** Call `AskUserQuestion` with:
   - question: "Does this test distribution look correct? The total test count should roughly correlate with the number of routes/features in your app."
   - options: ["Yes, proceed to Step 4", "I want to suggest changes"]
   Wait for the user's response before proceeding.
   **If `AUTONOMA_AUTO_ADVANCE=true`:** Skip the prompt and proceed directly to Step 4.

## Step 4: Environment Factory

Report step start:
```bash
AUTONOMA_ROOT=$(cat /tmp/autonoma-project-root 2>/dev/null || echo '.')
GENERATION_ID=$(cat "$AUTONOMA_ROOT/autonoma/.generation-id" 2>/dev/null || echo '')
echo "GENERATION_ID=${GENERATION_ID:-<empty>}"
[ -n "$GENERATION_ID" ] && curl -f -X POST "${AUTONOMA_API_URL}/v1/setup/setups/${GENERATION_ID}/events" \
  -H "Authorization: Bearer ${AUTONOMA_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"type":"step.started","data":{"step":3,"name":"Environment Factory"}}' || true
```

This step requires these environment variables:
- `AUTONOMA_SDK_ENDPOINT` — full URL of the customer's SDK endpoint
- `AUTONOMA_SHARED_SECRET` — the HMAC shared secret used by the SDK endpoint

If either variable is missing, stop and tell the user that Step 4 requires SDK endpoint access for
preflight validation. State plainly that both environment variables are mandatory.

Spawn the `env-factory-generator` subagent with the following task:

> Read `autonoma/discover.json` and `autonoma/scenarios.md`.
> Implement or complete the Autonoma Environment Factory in the project's backend so it can
> support the planned scenarios with the current SDK contract, then validate the planned scenarios
> against that implementation.
> Fetch the latest instructions from https://docs.agent.autonoma.app/llms/test-planner/step-4-implement-scenarios.txt
> and https://docs.agent.autonoma.app/llms/guides/environment-factory.txt first.
> Preserve the existing discover integration if it already works, and finish `up` / `down`
> behavior using `AUTONOMA_SHARED_SECRET` and `AUTONOMA_SIGNING_SECRET`.
> Smoke-test the discover -> up -> down lifecycle in-session after implementing.
> Then validate `standard`, `empty`, and `large`, and write approved recipes to `autonoma/scenario-recipes.json`.
> The recipe file must match the current setup API schema:
> top-level `version: 1`, `source`, `validationMode`, `recipes`; each recipe must use
> `name`, `description`, `create`, and `validation` with `status: "validated"`,
> a valid `method`, `phase: "ok"`, and optional `up_ms` / `down_ms`.
> Do not use the old shape with top-level `scenarios`, `generatedAt`, or per-recipe `validated` / `timing`.
> When `create` uses `{{token}}` placeholders, include a `variables` field per recipe that defines
> how each token is resolved. Allowed strategies: `literal`, `derived`, `faker`.
> Persisted `create` must remain tokenized — never store resolved concrete values.
> After writing the recipe file, run the preflight helper to validate all recipes against the
> live SDK endpoint before uploading:
> `python3 "$(cat /tmp/autonoma-plugin-root)/hooks/preflight_scenario_recipes.py" autonoma/scenario-recipes.json`
> The preflight must pass for all three scenarios before Step 4 is considered complete.

**After the subagent completes:**
1. Verify the backend implementation or integration changes were made
2. Verify `autonoma/scenario-recipes.json` exists and is non-empty
3. Run the preflight helper if the subagent did not already do so:
```bash
AUTONOMA_ROOT=$(cat /tmp/autonoma-project-root 2>/dev/null || echo '.')
python3 "$(cat /tmp/autonoma-plugin-root)/hooks/preflight_scenario_recipes.py" "$AUTONOMA_ROOT/autonoma/scenario-recipes.json"
```
If preflight fails, do NOT proceed to upload. Report the failure to the user and stop.
4. Present the results to the user — endpoint location, what was implemented or fixed, smoke-test results, per-scenario preflight results
5. Report which environment variables the backend now requires
6. Report any backend issues that still need manual attention

Report step complete:
```bash
AUTONOMA_ROOT=$(cat /tmp/autonoma-project-root 2>/dev/null || echo '.')
GENERATION_ID=$(cat "$AUTONOMA_ROOT/autonoma/.generation-id" 2>/dev/null || echo '')
echo "GENERATION_ID=${GENERATION_ID:-<empty>}"
[ -n "$GENERATION_ID" ] && curl -f -X POST "${AUTONOMA_API_URL}/v1/setup/setups/${GENERATION_ID}/events" \
  -H "Authorization: Bearer ${AUTONOMA_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"type":"log","data":{"message":"Uploading validated scenario recipes to setup..."}}' || true
if [ -n "$GENERATION_ID" ]; then
  AUTONOMA_ROOT=$(cat /tmp/autonoma-project-root 2>/dev/null || echo '.')
  RECIPE_PATH="$AUTONOMA_ROOT/autonoma/scenario-recipes.json"
  if ! python3 -c "import json; json.load(open('$RECIPE_PATH'))" 2>/dev/null; then
    echo "ERROR: scenario-recipes.json is not valid JSON. Step 4 cannot complete."
    exit 1
  fi
  UPLOAD_RESPONSE=$(curl -s -w "\nHTTP_STATUS:%{http_code}" -X POST "${AUTONOMA_API_URL}/v1/setup/setups/${GENERATION_ID}/scenario-recipe-versions" \
    -H "Authorization: Bearer ${AUTONOMA_API_KEY}" \
    -H "Content-Type: application/json" \
    -d @"$RECIPE_PATH")
  UPLOAD_STATUS=$(echo "$UPLOAD_RESPONSE" | grep -o "HTTP_STATUS:[0-9]*" | cut -d: -f2)
  UPLOAD_BODY=$(echo "$UPLOAD_RESPONSE" | sed '/HTTP_STATUS:/d')
  echo "Scenario recipe upload response (HTTP $UPLOAD_STATUS): $UPLOAD_BODY"
  if [ "$UPLOAD_STATUS" != "200" ] && [ "$UPLOAD_STATUS" != "201" ]; then
    echo "ERROR: Recipe upload failed (HTTP $UPLOAD_STATUS). Step 4 cannot complete."
    exit 1
  fi

  # Verify recipes were persisted by fetching them back from the dashboard
  VERIFY_RESPONSE=$(curl -s -w "\nHTTP_STATUS:%{http_code}" -X GET "${AUTONOMA_API_URL}/v1/setup/setups/${GENERATION_ID}/scenarios" \
    -H "Authorization: Bearer ${AUTONOMA_API_KEY}")
  VERIFY_STATUS=$(echo "$VERIFY_RESPONSE" | grep -o "HTTP_STATUS:[0-9]*" | cut -d: -f2)
  VERIFY_BODY=$(echo "$VERIFY_RESPONSE" | sed '/HTTP_STATUS:/d')
  if [ "$VERIFY_STATUS" != "200" ]; then
    echo "ERROR: Failed to verify scenarios (HTTP $VERIFY_STATUS). Step 4 cannot complete."
    exit 1
  fi
  # Extract scenario names from the uploaded recipes file and verify each one exists with an active recipe
  EXPECTED_NAMES=$(python3 -c "import json; data=json.load(open('$RECIPE_PATH')); print('\n'.join(r['name'] for r in data['recipes']))")
  MISSING=""
  for NAME in $EXPECTED_NAMES; do
    HAS_ACTIVE=$(echo "$VERIFY_BODY" | python3 -c "
import json, sys
data = json.loads(sys.stdin.read())
match = [s for s in data.get('scenarios', []) if s['name'] == '$NAME' and s.get('hasActiveRecipe')]
print('yes' if match else 'no')
" 2>/dev/null || echo "no")
    if [ "$HAS_ACTIVE" != "yes" ]; then
      MISSING="$MISSING $NAME"
    fi
  done
  if [ -n "$MISSING" ]; then
    echo "ERROR: The following scenarios are missing or lack an active recipe on the dashboard:$MISSING"
    echo "Step 4 cannot complete. Recipe upload may have partially failed."
    exit 1
  fi
  echo "Verified: all scenario recipes persisted successfully on the dashboard."
fi
[ -n "$GENERATION_ID" ] && curl -f -X POST "${AUTONOMA_API_URL}/v1/setup/setups/${GENERATION_ID}/events" \
  -H "Authorization: Bearer ${AUTONOMA_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"type":"step.completed","data":{"step":3,"name":"Environment Factory"}}' || true
```

## Completion

After all steps complete, summarize:
- **Step 1**: Knowledge base location and core flow count
- **Step 2**: Scenario count and entity types covered
- **Step 3**: Total test count, folder breakdown, coverage correlation
- **Step 4**: Environment Factory location, backend changes, smoke-test results, required secrets, and per-scenario lifecycle results
