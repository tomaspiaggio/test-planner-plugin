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

## User Confirmation Between Steps

By default, after each step (1, 2, 3, and 4), present the summary and automatically proceed to the
next step once validation passes.

**Canonical auto-advance mode:** If `AUTONOMA_AUTO_ADVANCE=true`, keep moving automatically after
Steps 1-4.

**Compatibility alias:** If `AUTONOMA_AUTO_ADVANCE` is unset and `AUTONOMA_REQUIRE_CONFIRMATION=false`,
that means auto-advance as well.

If auto-advance is disabled, you MUST present the summary and then ask the user for confirmation
using the `AskUserQuestion` tool.

After calling `AskUserQuestion`, wait for the user's response.
Only proceed to the next step after they confirm.

## Before Starting

Create the output directory and save the project root:

```bash
AUTONOMA_ROOT="$(pwd)"
echo "$AUTONOMA_ROOT" > /tmp/autonoma-project-root
mkdir -p autonoma autonoma/skills autonoma/qa-tests
cleanup_dev_server() {
  DEV_SERVER_PID=$(cat /tmp/autonoma-dev-server-pid 2>/dev/null || echo '')
  if [ -n "$DEV_SERVER_PID" ]; then
    kill "$DEV_SERVER_PID" 2>/dev/null || true
    rm -f /tmp/autonoma-dev-server-pid
    echo "Dev server (PID $DEV_SERVER_PID) stopped."
  fi
}
```

The plugin root path is persisted to `/tmp/autonoma-plugin-root` automatically by the PostToolUse hook on the first Write:

```bash
PLUGIN_ROOT=$(cat /tmp/autonoma-plugin-root 2>/dev/null || echo '')
```

Read the environment variables required for reporting progress back to Autonoma:
- `AUTONOMA_API_KEY`
- `AUTONOMA_PROJECT_ID`
- `AUTONOMA_API_URL`
- `AUTONOMA_AUTO_ADVANCE` — optional, canonical
- `AUTONOMA_REQUIRE_CONFIRMATION` — optional legacy alias

Add shared helpers before running the pipeline:

