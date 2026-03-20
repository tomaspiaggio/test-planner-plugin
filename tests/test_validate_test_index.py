"""Tests for validate_test_index.py — INDEX.md frontmatter validation."""
import json
from conftest import run_validator_with_dir

SCRIPT = 'validate_test_index.py'

FEATURES_DATA = {
    'total_features': 3,
    'total_routes': 5,
    'total_api_routes': 2,
    'features': [
        {'name': 'Login', 'type': 'page', 'path': '/login', 'core': True},
        {'name': 'Dashboard', 'type': 'page', 'path': '/dashboard', 'core': False},
        {'name': 'API Users', 'type': 'api', 'path': '/api/users', 'core': False},
    ],
}

VALID_INDEX = """\
---
total_tests: 8
total_folders: 2
folders:
  - name: auth
    description: Authentication tests
    test_count: 5
    critical: 2
    high: 1
    mid: 1
    low: 1
  - name: dashboard
    description: Dashboard tests
    test_count: 3
    critical: 1
    high: 1
    mid: 0
    low: 1
coverage_correlation:
  routes_or_features: 3
  expected_test_range_min: 6
  expected_test_range_max: 30
---

# Test Index
"""


def _files(index_content=VALID_INDEX, features_data=FEATURES_DATA):
    return {
        'autonoma/qa-tests/INDEX.md': index_content,
        'autonoma/features.json': json.dumps(features_data),
    }


def test_valid_index():
    code, out = run_validator_with_dir(SCRIPT, _files(), 'autonoma/qa-tests/INDEX.md')
    assert code == 0
    assert out == 'OK'


def test_missing_frontmatter():
    files = _files('no frontmatter here')
    code, out = run_validator_with_dir(SCRIPT, files, 'autonoma/qa-tests/INDEX.md')
    assert code == 1
    assert 'must start with YAML frontmatter' in out


def test_missing_required_fields():
    content = '---\ntotal_tests: 5\n---\nbody'
    files = _files(content)
    code, out = run_validator_with_dir(SCRIPT, files, 'autonoma/qa-tests/INDEX.md')
    assert code == 1
    assert 'Missing required frontmatter fields' in out


def test_total_tests_zero():
    content = VALID_INDEX.replace('total_tests: 8', 'total_tests: 0')
    files = _files(content)
    code, out = run_validator_with_dir(SCRIPT, files, 'autonoma/qa-tests/INDEX.md')
    assert code == 1
    assert 'total_tests must be a positive integer' in out


def test_folder_count_mismatch():
    content = VALID_INDEX.replace('total_folders: 2', 'total_folders: 5')
    files = _files(content)
    code, out = run_validator_with_dir(SCRIPT, files, 'autonoma/qa-tests/INDEX.md')
    assert code == 1
    assert 'must match total_folders' in out


def test_criticality_sum_mismatch():
    # Change critical from 2 to 9 in auth folder — sum becomes 12, but test_count is 5
    content = VALID_INDEX.replace('critical: 2\n    high: 1\n    mid: 1\n    low: 1',
                                  'critical: 9\n    high: 1\n    mid: 1\n    low: 1')
    files = _files(content)
    code, out = run_validator_with_dir(SCRIPT, files, 'autonoma/qa-tests/INDEX.md')
    assert code == 1
    assert 'criticality counts' in out
    assert 'do not sum to test_count' in out


def test_folder_test_counts_dont_sum_to_total():
    # total_tests says 99 but folders sum to 8
    content = VALID_INDEX.replace('total_tests: 8', 'total_tests: 99')
    files = _files(content)
    code, out = run_validator_with_dir(SCRIPT, files, 'autonoma/qa-tests/INDEX.md')
    assert code == 1
    assert 'does not match total_tests' in out


def test_total_tests_below_minimum_range():
    # Set min higher than total_tests but still <= max
    content = VALID_INDEX.replace('expected_test_range_min: 6', 'expected_test_range_min: 10')
    content = content.replace('expected_test_range_max: 30', 'expected_test_range_max: 100')
    files = _files(content)
    code, out = run_validator_with_dir(SCRIPT, files, 'autonoma/qa-tests/INDEX.md')
    assert code == 1
    assert 'below minimum' in out


def test_min_greater_than_max():
    content = VALID_INDEX.replace(
        'expected_test_range_min: 6\n  expected_test_range_max: 30',
        'expected_test_range_min: 50\n  expected_test_range_max: 10',
    )
    files = _files(content)
    code, out = run_validator_with_dir(SCRIPT, files, 'autonoma/qa-tests/INDEX.md')
    assert code == 1
    assert 'must be <=' in out


def test_missing_features_json():
    files = {'autonoma/qa-tests/INDEX.md': VALID_INDEX}
    code, out = run_validator_with_dir(SCRIPT, files, 'autonoma/qa-tests/INDEX.md')
    assert code == 1
    assert 'features.json not found' in out


def test_too_few_tests_for_features():
    # 3 features × 2 = 6 minimum, but we'll set total_tests to 4
    index = VALID_INDEX.replace('total_tests: 8', 'total_tests: 4')
    index = index.replace('test_count: 5', 'test_count: 2')
    index = index.replace('critical: 2\n    high: 1\n    mid: 1\n    low: 1',
                           'critical: 1\n    high: 1\n    mid: 0\n    low: 0')
    index = index.replace('test_count: 3', 'test_count: 2')
    index = index.replace('critical: 1\n    high: 1\n    mid: 0\n    low: 1',
                           'critical: 1\n    high: 1\n    mid: 0\n    low: 0')
    index = index.replace('expected_test_range_min: 6', 'expected_test_range_min: 4')
    files = _files(index)
    code, out = run_validator_with_dir(SCRIPT, files, 'autonoma/qa-tests/INDEX.md')
    assert code == 1
    assert 'too low for' in out


def test_underreported_routes_or_features():
    # features.json has 3 features but INDEX claims only 1
    index = VALID_INDEX.replace('routes_or_features: 3', 'routes_or_features: 1')
    files = _files(index)
    code, out = run_validator_with_dir(SCRIPT, files, 'autonoma/qa-tests/INDEX.md')
    assert code == 1
    assert 'underreporting features' in out


def test_folder_missing_required_field():
    # Remove 'low' from first folder
    index = VALID_INDEX.replace('    low: 1\n  - name: dashboard',
                                '\n  - name: dashboard')
    files = _files(index)
    code, out = run_validator_with_dir(SCRIPT, files, 'autonoma/qa-tests/INDEX.md')
    assert code == 1
    assert 'missing required field' in out


def test_negative_criticality_value():
    index = VALID_INDEX.replace('mid: 1\n    low: 1',
                                'mid: -1\n    low: 1', 1)
    files = _files(index)
    code, out = run_validator_with_dir(SCRIPT, files, 'autonoma/qa-tests/INDEX.md')
    assert code == 1
    assert 'must be a non-negative integer' in out
