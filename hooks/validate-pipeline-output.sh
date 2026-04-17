#!/bin/bash
# Validates pipeline output files after Write tool use and emits lifecycle
# events + artifact uploads to the Autonoma dashboard on successful artifact
# production. All backend reporting lives here so the agent can never forget.
#
# Exit 0 = allow (file is valid or not a pipeline file)
# Exit 2 = block and send error message to Claude

set -u

INPUT=$(cat)

FILE_PATH=$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('tool_input',{}).get('file_path',''))" 2>/dev/null)

if [ -z "$FILE_PATH" ]; then
  exit 0
fi

# ----------------------------------------------------------------------------
# Lifecycle emission helpers
# ----------------------------------------------------------------------------
_reporting_ready() {
  local generation_id
  generation_id=$(cat autonoma/.generation-id 2>/dev/null || echo '')
  [ -n "$generation_id" ] && [ -n "${AUTONOMA_API_URL:-}" ] && [ -n "${AUTONOMA_API_KEY:-}" ]
}

# emit_step_event <step> <started|completed> [<name>] — idempotent via marker.
emit_step_event() {
  local step="$1"
  local action="$2"
  local name="${3:-}"
  local marker="autonoma/.step-${step}-${action}"

  [ -f "$marker" ] && return 0
  mkdir -p autonoma 2>/dev/null || true
  touch "$marker"

  _reporting_ready || return 0
  local generation_id
  generation_id=$(cat autonoma/.generation-id)

  local payload
  if [ -n "$name" ]; then
    payload=$(printf '{"type":"step.%s","data":{"step":%s,"name":"%s"}}' "$action" "$step" "$name")
  else
    payload=$(printf '{"type":"step.%s","data":{"step":%s}}' "$action" "$step")
  fi

  curl -sf -X POST "${AUTONOMA_API_URL}/v1/setup/setups/${generation_id}/events" \
    -H "Authorization: Bearer ${AUTONOMA_API_KEY}" \
    -H "Content-Type: application/json" \
    -d "$payload" >/dev/null 2>&1 || true
}

# upload_skills — bundle autonoma/skills/*.md and POST to /artifacts. Idempotent.
upload_skills() {
  local marker="autonoma/.skills-uploaded"
  [ -f "$marker" ] && return 0
  _reporting_ready || return 0
  [ -d autonoma/skills ] || return 0

  local generation_id
  generation_id=$(cat autonoma/.generation-id)

  python3 -c "
import os, json
skills = []
d = 'autonoma/skills'
if os.path.isdir(d):
    for f in sorted(os.listdir(d)):
        if f.endswith('.md'):
            with open(os.path.join(d, f)) as fh:
                skills.append({'name': f, 'content': fh.read()})
print(json.dumps({'skills': skills}))
" | curl -sf -X POST "${AUTONOMA_API_URL}/v1/setup/setups/${generation_id}/artifacts" \
    -H "Authorization: Bearer ${AUTONOMA_API_KEY}" \
    -H "Content-Type: application/json" \
    -d @- >/dev/null 2>&1 || true

  touch "$marker"
}

# upload_test_cases — bundle autonoma/qa-tests/**/*.md (except INDEX) and POST. Idempotent.
upload_test_cases() {
  local marker="autonoma/.test-cases-uploaded"
  [ -f "$marker" ] && return 0
  _reporting_ready || return 0
  [ -d autonoma/qa-tests ] || return 0

  local generation_id
  generation_id=$(cat autonoma/.generation-id)

  python3 -c "
import os, json
test_cases = []
for root, dirs, files in os.walk('autonoma/qa-tests'):
    for f in sorted(files):
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
" | curl -sf -X POST "${AUTONOMA_API_URL}/v1/setup/setups/${generation_id}/artifacts" \
    -H "Authorization: Bearer ${AUTONOMA_API_KEY}" \
    -H "Content-Type: application/json" \
    -d @- >/dev/null 2>&1 || true

  touch "$marker"
}

# ----------------------------------------------------------------------------
# Sentinel files: no validation, just event emission.
#   - autonoma/.endpoint-implemented — env-factory agent writes this after the
#     discover smoke test + factory-integrity check pass; signals step 3 complete.
#   - autonoma/.endpoint-validated — scenario-validator writes this after the full
#     up/down lifecycle passes for every scenario; signals step 4 complete AND
#     unlocks the gate that allows qa-tests/*.md to be written.
#   - autonoma/.step-<N>-ack — orchestrator writes this AFTER the user has
#     confirmed via AskUserQuestion; this is the *only* path that emits
#     step.started for step N. The UI can therefore show "waiting for
#     confirmation" in the gap between step.completed (N-1) and step.started N.
# ----------------------------------------------------------------------------
STEP_NAMES=("Knowledge Base" "Entity Audit" "Scenarios" "Implement" "Validate" "E2E Tests")