```bash
auto_advance_enabled() {
  if [ "${AUTONOMA_AUTO_ADVANCE:-}" = "true" ]; then
    return 0
  fi
  if [ -z "${AUTONOMA_AUTO_ADVANCE:-}" ] && [ "${AUTONOMA_REQUIRE_CONFIRMATION:-}" = "false" ]; then
    return 0
  fi
  return 1
}

refresh_generation_id() {
  AUTONOMA_ROOT=$(cat /tmp/autonoma-project-root 2>/dev/null || echo '.')
  GENERATION_ID=$(cat "$AUTONOMA_ROOT/autonoma/.generation-id" 2>/dev/null || echo '')
}

build_event_payload() {
  python3 - "$1" "$2" "$3" <<'PY'
import json
import sys

event_type, key, value = sys.argv[1:4]
print(json.dumps({"type": event_type, "data": {key: json.loads(value)}}))
PY
}

build_step_payload() {
  python3 - "$1" "$2" "$3" <<'PY'
import json
import sys

event_type, step, name = sys.argv[1:4]
print(json.dumps({"type": event_type, "data": {"step": int(step), "name": name}}))
PY
}

post_setup_event_blocking() {
  refresh_generation_id
  payload="$1"
  if [ -z "$GENERATION_ID" ]; then
    return 0
  fi
  for attempt in 1 2 3; do
    if curl -fsS -X POST "${AUTONOMA_API_URL}/v1/setup/setups/${GENERATION_ID}/events" \
      -H "Authorization: Bearer ${AUTONOMA_API_KEY}" \
      -H "Content-Type: application/json" \
      -d "$payload" >/dev/null; then
      return 0
    fi
    sleep "$attempt"
  done
  echo "ERROR: Failed to post blocking setup event after retries: $payload"
  return 1
}

post_setup_log() {
  refresh_generation_id
  if [ -z "$GENERATION_ID" ]; then
    return 0
  fi
  payload=$(build_event_payload "log" "message" "$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$1")")
  curl -fsS -X POST "${AUTONOMA_API_URL}/v1/setup/setups/${GENERATION_ID}/events" \
    -H "Authorization: Bearer ${AUTONOMA_API_KEY}" \
    -H "Content-Type: application/json" \
    -d "$payload" >/dev/null || true
}

patch_setup_status_blocking() {
  refresh_generation_id
  status="$1"
  message="$2"
  if [ -z "$GENERATION_ID" ]; then
    return 0
  fi
  payload=$(python3 - "$status" "$message" <<'PY'
import json
import sys

body = {"status": sys.argv[1]}
if sys.argv[2]:
    body["errorMessage"] = sys.argv[2]
print(json.dumps(body))
PY
)
  for attempt in 1 2 3; do
    if curl -fsS -X PATCH "${AUTONOMA_API_URL}/v1/setup/setups/${GENERATION_ID}" \
      -H "Authorization: Bearer ${AUTONOMA_API_KEY}" \
      -H "Content-Type: application/json" \
      -d "$payload" >/dev/null; then
      return 0
    fi
    sleep "$attempt"
  done
  echo "ERROR: Failed to patch setup status after retries: $status"
  return 1
}

report_error_and_exit() {
  message="$1"
  preserve_dev_server="${2:-false}"
  payload=$(build_event_payload "error" "message" "$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$message")")
  post_setup_event_blocking "$payload" || true
  echo "ERROR: $message"
  if [ "$preserve_dev_server" != "true" ]; then
    cleanup_dev_server
  fi
  exit 1
}

report_partial_failure_and_exit() {
  message="$1"
  post_setup_log "$message"
  patch_setup_status_blocking "partial_failure" "$message" || true
  echo "ERROR: $message"
  cleanup_dev_server
  exit 1
}

rehydrate_sdk_env() {
  AUTONOMA_ROOT=$(cat /tmp/autonoma-project-root 2>/dev/null || echo '.')
  AUTONOMA_SDK_ENDPOINT=$(tr -d '\n' < "$AUTONOMA_ROOT/autonoma/.sdk-endpoint" 2>/dev/null || echo '')
  AUTONOMA_SHARED_SECRET=$(grep '^AUTONOMA_SHARED_SECRET=' "$AUTONOMA_ROOT/.env" 2>/dev/null | tail -n 1 | cut -d= -f2-)
  AUTONOMA_SIGNING_SECRET=$(grep '^AUTONOMA_SIGNING_SECRET=' "$AUTONOMA_ROOT/.env" 2>/dev/null | tail -n 1 | cut -d= -f2-)
  export AUTONOMA_SDK_ENDPOINT AUTONOMA_SHARED_SECRET AUTONOMA_SIGNING_SECRET
  if [ -z "$AUTONOMA_SDK_ENDPOINT" ] || [ -z "$AUTONOMA_SHARED_SECRET" ] || [ -z "$AUTONOMA_SIGNING_SECRET" ]; then
    return 1
  fi
  return 0
}
```

Prepare the SDK reference repo for Step 1:

```bash
SDK_REF_DIR="${AUTONOMA_SDK_REF_DIR:-}"
if [ -n "$SDK_REF_DIR" ] && [ -d "$SDK_REF_DIR" ]; then
  echo "$SDK_REF_DIR" > /tmp/autonoma-sdk-ref-dir
else
  SDK_REF_DIR="$(mktemp -d)/autonoma-sdk"
  if git clone --depth 1 https://github.com/Autonoma-AI/sdk.git "$SDK_REF_DIR"; then
    echo "$SDK_REF_DIR" > /tmp/autonoma-sdk-ref-dir
  else
    echo "ERROR: Unable to prepare the SDK reference repo."
    cleanup_dev_server
    exit 1
  fi
fi
```

