"""Tests for validate_scenario_recipes.py."""
import json
from conftest import run_validator, run_validator_with_dir

SCRIPT = 'validate_scenario_recipes.py'

VALID_DISCOVER = {
    'schema': {
        'models': [
            {
                'name': 'Organization',
                'fields': [
                    {'name': 'name', 'type': 'String', 'isRequired': True, 'isId': False, 'hasDefault': False},
                    {'name': 'communicationChannel', 'type': 'enum(slack)', 'isRequired': False, 'isId': False, 'hasDefault': False},
                    {'name': 'teamSlugs', 'type': 'String[]', 'isRequired': True, 'isId': False, 'hasDefault': True},
                ],
            },
            {
                'name': 'User',
                'fields': [
                    {'name': 'email', 'type': 'String', 'isRequired': True, 'isId': False, 'hasDefault': False},
                    {'name': 'name', 'type': 'String', 'isRequired': True, 'isId': False, 'hasDefault': False},
                ],
            },
        ],
        'edges': [],
        'relations': [],
        'scopeField': 'organizationId',
    }
}

VALID_DATA = {
    'version': 1,
    'source': {
        'discoverPath': 'autonoma/discover.json',
        'scenariosPath': 'autonoma/scenarios.md',
    },
    'validationMode': 'sdk-check',
    'recipes': [
        {
            'name': 'standard',
            'description': 'Realistic variety for core flows',
            'create': {
                'Organization': [{'name': 'Standard Org {{testRunId}}'}],
            },
            'validation': {
                'status': 'validated',
                'method': 'checkScenario',
                'phase': 'ok',
                'up_ms': 12,
                'down_ms': 8,
            },
        },
        {
            'name': 'empty',
            'description': 'Empty-state scenario',
            'create': {
                'Organization': [{'name': 'Empty Org {{testRunId}}'}],
            },
            'validation': {
                'status': 'validated',
                'method': 'checkScenario',
                'phase': 'ok',
            },
        },
        {
            'name': 'large',
            'description': 'High-volume scenario',
            'create': {
                'Organization': [{'name': 'Large Org {{testRunId}}'}],
            },
            'validation': {
                'status': 'validated',
                'method': 'endpoint-up-down',
                'phase': 'ok',
                'up_ms': 120,
                'down_ms': 65,
            },
        },
    ],
}

VALID_DATA_WITH_VARIABLES = {
    'version': 1,
    'source': {
        'discoverPath': 'autonoma/discover.json',
        'scenariosPath': 'autonoma/scenarios.md',
    },
    'validationMode': 'sdk-check',
    'recipes': [
        {
            'name': 'standard',
            'description': 'Realistic variety for core flows',
            'create': {
                'User': [{'email': '{{owner_email}}'}],
            },
            'variables': {
                'owner_email': {
                    'strategy': 'derived',
                    'source': 'testRunId',
                    'format': 'owner+{testRunId}@example.com',
                },
            },
            'validation': {
                'status': 'validated',
                'method': 'checkScenario',
                'phase': 'ok',
            },
        },
        {
            'name': 'empty',
            'description': 'Empty-state scenario',
            'create': {
                'Organization': [{'name': 'Empty Org'}],
            },
            'validation': {
                'status': 'validated',
                'method': 'checkScenario',
                'phase': 'ok',
            },
        },
        {
            'name': 'large',
            'description': 'High-volume scenario',
            'create': {
                'Organization': [{'name': '{{company}}'}],
            },
            'variables': {
                'company': {
                    'strategy': 'faker',
                    'generator': 'company.name',
                },
            },
            'validation': {
                'status': 'validated',
                'method': 'endpoint-up-down',
                'phase': 'ok',
            },
        },
    ],
}


def _json(data):
    return json.dumps(data)


def _run_recipe_validator(data, discover=None):
    if discover is None:
        discover = VALID_DISCOVER
    files = {
        'autonoma/scenario-recipes.json': _json(data),
        'autonoma/discover.json': _json(discover),
    }
    return run_validator_with_dir(SCRIPT, files, 'autonoma/scenario-recipes.json')


def test_valid_scenario_recipes():
    code, out = _run_recipe_validator(VALID_DATA)
    assert code == 0
    assert out == 'OK'


def test_valid_with_variables():
    code, out = _run_recipe_validator(VALID_DATA_WITH_VARIABLES)
    assert code == 0
    assert out == 'OK'


