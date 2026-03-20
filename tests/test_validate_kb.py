"""Tests for validate_kb.py — AUTONOMA.md frontmatter validation."""
from conftest import run_validator

SCRIPT = 'validate_kb.py'

VALID = """\
---
app_name: My App
app_description: A full-featured application for managing tasks and projects.
feature_count: 3
skill_count: 2
core_flows:
  - feature: login
    description: User logs in
    core: true
  - feature: dashboard
    description: View dashboard
    core: false
---

# Knowledge Base
"""


def test_valid_kb():
    code, out = run_validator(SCRIPT, VALID)
    assert code == 0
    assert out == 'OK'


def test_missing_frontmatter_delimiters():
    code, out = run_validator(SCRIPT, 'no frontmatter here')
    assert code == 1
    assert 'must start with YAML frontmatter' in out


def test_missing_closing_delimiter():
    code, out = run_validator(SCRIPT, '---\napp_name: x\n')
    assert code == 1
    assert 'Missing closing ---' in out


def test_invalid_yaml():
    code, out = run_validator(SCRIPT, '---\n: :\n  bad yaml\n---\n')
    assert code == 1
    assert 'Invalid YAML' in out


def test_missing_required_fields():
    content = '---\napp_name: x\n---\nbody'
    code, out = run_validator(SCRIPT, content)
    assert code == 1
    assert 'Missing required frontmatter fields' in out
    assert 'app_description' in out


def test_app_description_too_short():
    content = VALID.replace(
        'A full-featured application for managing tasks and projects.',
        'Short',
    )
    code, out = run_validator(SCRIPT, content)
    assert code == 1
    assert 'app_description' in out


def test_empty_core_flows():
    content = VALID.replace(
        'core_flows:\n  - feature: login\n    description: User logs in\n    core: true\n  - feature: dashboard\n    description: View dashboard\n    core: false',
        'core_flows: []',
    )
    code, out = run_validator(SCRIPT, content)
    assert code == 1
    assert 'core_flows must be a non-empty list' in out


def test_core_flow_missing_field():
    content = VALID.replace(
        '  - feature: login\n    description: User logs in\n    core: true',
        '  - feature: login\n    core: true',
    )
    code, out = run_validator(SCRIPT, content)
    assert code == 1
    assert 'missing required field: description' in out


def test_no_core_true_flow():
    content = VALID.replace('core: true', 'core: false')
    code, out = run_validator(SCRIPT, content)
    assert code == 1
    assert 'At least one core_flow must have core: true' in out


def test_core_not_boolean():
    content = VALID.replace('core: true', 'core: yes_please')
    code, out = run_validator(SCRIPT, content)
    assert code == 1
    assert 'must be a boolean' in out


def test_feature_count_zero():
    content = VALID.replace('feature_count: 3', 'feature_count: 0')
    code, out = run_validator(SCRIPT, content)
    assert code == 1
    assert 'feature_count must be a positive integer' in out


def test_skill_count_not_integer():
    content = VALID.replace('skill_count: 2', 'skill_count: many')
    code, out = run_validator(SCRIPT, content)
    assert code == 1
    assert 'skill_count must be a positive integer' in out