Before creating the record, derive a clean human-readable application name from the repository. Look at the git remote URL, the directory name, and any `package.json` / `pyproject.toml` / `README.md` to infer what the product is actually called. Prefer the product name over the repo slug.

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
echo "$GENERATION_ID" > autonoma/.generation-id
echo "Generation ID: $GENERATION_ID"
```

If `GENERATION_ID` is empty, log the HTTP status and response body above for debugging, then continue anyway.

## Step 1: SDK Integration

Report step start:

```bash
AUTONOMA_ROOT=$(cat /tmp/autonoma-project-root 2>/dev/null || echo '.')
GENERATION_ID=$(cat "$AUTONOMA_ROOT/autonoma/.generation-id" 2>/dev/null || echo '')
SDK_REF_DIR=$(cat /tmp/autonoma-sdk-ref-dir 2>/dev/null || echo '')
echo "GENERATION_ID=${GENERATION_ID:-<empty>}"
post_setup_event_blocking "$(build_step_payload "step.started" "0" "SDK Integration")" || report_error_and_exit "Failed to report Step 1 start."
post_setup_log "Detecting stack and integrating the Autonoma SDK..."
```

Spawn the `sdk-integrator` subagent with the following task:

> Read the SDK reference repo path from `/tmp/autonoma-sdk-ref-dir` and use it as read-only context.
> Detect the project stack, map it against the supported SDK docs matrix, and stop immediately with
> a `mailto:support@autonoma.app` link if unsupported.
> Create a branch, install the SDK from package managers only, implement the SDK endpoint following
> the matching example or README pattern, ensure `AUTONOMA_SHARED_SECRET` and `AUTONOMA_SIGNING_SECRET`
> exist in `.env`, update `.env.example`, keep `autonoma/` out of commits, start or reuse a dev server,
> verify signed `discover`, `up`, and `down`, write `autonoma/.sdk-endpoint` and
> `autonoma/.sdk-integration.json`, commit with
> `feat: integrate autonoma sdk`, and create a PR if `gh` is available.
> Do NOT modify the SDK source repo. Do NOT modify database schemas, migrations, or models.

**After the subagent completes:**
1. Verify `autonoma/.sdk-endpoint` exists and is non-empty
2. Verify `autonoma/.sdk-integration.json` exists and is non-empty
3. Read and export `AUTONOMA_SDK_ENDPOINT` from that file
4. Read `AUTONOMA_SHARED_SECRET` and `AUTONOMA_SIGNING_SECRET` from `.env`
5. Confirm the endpoint is reachable with a signed `discover` request
6. Retain `/tmp/autonoma-dev-server-pid` for cleanup after the pipeline finishes
7. Present the summary to the user — detected stack, packages installed, endpoint URL, PR URL if available

Load the endpoint and secrets:

```bash
python3 "$(cat /tmp/autonoma-plugin-root)/hooks/validators/validate_sdk_endpoint.py" "$AUTONOMA_ROOT/autonoma/.sdk-endpoint" \
  || report_error_and_exit "Step 1 did not produce a valid autonoma/.sdk-endpoint artifact." true
python3 "$(cat /tmp/autonoma-plugin-root)/hooks/validators/validate_sdk_integration.py" "$AUTONOMA_ROOT/autonoma/.sdk-integration.json" \
  || report_error_and_exit "Step 1 did not produce a valid autonoma/.sdk-integration.json artifact." true

rehydrate_sdk_env || report_error_and_exit "Step 1 did not leave a reusable SDK endpoint and both secrets in project files." true

BODY='{"action":"discover"}'
SIG=$(echo -n "$BODY" | openssl dgst -sha256 -hmac "$AUTONOMA_SHARED_SECRET" | sed 's/.*= //')
HTTP_STATUS=$(curl -sS -o /tmp/autonoma-sdk-discover-check.json -w "%{http_code}" -X POST "$AUTONOMA_SDK_ENDPOINT" \
  -H "Content-Type: application/json" \
  -H "x-signature: $SIG" \
  -d "$BODY")
if [ "$HTTP_STATUS" != "200" ]; then
  report_error_and_exit "SDK discover check failed after Step 1 (HTTP $HTTP_STATUS)." true
fi
python3 "$(cat /tmp/autonoma-plugin-root)/hooks/validators/validate_discover.py" /tmp/autonoma-sdk-discover-check.json \
  || report_error_and_exit "Step 1 discover response did not match the required schema." true
