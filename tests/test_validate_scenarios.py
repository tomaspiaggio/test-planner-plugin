"""Tests for validate_scenarios.py — scenarios.md frontmatter validation."""
from conftest import run_validator

SCRIPT = 'validate_scenarios.py'

VALID = """\
---
scenario_count: 3
scenarios:
  - name: standard
    description: Typical usage
    entity_types: 2
    total_entities: 10
  - name: empty
    description: No data
    entity_types: 0
    total_entities: 0
  - name: large
    description: Stress test
    entity_types: 3
    total_entities: 1000
entity_types:
  - name: user
  - name: task
discover:
  source: sdk
  model_count: 4
  edge_count: 3
  relation_count: 2
  scope_field: organizationId
variable_fields:
  - token: "{{project_title}}"
    entity: Project.title
    scenarios:
      - standard
      - large
    reason: title must be unique per test run
    test_reference: ({{project_title}} variable)
planning_sections:
  - sdk_discover
  - schema_summary
  - relationship_map
  - variable_data_strategy
---

# Scenarios

## SDK Discover

Models: 4

## Schema Summary

- User
- Task

## Relationship Map

- User.organizationId -> Organization.id

## Variable Data Strategy

- `{{project_title}}` is generated.

## Scenario: `standard`

Standard details.

## Scenario: `empty`

Empty details.

## Scenario: `large`

Large details.
"""


def test_valid_scenarios():
    code, out = run_validator(SCRIPT, VALID)
    assert code == 0
    assert out == 'OK'


def test_missing_frontmatter():
    code, out = run_validator(SCRIPT, 'no frontmatter')
    assert code == 1
    assert 'must start with YAML frontmatter' in out


def test_missing_required_fields():
    content = '---\nscenario_count: 3\n---\nbody'
    code, out = run_validator(SCRIPT, content)
    assert code == 1
    assert 'Missing required frontmatter fields' in out


def test_missing_discover_field():
    content = VALID.replace(
        "discover:\n  source: sdk\n  model_count: 4\n  edge_count: 3\n  relation_count: 2\n  scope_field: organizationId\n",
        "",
    )
    code, out = run_validator(SCRIPT, content)
    assert code == 1
    assert "discover" in out


def test_discover_source_must_be_sdk():
    content = VALID.replace('source: sdk', 'source: codebase')
    code, out = run_validator(SCRIPT, content)
    assert code == 1
    assert 'discover.source must be exactly "sdk"' in out


def test_scenario_count_too_low():
    content = VALID.replace('scenario_count: 3', 'scenario_count: 2')
    code, out = run_validator(SCRIPT, content)
    assert code == 1
    assert 'scenario_count must be an integer >= 3' in out


def test_scenario_count_mismatch():
    content = VALID.replace('scenario_count: 3', 'scenario_count: 5')
    code, out = run_validator(SCRIPT, content)
    assert code == 1
    assert 'must match scenario_count' in out


def test_missing_required_scenario_name():
    content = VALID.replace('name: large', 'name: extra')
    code, out = run_validator(SCRIPT, content)
    assert code == 1
    assert 'Missing required scenarios' in out
    assert 'large' in out


def test_scenario_missing_field():
    content = VALID.replace(
        '  - name: standard\n    description: Typical usage',
        '  - name: standard',
    )
    code, out = run_validator(SCRIPT, content)
    assert code == 1
    assert 'missing required field: description' in out


def test_empty_entity_types():
    content = VALID.replace(
        'entity_types:\n  - name: user\n  - name: task',
        'entity_types: []',
    )
    code, out = run_validator(SCRIPT, content)
    assert code == 1
    assert 'entity_types must be a non-empty list' in out


def test_entity_type_missing_name():
    content = VALID.replace(
        'entity_types:\n  - name: user\n  - name: task',
        'entity_types:\n  - description: no name field',
    )
    code, out = run_validator(SCRIPT, content)
    assert code == 1
    assert 'must be a mapping with at least a "name" field' in out


def test_variable_token_must_use_double_curly_braces():
    content = VALID.replace('token: "{{project_title}}"', 'token: project_title')
    code, out = run_validator(SCRIPT, content)
    assert code == 1
    assert 'must use double curly braces' in out


def test_variable_generator_is_optional():
    code, out = run_validator(SCRIPT, VALID)
    assert code == 0
    assert out == 'OK'


def test_non_faker_generator_is_accepted():
    content = VALID.replace(
        '    reason: title must be unique per test run\n',
        '    generator: derived from testRunId\n    reason: title must be unique per test run\n',
    )
    code, out = run_validator(SCRIPT, content)
    assert code == 0
    assert out == 'OK'


def test_empty_generator_fails_if_present():
    content = VALID.replace(
        '    reason: title must be unique per test run\n',
        '    generator: ""\n    reason: title must be unique per test run\n',
    )
    code, out = run_validator(SCRIPT, content)
    assert code == 1
    assert 'generator must be a non-empty string if present' in out


def test_variable_scenarios_must_be_known():
    content = VALID.replace('      - large', '      - invalid')
    code, out = run_validator(SCRIPT, content)
    assert code == 1
    assert 'unknown scenario names' in out


def test_missing_required_planning_section():
    content = VALID.replace(
        'planning_sections:\n  - sdk_discover\n  - schema_summary\n  - relationship_map\n  - variable_data_strategy\n',
        'planning_sections:\n  - sdk_discover\n  - schema_summary\n  - relationship_map\n',
    )
    code, out = run_validator(SCRIPT, content)
    assert code == 1
    assert 'Missing required planning_sections' in out


def test_scoping_analysis_optional_section_accepted():
    content = VALID.replace(
        'planning_sections:\n  - sdk_discover\n  - schema_summary\n  - relationship_map\n  - variable_data_strategy\n',
        'planning_sections:\n  - sdk_discover\n  - schema_summary\n  - relationship_map\n  - variable_data_strategy\n  - scoping_analysis\n',
    )
    code, out = run_validator(SCRIPT, content)
    assert code == 0
    assert out == 'OK'


def test_unknown_planning_section_rejected():
    content = VALID.replace(
        'planning_sections:\n  - sdk_discover\n  - schema_summary\n  - relationship_map\n  - variable_data_strategy\n',
        'planning_sections:\n  - sdk_discover\n  - schema_summary\n  - relationship_map\n  - variable_data_strategy\n  - made_up_section\n',
    )
    code, out = run_validator(SCRIPT, content)
    assert code == 1
    assert 'planning_sections contains unknown value: made_up_section' in out