def test_valid_concrete_without_variables():
    """Fully concrete recipes (no tokens) should pass without variables."""
    data = {
        'version': 1,
        'source': {'discoverPath': 'autonoma/discover.json', 'scenariosPath': 'autonoma/scenarios.md'},
        'validationMode': 'sdk-check',
        'recipes': [
            {'name': 'standard', 'description': 'Std', 'create': {'Organization': [{'name': 'Acme'}]},
             'validation': {'status': 'validated', 'method': 'checkScenario', 'phase': 'ok'}},
            {'name': 'empty', 'description': 'Empty', 'create': {'Organization': [{'name': 'None'}]},
             'validation': {'status': 'validated', 'method': 'checkScenario', 'phase': 'ok'}},
            {'name': 'large', 'description': 'Large', 'create': {'Organization': [{'name': 'Big'}]},
             'validation': {'status': 'validated', 'method': 'checkScenario', 'phase': 'ok'}},
        ],
    }
    code, out = _run_recipe_validator(data)
    assert code == 0
    assert out == 'OK'


def test_invalid_json():
    code, out = run_validator(SCRIPT, '{not json', 'scenario-recipes.json')
    assert code == 1
    assert 'Invalid JSON' in out


def test_missing_required_fields():
    code, out = _run_recipe_validator({'recipes': []})
    assert code == 1
    assert 'Missing required fields' in out


def test_invalid_validation_mode():
    data = {**VALID_DATA, 'validationMode': 'rollback'}
    code, out = _run_recipe_validator(data)
    assert code == 1
    assert 'validationMode must be one of' in out


def test_missing_required_recipe_name():
    data = {**VALID_DATA}
    data['recipes'] = [
        VALID_DATA['recipes'][0],
        VALID_DATA['recipes'][1],
        {
            'name': 'custom',
            'description': 'Extra recipe',
            'create': {
                'Organization': [{'name': 'Custom Org {{testRunId}}'}],
            },
            'validation': {
                'status': 'validated',
                'method': 'checkScenario',
                'phase': 'ok',
            },
        },
    ]
    code, out = _run_recipe_validator(data)
    assert code == 1
    assert 'Missing required recipes' in out


def test_recipe_requires_create():
    data = {**VALID_DATA}
    data['recipes'] = [dict(recipe) for recipe in VALID_DATA['recipes']]
    data['recipes'][0]['create'] = {}
    code, out = _run_recipe_validator(data)
    assert code == 1
    assert 'create must be a non-empty object' in out


def test_validation_status_must_be_validated():
    data = {**VALID_DATA}
    data['recipes'] = [dict(recipe) for recipe in VALID_DATA['recipes']]
    data['recipes'][0]['validation'] = dict(data['recipes'][0]['validation'])
    data['recipes'][0]['validation']['status'] = 'draft'
    code, out = _run_recipe_validator(data)
    assert code == 1
    assert 'validation.status must be exactly "validated"' in out


def test_validation_phase_must_be_ok():
    data = {**VALID_DATA}
    data['recipes'] = [dict(recipe) for recipe in VALID_DATA['recipes']]
    data['recipes'][0]['validation'] = dict(data['recipes'][0]['validation'])
    data['recipes'][0]['validation']['phase'] = 'up'
    code, out = _run_recipe_validator(data)
    assert code == 1
    assert 'validation.phase must be exactly "ok"' in out


def test_validation_method_must_be_known():
    data = {**VALID_DATA}
    data['recipes'] = [dict(recipe) for recipe in VALID_DATA['recipes']]
    data['recipes'][0]['validation'] = dict(data['recipes'][0]['validation'])
    data['recipes'][0]['validation']['method'] = 'custom'
    code, out = _run_recipe_validator(data)
    assert code == 1
    assert 'validation.method must be one of' in out


# --- Variables validation tests ---

def test_token_without_variable_definition():
    """Token in create with no matching variable should fail."""
    import copy
    data = copy.deepcopy(VALID_DATA_WITH_VARIABLES)
    # Add a token but no variable
    data['recipes'][0]['create']['User'][0]['name'] = '{{missing_var}}'
    code, out = _run_recipe_validator(data)
    assert code == 1
    assert 'tokens without variable definitions' in out


def test_unused_variable_definition():
    """Variable defined but not used in create should fail."""
    import copy
    data = copy.deepcopy(VALID_DATA_WITH_VARIABLES)
    data['recipes'][0]['variables']['extra_unused'] = {
        'strategy': 'literal',
        'value': 'oops',
    }
    code, out = _run_recipe_validator(data)
    assert code == 1
    assert 'unused variable definitions' in out


def test_invalid_variable_strategy():
    """Unknown strategy should fail."""
    import copy
    data = copy.deepcopy(VALID_DATA_WITH_VARIABLES)
    data['recipes'][0]['variables']['owner_email']['strategy'] = 'random'
    code, out = _run_recipe_validator(data)
    assert code == 1
    assert 'strategy must be one of' in out