```

Report step complete:

```bash
AUTONOMA_ROOT=$(cat /tmp/autonoma-project-root 2>/dev/null || echo '.')
GENERATION_ID=$(cat "$AUTONOMA_ROOT/autonoma/.generation-id" 2>/dev/null || echo '')
echo "GENERATION_ID=${GENERATION_ID:-<empty>}"
post_setup_event_blocking "$(build_step_payload "step.completed" "0" "SDK Integration")" || report_error_and_exit "Failed to report Step 1 completion." true
```

7. **If auto-advance is disabled:** Call `AskUserQuestion` with:
   - question: "Does this SDK integration summary look correct? The next step will use the endpoint produced here."
   - options: ["Yes, proceed to Step 2", "I want to suggest changes"]
   Wait for the user's response before proceeding.
   **Otherwise:** Skip the prompt and proceed directly to Step 2.

## Step 2: Generate Knowledge Base

Report step start:

```bash
AUTONOMA_ROOT=$(cat /tmp/autonoma-project-root 2>/dev/null || echo '.')
GENERATION_ID=$(cat "$AUTONOMA_ROOT/autonoma/.generation-id" 2>/dev/null || echo '')
echo "GENERATION_ID=${GENERATION_ID:-<empty>}"
post_setup_event_blocking "$(build_step_payload "step.started" "1" "Knowledge Base")" || report_error_and_exit "Failed to report Step 2 start."
post_setup_log "Analyzing codebase structure and identifying features..."
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
post_setup_log "Knowledge base complete. Generated ${SKILL_COUNT} skills. Uploading to dashboard..."
post_setup_event_blocking "$(build_step_payload "step.completed" "1" "Knowledge Base")" || report_error_and_exit "Failed to report Step 2 completion."
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

4. **If auto-advance is disabled:** Call `AskUserQuestion` with:
   - question: "Does this core flows table look correct? These flows determine how the test budget is distributed."
   - options: ["Yes, proceed to Step 3", "I want to suggest changes"]
   Wait for the user's response before proceeding.
   **Otherwise:** Skip the prompt and proceed directly to Step 3.

## Step 3: Generate Scenarios

Report step start:

```bash
AUTONOMA_ROOT=$(cat /tmp/autonoma-project-root 2>/dev/null || echo '.')
GENERATION_ID=$(cat "$AUTONOMA_ROOT/autonoma/.generation-id" 2>/dev/null || echo '')
echo "GENERATION_ID=${GENERATION_ID:-<empty>}"
post_setup_event_blocking "$(build_step_payload "step.started" "2" "Scenarios")" || report_error_and_exit "Failed to report Step 3 start."
post_setup_log "Mapping data model and designing test data environments..."
```

Before spawning the subagent, fetch the SDK discover artifact and save it to `autonoma/discover.json`.
This step assumes Step 1 already produced:
- `AUTONOMA_SDK_ENDPOINT`
- `AUTONOMA_SHARED_SECRET`

Fetch and validate the artifact:

```bash
AUTONOMA_ROOT=$(cat /tmp/autonoma-project-root 2>/dev/null || echo '.')
mkdir -p "$AUTONOMA_ROOT/autonoma"
rehydrate_sdk_env || report_error_and_exit "Step 3 could not reload the SDK endpoint and secrets from Step 1."
BODY='{"action":"discover"}'
SIG=$(echo -n "$BODY" | openssl dgst -sha256 -hmac "$AUTONOMA_SHARED_SECRET" | sed 's/.*= //')
RESPONSE=$(curl -sS -w "\nHTTP_STATUS:%{http_code}" -X POST "$AUTONOMA_SDK_ENDPOINT" \
  -H "Content-Type: application/json" \
  -H "x-signature: $SIG" \
  -d "$BODY")
HTTP_STATUS=$(echo "$RESPONSE" | grep -o "HTTP_STATUS:[0-9]*" | cut -d: -f2)
DISCOVER_BODY=$(echo "$RESPONSE" | sed '/HTTP_STATUS:/d')
if [ "$HTTP_STATUS" != "200" ]; then
  report_error_and_exit "SDK discover failed during Step 3 (HTTP $HTTP_STATUS): $DISCOVER_BODY"
fi
printf '%s\n' "$DISCOVER_BODY" > "$AUTONOMA_ROOT/autonoma/discover.json"
python3 "$(cat /tmp/autonoma-plugin-root)/hooks/validators/validate_discover.py" "$AUTONOMA_ROOT/autonoma/discover.json" \
  || report_error_and_exit "Step 3 discover artifact did not pass validation."
```

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
2. Validate `autonoma/discover.json` using the plugin's validator
3. The PostToolUse hook will have validated the frontmatter format automatically
4. Read the file and present the summary to the user — scenario names, entity counts, entity types, discover schema counts, and the minimal variable field tokens that remain dynamic

