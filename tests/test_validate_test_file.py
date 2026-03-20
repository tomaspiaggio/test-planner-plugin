"""Tests for validate_test_file.py — individual test file frontmatter validation."""
from conftest import run_validator

SCRIPT = 'validate_test_file.py'

VALID = """\
---
title: User can log in with valid credentials
description: Verifies the login flow with correct email and password
criticality: critical
scenario: standard
flow: login
---

## Steps
1. Navigate to /login
2. Enter credentials
3. Click submit
"""


def test_valid_test_file():
    code, out = run_validator(SCRIPT, VALID)
    assert code == 0
    assert out == 'OK'


def test_missing_frontmatter():
    code, out = run_validator(SCRIPT, 'no frontmatter')
    assert code == 1
    assert 'must start with YAML frontmatter' in out


def test_missing_required_fields():
    content = '---\ntitle: x\n---\nbody'
    code, out = run_validator(SCRIPT, content)
    assert code == 1
    assert 'Missing required frontmatter fields' in out


def test_invalid_criticality():
    content = VALID.replace('criticality: critical', 'criticality: ultra')
    code, out = run_validator(SCRIPT, content)
    assert code == 1
    assert 'criticality must be one of' in out


def test_all_valid_criticalities():
    for level in ['critical', 'high', 'mid', 'low']:
        content = VALID.replace('criticality: critical', f'criticality: {level}')
        code, out = run_validator(SCRIPT, content)
        assert code == 0, f'criticality={level} should be valid, got: {out}'


def test_empty_title():
    content = VALID.replace(
        'title: User can log in with valid credentials',
        'title: ""',
    )
    code, out = run_validator(SCRIPT, content)
    assert code == 1
    assert 'title must be a non-empty string' in out


def test_empty_scenario():
    content = VALID.replace('scenario: standard', 'scenario: ""')
    code, out = run_validator(SCRIPT, content)
    assert code == 1
    assert 'scenario must be a non-empty string' in out


def test_empty_flow():
    content = VALID.replace('flow: login', 'flow: "  "')
    code, out = run_validator(SCRIPT, content)
    assert code == 1
    assert 'flow must be a non-empty string' in out


def test_description_whitespace_only():
    content = VALID.replace(
        'description: Verifies the login flow with correct email and password',
        'description: "   "',
    )
    code, out = run_validator(SCRIPT, content)
    assert code == 1
    assert 'description must be a non-empty string' in out
