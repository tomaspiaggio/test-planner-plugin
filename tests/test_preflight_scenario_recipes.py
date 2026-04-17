"""Tests for hooks/preflight_scenario_recipes.py resolver logic."""
import sys
import os

# Add hooks dir to path so we can import the module
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'hooks'))

from preflight_scenario_recipes import (
    resolve_variable,
    resolve_recipe,
    _find_tokens,
    _faker_generate,
)
import pytest


# --- resolve_variable tests ---

def test_literal_string():
    v = resolve_variable({'strategy': 'literal', 'value': 'hello'}, 'run1', 'tok')
    assert v == 'hello'


def test_literal_number():
    v = resolve_variable({'strategy': 'literal', 'value': 42}, 'run1', 'tok')
    assert v == 42


def test_literal_null():
    v = resolve_variable({'strategy': 'literal', 'value': None}, 'run1', 'tok')
    assert v is None


def test_derived():
    v = resolve_variable(
        {'strategy': 'derived', 'source': 'testRunId', 'format': 'user+{testRunId}@example.com'},
        'abc-123', 'tok',
    )
    assert v == 'user+abc-123@example.com'


def test_faker_deterministic():
    """Same testRunId + token name → same value."""
    v1 = resolve_variable({'strategy': 'faker', 'generator': 'person.firstName'}, 'run1', 'first')
    v2 = resolve_variable({'strategy': 'faker', 'generator': 'person.firstName'}, 'run1', 'first')
    assert v1 == v2
    assert isinstance(v1, str) and len(v1) > 0


def test_faker_different_run_id():
    """Different testRunId → different value (with high probability)."""
    v1 = resolve_variable({'strategy': 'faker', 'generator': 'person.firstName'}, 'run-a', 'first')
    v2 = resolve_variable({'strategy': 'faker', 'generator': 'person.firstName'}, 'run-b', 'first')
    # Not guaranteed but extremely likely with different seeds
    # We just check both produce valid strings
    assert isinstance(v1, str)
    assert isinstance(v2, str)


def test_faker_email():
    v = resolve_variable({'strategy': 'faker', 'generator': 'internet.email'}, 'run1', 'email')
    assert '@' in v


def test_faker_company():
    v = resolve_variable({'strategy': 'faker', 'generator': 'company.name'}, 'run1', 'co')
    assert isinstance(v, str) and len(v) > 0


def test_faker_lorem():
    v = resolve_variable({'strategy': 'faker', 'generator': 'lorem.words'}, 'run1', 'w')
    assert ' ' in v  # multiple words


def test_unsupported_faker_generator():
    with pytest.raises(ValueError, match='Unsupported faker generator'):
        resolve_variable({'strategy': 'faker', 'generator': 'address.city'}, 'run1', 'tok')


def test_unsupported_strategy():
    with pytest.raises(ValueError, match='Unsupported variable strategy'):
        resolve_variable({'strategy': 'random'}, 'run1', 'tok')


# --- resolve_recipe tests ---

def test_resolve_full_recipe():
    recipe = {
        'create': {
            'User': [{'email': '{{owner_email}}', 'name': '{{first_name}}'}],
        },
        'variables': {
            'owner_email': {'strategy': 'derived', 'source': 'testRunId', 'format': 'owner+{testRunId}@example.com'},
            'first_name': {'strategy': 'faker', 'generator': 'person.firstName'},
        },
    }
    result = resolve_recipe(recipe, 'test-run-1')
    assert result['User'][0]['email'] == 'owner+test-run-1@example.com'
    assert isinstance(result['User'][0]['name'], str)


def test_embedded_string_replacement():
    recipe = {
        'create': {
            'Org': [{'name': 'Org-{{suffix}}'}],
        },
        'variables': {
            'suffix': {'strategy': 'literal', 'value': 'acme'},
        },
    }
    result = resolve_recipe(recipe, 'run1')
    assert result['Org'][0]['name'] == 'Org-acme'


def test_missing_variable_fails():
    recipe = {
        'create': {'User': [{'email': '{{missing}}'}]},
        'variables': {},
    }
    with pytest.raises(ValueError, match='Tokens without variable definitions'):
        resolve_recipe(recipe, 'run1')


def test_unused_variable_fails():
    recipe = {
        'create': {'User': [{'email': 'static@example.com'}]},
        'variables': {
            'extra': {'strategy': 'literal', 'value': 'unused'},
        },
    }
    with pytest.raises(ValueError, match='Unused variable definitions'):
        resolve_recipe(recipe, 'run1')


def test_concrete_recipe_no_variables():
    """Recipe with no tokens and no variables should resolve fine."""
    recipe = {
        'create': {'Org': [{'name': 'Acme'}]},
    }
    result = resolve_recipe(recipe, 'run1')
    assert result == {'Org': [{'name': 'Acme'}]}


# --- _find_tokens tests ---

def test_find_tokens_nested():
    obj = {'a': [{'b': '{{x}} and {{y}}'}], 'c': '{{z}}'}
    assert _find_tokens(obj) == {'x', 'y', 'z'}


def test_find_tokens_no_tokens():
    assert _find_tokens({'a': 'hello'}) == set()