case "$FILE_PATH" in
  */autonoma/.endpoint-implemented)
    emit_step_event 3 completed "Implement"
    exit 0
    ;;
  */autonoma/.endpoint-validated)
    emit_step_event 4 completed "Validate"
    exit 0
    ;;
  */autonoma/.pipeline-complete)
    emit_step_event 5 completed "E2E Tests"
    exit 0
    ;;
  */autonoma/.step-*-ack)
    ack_num=$(basename "$FILE_PATH" | sed -E 's/^\.step-([0-9]+)-ack$/\1/')
    if [[ "$ack_num" =~ ^[0-9]+$ ]] && [ "$ack_num" -ge 0 ] && [ "$ack_num" -lt ${#STEP_NAMES[@]} ]; then
      emit_step_event "$ack_num" started "${STEP_NAMES[$ack_num]}"
    fi
    exit 0
    ;;
esac

# ----------------------------------------------------------------------------
# Validation gate: test files (INDEX.md or any qa-tests/*.md) cannot be written
# until the scenario-validator writes autonoma/.endpoint-validated. This
# prevents step 6 from generating tests against an unproven endpoint.
# ----------------------------------------------------------------------------
case "$FILE_PATH" in
  */autonoma/qa-tests/INDEX.md|*/autonoma/qa-tests/*.md)
    if [ ! -f "autonoma/.endpoint-validated" ]; then
      echo "VALIDATION GATE: Cannot write $FILE_PATH — autonoma/.endpoint-validated is missing. Complete Step 5 (scenario-validator) first. The validator must run discover/up/down against every scenario and write the sentinel before test generation is allowed." >&2
      exit 2
    fi
    ;;
esac

# ----------------------------------------------------------------------------
# Validation routing
# ----------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VALIDATORS_DIR="$SCRIPT_DIR/validators"

python3 -c "import yaml" 2>/dev/null || pip3 install pyyaml -q 2>/dev/null

STEP_COMPLETED=""
STEP_COMPLETED_NAME=""
STEP_STARTED=""
STEP_STARTED_NAME=""
POST_UPLOAD=""

case "$FILE_PATH" in
  */autonoma/AUTONOMA.md)
    VALIDATOR_SCRIPT="$VALIDATORS_DIR/validate_kb.py"
    VALIDATOR_NAME="validate-kb"
    STEP_COMPLETED=0
    STEP_COMPLETED_NAME="Knowledge Base"
    STEP_STARTED=1
    STEP_STARTED_NAME="Entity Audit"
    POST_UPLOAD="skills"
    ;;
  */autonoma/features.json)
    VALIDATOR_SCRIPT="$VALIDATORS_DIR/validate_features.py"
    VALIDATOR_NAME="validate-features"
    ;;
  */autonoma/entity-audit.md)
    VALIDATOR_SCRIPT="$VALIDATORS_DIR/validate_entity_audit.py"
    VALIDATOR_NAME="validate-entity-audit"
    STEP_COMPLETED=1
    STEP_COMPLETED_NAME="Entity Audit"
    STEP_STARTED=2
    STEP_STARTED_NAME="Scenarios"
    ;;
  */autonoma/scenarios.md)
    VALIDATOR_SCRIPT="$VALIDATORS_DIR/validate_scenarios.py"
    VALIDATOR_NAME="validate-scenarios"
    STEP_COMPLETED=2
    STEP_COMPLETED_NAME="Scenarios"
    STEP_STARTED=3
    STEP_STARTED_NAME="Implement"
    ;;
  */autonoma/qa-tests/INDEX.md)
    VALIDATOR_SCRIPT="$VALIDATORS_DIR/validate_test_index.py"
    VALIDATOR_NAME="validate-test-index"
    STEP_COMPLETED=5
    STEP_COMPLETED_NAME="E2E Tests"
    POST_UPLOAD="test_cases"
    ;;
  */autonoma/qa-tests/*/[!I]*.md)
    VALIDATOR_SCRIPT="$VALIDATORS_DIR/validate_test_file.py"
    VALIDATOR_NAME="validate-test-file"
    ;;
  *)
    exit 0
    ;;
esac

if [ ! -f "$FILE_PATH" ]; then
  echo "VALIDATION FAILED [$VALIDATOR_NAME]: File does not exist: $FILE_PATH" >&2
  exit 2
fi

if [ ! -s "$FILE_PATH" ]; then
  echo "VALIDATION FAILED [$VALIDATOR_NAME]: File is empty: $FILE_PATH" >&2
  exit 2
fi

if [ ! -f "$VALIDATOR_SCRIPT" ]; then
  echo "VALIDATION FAILED [$VALIDATOR_NAME]: Validator script not found: $VALIDATOR_SCRIPT" >&2
  exit 2
fi

RESULT=$(python3 "$VALIDATOR_SCRIPT" "$FILE_PATH" 2>&1)
EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ] || [ "$RESULT" != "OK" ]; then
  echo "VALIDATION FAILED [$VALIDATOR_NAME]: $RESULT" >&2
  exit 2
fi

if [ "$VALIDATOR_NAME" = "validate-test-index" ]; then
  DIR_SCRIPT="$VALIDATORS_DIR/validate_directory_structure.py"
  DIR_RESULT=$(python3 "$DIR_SCRIPT" "$FILE_PATH" 2>&1)
  DIR_EXIT=$?
  if [ $DIR_EXIT -ne 0 ] || [ "$DIR_RESULT" != "OK" ]; then
    echo "VALIDATION FAILED [validate-directory-structure]: $DIR_RESULT" >&2
    exit 2
  fi
fi

# Validation passed — emit lifecycle events and upload artifacts.
# Note: step.started for the NEXT step is NOT emitted here. It fires only when
# the orchestrator writes autonoma/.step-<N>-ack after the user confirms via
# AskUserQuestion. That gap gives the UI its "waiting for confirmation" banner.
if [ -n "$STEP_COMPLETED" ]; then
  emit_step_event "$STEP_COMPLETED" completed "$STEP_COMPLETED_NAME"
fi

case "$POST_UPLOAD" in
  skills) upload_skills ;;
  test_cases) upload_test_cases ;;
esac

exit 0