def test_invalid_derived_shape():
    """Derived variable with wrong source should fail."""
    import copy
    data = copy.deepcopy(VALID_DATA_WITH_VARIABLES)
    data['recipes'][0]['variables']['owner_email']['source'] = 'userId'
    code, out = _run_recipe_validator(data)
    assert code == 1
    assert 'derived.source must be "testRunId"' in out


def test_invalid_literal_scalar():
    """Literal with non-scalar value should fail."""
    import copy
    data = copy.deepcopy(VALID_DATA_WITH_VARIABLES)
    data['recipes'][0]['create'] = {'User': [{'email': '{{owner_email}}'}]}
    data['recipes'][0]['variables'] = {
        'owner_email': {
            'strategy': 'literal',
            'value': [1, 2, 3],  # not scalar
        },
    }
    code, out = _run_recipe_validator(data)
    assert code == 1
    assert 'literal.value must be a scalar' in out


def test_rejects_unknown_model_from_discover():
    data = json.loads(_json(VALID_DATA))
    data['recipes'][0]['create'] = {'UnknownModel': [{'name': 'Acme'}]}
    code, out = _run_recipe_validator(data)
    assert code == 1
    assert 'is not present in discover schema' in out


def test_rejects_unknown_field_from_discover():
    data = json.loads(_json(VALID_DATA))
    data['recipes'][0]['create'] = {'Organization': [{'unknownField': 'Acme'}]}
    code, out = _run_recipe_validator(data)
    assert code == 1
    assert 'unknownField is not present in discover schema' in out


def test_rejects_invalid_enum_literal_from_discover():
    data = json.loads(_json(VALID_DATA))
    data['recipes'][0]['create'] = {'Organization': [{'communicationChannel': 'EMAIL'}]}
    code, out = _run_recipe_validator(data)
    assert code == 1
    assert 'invalid enum value "EMAIL"' in out


def test_rejects_non_list_value_for_list_field():
    data = json.loads(_json(VALID_DATA))
    data['recipes'][0]['create'] = {'Organization': [{'teamSlugs': 'qa-team'}]}
    code, out = _run_recipe_validator(data)
    assert code == 1
    assert 'must be a list because discover type is String[]' in out


def test_nested_tree_with_relation_fields():
    """Nested tree creates using relation field names from discover should pass."""
    discover = {
        'schema': {
            'models': [
                {
                    'name': 'Organization',
                    'fields': [
                        {'name': 'name', 'type': 'String', 'isRequired': True, 'isId': False, 'hasDefault': False},
                    ],
                },
                {
                    'name': 'User',
                    'fields': [
                        {'name': 'email', 'type': 'String', 'isRequired': True, 'isId': False, 'hasDefault': False},
                        {'name': 'name', 'type': 'String', 'isRequired': True, 'isId': False, 'hasDefault': False},
                        {'name': 'organizationId', 'type': 'String', 'isRequired': True, 'isId': False, 'hasDefault': False},
                    ],
                },
            ],
            'edges': [
                {'from': 'User', 'to': 'Organization', 'localField': 'organizationId', 'foreignField': 'id', 'nullable': False},
            ],
            'relations': [
                {'parentModel': 'Organization', 'childModel': 'User', 'parentField': 'users', 'childField': 'organizationId'},
            ],
            'scopeField': 'organizationId',
        }
    }
    data = {
        'version': 1,
        'source': {'discoverPath': 'autonoma/discover.json', 'scenariosPath': 'autonoma/scenarios.md'},
        'validationMode': 'sdk-check',
        'recipes': [
            {
                'name': 'standard', 'description': 'Nested tree',
                'create': {
                    'Organization': [{
                        'name': 'Acme',
                        'users': [{'name': 'Alice', 'email': 'alice@test.com'}],
                    }],
                },
                'validation': {'status': 'validated', 'method': 'checkScenario', 'phase': 'ok'},
            },
            {
                'name': 'empty', 'description': 'Empty',
                'create': {'Organization': []},
                'validation': {'status': 'validated', 'method': 'checkScenario', 'phase': 'ok'},
            },
            {
                'name': 'large', 'description': 'Large',
                'create': {'Organization': [{'name': 'Big'}]},
                'validation': {'status': 'validated', 'method': 'checkScenario', 'phase': 'ok'},
            },
        ],
    }
    code, out = _run_recipe_validator(data, discover=discover)
    assert code == 0
    assert out == 'OK'