Report step complete:

```bash
AUTONOMA_ROOT=$(cat /tmp/autonoma-project-root 2>/dev/null || echo '.')
GENERATION_ID=$(cat "$AUTONOMA_ROOT/autonoma/.generation-id" 2>/dev/null || echo '')
echo "GENERATION_ID=${GENERATION_ID:-<empty>}"
post_setup_log "Scenarios generated from SDK discover. Preserved standard/empty/large plus schema metadata, keeping variable fields minimal and intentional."
post_setup_event_blocking "$(build_step_payload "step.completed" "2" "Scenarios")" || report_error_and_exit "Failed to report Step 3 completion."
```

4. **If auto-advance is disabled:** Call `AskUserQuestion` with:
   - question: "Do these scenarios look correct? Most seed values should stay concrete, and only truly dynamic values should remain variable for later tests."
   - options: ["Yes, proceed to Step 4", "I want to suggest changes"]
   Wait for the user's response before proceeding.
   **Otherwise:** Skip the prompt and proceed directly to Step 4.

## Step 4: Generate E2E Test Cases

Report step start:

```bash
AUTONOMA_ROOT=$(cat /tmp/autonoma-project-root 2>/dev/null || echo '.')
GENERATION_ID=$(cat "$AUTONOMA_ROOT/autonoma/.generation-id" 2>/dev/null || echo '')
echo "GENERATION_ID=${GENERATION_ID:-<empty>}"
post_setup_event_blocking "$(build_step_payload "step.started" "3" "E2E Tests")" || report_error_and_exit "Failed to report Step 4 start."
post_setup_log "Generating E2E test cases from knowledge base and scenarios..."
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
2. Verify at least one non-`INDEX.md` test file exists
3. Verify actual test count matches `INDEX.md`
4. Verify folder breakdown matches `INDEX.md`
5. The PostToolUse hook will have validated the INDEX frontmatter and individual test file frontmatter
6. Read the INDEX.md and present the summary to the user — total tests, folder breakdown, coverage correlation

Enforce the file-count postconditions:

```bash
INDEX_PATH="$AUTONOMA_ROOT/autonoma/qa-tests/INDEX.md"
[ -s "$INDEX_PATH" ] || report_error_and_exit "Step 4 did not produce autonoma/qa-tests/INDEX.md."
TEST_COUNT=$(find "$AUTONOMA_ROOT/autonoma/qa-tests" -name '*.md' ! -name 'INDEX.md' 2>/dev/null | wc -l | tr -d ' ')
[ "$TEST_COUNT" -gt 0 ] || report_error_and_exit "Step 4 produced INDEX.md but no actual test files."
python3 - "$INDEX_PATH" "$TEST_COUNT" "$AUTONOMA_ROOT/autonoma/qa-tests" <<'PY' || report_error_and_exit "Step 4 test inventory did not match INDEX.md."
import sys
from pathlib import Path
import yaml

index_path = Path(sys.argv[1])
actual_count = int(sys.argv[2])
qa_dir = Path(sys.argv[3])

content = index_path.read_text()
parts = content.split('---', 2)
if len(parts) < 3:
    raise SystemExit('INDEX.md is missing YAML frontmatter')
frontmatter = yaml.safe_load(parts[1])

if frontmatter.get('total_tests') != actual_count:
    raise SystemExit(
        f'total_tests ({frontmatter.get("total_tests")}) does not match actual test files ({actual_count})'
    )

actual_folders = {}
for path in qa_dir.rglob('*.md'):
    if path.name == 'INDEX.md':
        continue
    folder = path.parent.relative_to(qa_dir).as_posix()
    actual_folders[folder] = actual_folders.get(folder, 0) + 1

