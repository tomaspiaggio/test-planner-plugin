"""Tests for validate_scenarios.py — scenarios.md frontmatter validation."""
from conftest import run_validator

SCRIPT = 'validate_scenarios.py'

VALID = """\
---
scenario_count: 3
scenarios:
  - name: standard
    description: Typical usage
    entity_types: [user, task]
    total_entities: 10
  - name: empty
    description: No data
    entity_types: [user]
    total_entities: 0
  - name: large
    description: Stress test
    entity_types: [user, task, project]
    total_entities: 1000
entity_types:
  - name: user
  - name: task
variable_fields: []
planning_sections:
  - schema_summary
  - relationship_map
  - variable_data_strategy
---

# Scenarios
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
    # Replace 'large' with 'extra' — now 'large' is missing
    content = VALID.replace('name: large', 'name: extra')
    code, out = run_validator(SCRIPT, content)
    assert code == 1
    assert 'Missing required scenarios' in out
    assert 'large' in out


def test_scenario_missing_field():
    # Remove description from first scenario
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
