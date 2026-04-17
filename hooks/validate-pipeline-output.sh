#!/bin/bash
# Validates pipeline output files after Write tool use.
# Exit 0 = allow (file is valid or not a pipeline file)
# Exit 2 = block and send error message to Claude

INPUT=$(cat)

# Extract the file path from the tool input
FILE_PATH=$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('tool_input',{}).get('file_path',''))" 2>/dev/null)

if [ -z "$FILE_PATH" ]; then
  exit 0
fi

# Resolve the validators directory relative to this script
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VALIDATORS_DIR="$SCRIPT_DIR/validators"

# Persist the plugin root so orchestrator/subagent bash snippets can find plugin-local scripts.
# This hook is the earliest reliable place where we know the plugin directory.
PLUGIN_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
echo "$PLUGIN_ROOT" > /tmp/autonoma-plugin-root

# Ensure PyYAML is available (required for frontmatter parsing)
python3 -c "import yaml" 2>/dev/null || pip3 install pyyaml -q 2>/dev/null

# Only validate pipeline output files
case "$FILE_PATH" in
  */autonoma/AUTONOMA.md)
    VALIDATOR_SCRIPT="$VALIDATORS_DIR/validate_kb.py"
    VALIDATOR_NAME="validate-kb"
    ;;
  */autonoma/discover.json)
    VALIDATOR_SCRIPT="$VALIDATORS_DIR/validate_discover.py"
    VALIDATOR_NAME="validate-discover"
    ;;
  */autonoma/.sdk-endpoint)
    VALIDATOR_SCRIPT="$VALIDATORS_DIR/validate_sdk_endpoint.py"
    VALIDATOR_NAME="validate-sdk-endpoint"
    ;;
  */autonoma/.sdk-integration.json)
    VALIDATOR_SCRIPT="$VALIDATORS_DIR/validate_sdk_integration.py"
    VALIDATOR_NAME="validate-sdk-integration"
    ;;
  */autonoma/features.json)
    VALIDATOR_SCRIPT="$VALIDATORS_DIR/validate_features.py"
    VALIDATOR_NAME="validate-features"
    ;;
  */autonoma/scenarios.md)
    VALIDATOR_SCRIPT="$VALIDATORS_DIR/validate_scenarios.py"
    VALIDATOR_NAME="validate-scenarios"
    ;;
  */autonoma/.scenario-validation.json)
    VALIDATOR_SCRIPT="$VALIDATORS_DIR/validate_scenario_validation.py"
    VALIDATOR_NAME="validate-scenario-validation"
    ;;
  */autonoma/scenario-recipes.json)
    VALIDATOR_SCRIPT="$VALIDATORS_DIR/validate_scenario_recipes.py"
    VALIDATOR_NAME="validate-scenario-recipes"
    ;;
  */autonoma/qa-tests/INDEX.md)
    VALIDATOR_SCRIPT="$VALIDATORS_DIR/validate_test_index.py"
    VALIDATOR_NAME="validate-test-index"
    ;;
  */autonoma/qa-tests/*/[!I]*.md)
    VALIDATOR_SCRIPT="$VALIDATORS_DIR/validate_test_file.py"
    VALIDATOR_NAME="validate-test-file"
    ;;
  *)
    exit 0
    ;;
esac

# Check file exists
if [ ! -f "$FILE_PATH" ]; then
  echo "VALIDATION FAILED [$VALIDATOR_NAME]: File does not exist: $FILE_PATH" >&2
  exit 2
fi

# Check file is non-empty
if [ ! -s "$FILE_PATH" ]; then
  echo "VALIDATION FAILED [$VALIDATOR_NAME]: File is empty: $FILE_PATH" >&2
  exit 2
fi

# Check validator script exists
if [ ! -f "$VALIDATOR_SCRIPT" ]; then
  echo "VALIDATION FAILED [$VALIDATOR_NAME]: Validator script not found: $VALIDATOR_SCRIPT" >&2
  exit 2
fi

# Run the validator
RESULT=$(python3 "$VALIDATOR_SCRIPT" "$FILE_PATH" 2>&1)
EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ] || [ "$RESULT" != "OK" ]; then
  echo "VALIDATION FAILED [$VALIDATOR_NAME]: $RESULT" >&2
  exit 2
fi

# scenario-recipes.json must also pass live endpoint preflight. This is the
# only deterministic check that the generated create payload actually works
# against the current SDK contract.
if [ "$VALIDATOR_NAME" = "validate-scenario-recipes" ]; then
  PREFLIGHT_SCRIPT="$SCRIPT_DIR/preflight_scenario_recipes.py"
  if [ ! -f "$PREFLIGHT_SCRIPT" ]; then
    echo "VALIDATION FAILED [scenario-recipes-preflight]: Script not found: $PREFLIGHT_SCRIPT" >&2
    exit 2
  fi

  PREFLIGHT_RESULT=$(python3 "$PREFLIGHT_SCRIPT" "$FILE_PATH" 2>&1)
  PREFLIGHT_EXIT=$?
  if [ $PREFLIGHT_EXIT -ne 0 ]; then
    echo "VALIDATION FAILED [scenario-recipes-preflight]: $PREFLIGHT_RESULT" >&2
    exit 2
  fi
fi

# For INDEX.md, also validate directory structure
if [ "$VALIDATOR_NAME" = "validate-test-index" ]; then
  DIR_SCRIPT="$VALIDATORS_DIR/validate_directory_structure.py"
  DIR_RESULT=$(python3 "$DIR_SCRIPT" "$FILE_PATH" 2>&1)
  DIR_EXIT=$?
  if [ $DIR_EXIT -ne 0 ] || [ "$DIR_RESULT" != "OK" ]; then
    echo "VALIDATION FAILED [validate-directory-structure]: $DIR_RESULT" >&2
    exit 2
  fi
fi

exit 0