declared_folders = {entry['name']: entry['test_count'] for entry in frontmatter.get('folders', [])}
if actual_folders != declared_folders:
    raise SystemExit(f'folder breakdown mismatch: declared={declared_folders} actual={actual_folders}')
print('OK')
PY
```

Report step complete and upload test cases:

```bash
AUTONOMA_ROOT=$(cat /tmp/autonoma-project-root 2>/dev/null || echo '.')
GENERATION_ID=$(cat "$AUTONOMA_ROOT/autonoma/.generation-id" 2>/dev/null || echo '')
echo "GENERATION_ID=${GENERATION_ID:-<empty>}"
TEST_COUNT=$(find "$AUTONOMA_ROOT/autonoma/qa-tests" -name '*.md' ! -name 'INDEX.md' 2>/dev/null | wc -l | tr -d ' ')
post_setup_log "Generated ${TEST_COUNT} test cases. Uploading to dashboard..."
post_setup_event_blocking "$(build_step_payload "step.completed" "3" "E2E Tests")" || report_error_and_exit "Failed to report Step 4 completion."
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

4. **If auto-advance is disabled:** Call `AskUserQuestion` with:
   - question: "Does this test distribution look correct? The total test count should roughly correlate with the number of routes and features in your app."
   - options: ["Yes, proceed to Step 5", "I want to suggest changes"]
   Wait for the user's response before proceeding.
   **Otherwise:** Skip the prompt and proceed directly to Step 5.

## Step 5: Scenario Validation

Report step start:

```bash
AUTONOMA_ROOT=$(cat /tmp/autonoma-project-root 2>/dev/null || echo '.')
GENERATION_ID=$(cat "$AUTONOMA_ROOT/autonoma/.generation-id" 2>/dev/null || echo '')
echo "GENERATION_ID=${GENERATION_ID:-<empty>}"
post_setup_event_blocking "$(build_step_payload "step.started" "4" "Scenario Validation")" || report_error_and_exit "Failed to report Step 5 start."
post_setup_log "Validating planned scenarios against the live SDK endpoint..."
```

Spawn the `scenario-validator` subagent with the following task:

> Read `autonoma/discover.json` and `autonoma/scenarios.md`.
> Validate the planned scenarios against the existing live SDK endpoint without editing backend code.
> Smoke-test the signed `discover -> up -> down` lifecycle, validate `standard`, `empty`, and `large`,
> write approved recipes to `autonoma/scenario-recipes.json`, write the terminal artifact
> `autonoma/.scenario-validation.json`, and run:
> `python3 "$(cat /tmp/autonoma-plugin-root)/hooks/preflight_scenario_recipes.py" autonoma/scenario-recipes.json`
> Do NOT install packages, edit backend code, modify SDK source, modify DB schemas or migrations, or create branches/commits/PRs.

**After the subagent completes:**
1. Rehydrate SDK env from Step 1 artifacts
2. Verify `autonoma/.scenario-validation.json` exists and is non-empty
3. Validate `autonoma/.scenario-validation.json`
4. Require `status == "ok"` and `preflightPassed == true`
5. Verify `autonoma/scenario-recipes.json` exists and is non-empty
6. Run the preflight helper if the subagent did not already do so
7. If preflight fails, stop and report the failure without attempting code changes
8. Present the results to the user — endpoint validated, smoke-test results, per-scenario validation results, any remaining deployment issues

Run and enforce preflight:

```bash
AUTONOMA_ROOT=$(cat /tmp/autonoma-project-root 2>/dev/null || echo '.')
rehydrate_sdk_env || report_partial_failure_and_exit "Step 5 could not reload the SDK endpoint and secrets from Step 1."
python3 "$(cat /tmp/autonoma-plugin-root)/hooks/validators/validate_scenario_validation.py" "$AUTONOMA_ROOT/autonoma/.scenario-validation.json" \
  || report_partial_failure_and_exit "Scenario Validation did not produce a valid autonoma/.scenario-validation.json artifact."
python3 - "$AUTONOMA_ROOT/autonoma/.scenario-validation.json" <<'PY' || report_partial_failure_and_exit "Scenario Validation finished without a successful terminal state."
import json
import sys

payload = json.load(open(sys.argv[1]))
if payload.get("status") != "ok":
    raise SystemExit(f'status must be "ok", got {payload.get("status")!r}')
if payload.get("preflightPassed") is not True:
    raise SystemExit('preflightPassed must be true before Step 5 can upload recipes')
print('OK')
PY
[ -s "$AUTONOMA_ROOT/autonoma/scenario-recipes.json" ] \
  || report_partial_failure_and_exit "Scenario Validation did not leave an authoritative autonoma/scenario-recipes.json artifact."
python3 "$(cat /tmp/autonoma-plugin-root)/hooks/preflight_scenario_recipes.py" "$AUTONOMA_ROOT/autonoma/scenario-recipes.json" \
  || report_partial_failure_and_exit "Scenario recipe preflight failed. Fix the live integration before retrying Step 5."
```

Report step complete and upload scenario recipes:

```bash
AUTONOMA_ROOT=$(cat /tmp/autonoma-project-root 2>/dev/null || echo '.')
GENERATION_ID=$(cat "$AUTONOMA_ROOT/autonoma/.generation-id" 2>/dev/null || echo '')
echo "GENERATION_ID=${GENERATION_ID:-<empty>}"
post_setup_log "Uploading validated scenario recipes to setup..."
if [ -n "$GENERATION_ID" ]; then
  RECIPE_PATH="$AUTONOMA_ROOT/autonoma/scenario-recipes.json"
  if ! python3 -c "import json; json.load(open('$RECIPE_PATH'))" 2>/dev/null; then
    report_partial_failure_and_exit "scenario-recipes.json is not valid JSON. Step 5 cannot complete."
  fi
  UPLOAD_RESPONSE=$(curl -s -w "\nHTTP_STATUS:%{http_code}" -X POST "${AUTONOMA_API_URL}/v1/setup/setups/${GENERATION_ID}/scenario-recipe-versions" \
    -H "Authorization: Bearer ${AUTONOMA_API_KEY}" \
    -H "Content-Type: application/json" \
    -d @"$RECIPE_PATH")
  UPLOAD_STATUS=$(echo "$UPLOAD_RESPONSE" | grep -o "HTTP_STATUS:[0-9]*" | cut -d: -f2)
  UPLOAD_BODY=$(echo "$UPLOAD_RESPONSE" | sed '/HTTP_STATUS:/d')
  echo "Scenario recipe upload response (HTTP $UPLOAD_STATUS): $UPLOAD_BODY"
  if [ "$UPLOAD_STATUS" != "200" ] && [ "$UPLOAD_STATUS" != "201" ]; then
    report_partial_failure_and_exit "Recipe upload failed (HTTP $UPLOAD_STATUS). Step 5 cannot complete."
  fi

  VERIFY_RESPONSE=$(curl -s -w "\nHTTP_STATUS:%{http_code}" -X GET "${AUTONOMA_API_URL}/v1/setup/setups/${GENERATION_ID}/scenarios" \
    -H "Authorization: Bearer ${AUTONOMA_API_KEY}")
  VERIFY_STATUS=$(echo "$VERIFY_RESPONSE" | grep -o "HTTP_STATUS:[0-9]*" | cut -d: -f2)
  VERIFY_BODY=$(echo "$VERIFY_RESPONSE" | sed '/HTTP_STATUS:/d')
  if [ "$VERIFY_STATUS" != "200" ]; then
    report_partial_failure_and_exit "Failed to verify uploaded scenarios (HTTP $VERIFY_STATUS)."
  fi
fi
post_setup_log "Scenario validation completed."
post_setup_event_blocking "$(build_step_payload "step.completed" "4" "Scenario Validation")" || report_partial_failure_and_exit "Failed to report Step 5 completion."
cleanup_dev_server
```

## Completion

After all steps complete, summarize:
- **Step 1**: detected stack, installed packages, endpoint URL, PR URL if available
- **Step 2**: knowledge base location and core flow count
- **Step 3**: scenario count and entity types covered
- **Step 4**: total test count, folder breakdown, coverage correlation
- **Step 5**: scenario validation results, smoke-test status, and recipe upload status

If Step 1 already launched a dev server and its postconditions fail, preserve the server for diagnosis and report the PID.
For terminal failures after later steps begin, clean up the dev server before returning control to the user.
