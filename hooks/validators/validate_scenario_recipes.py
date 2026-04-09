#!/usr/bin/env python3
"""Validates autonoma/scenario-recipes.json schema."""
import json
import re
import sys
from pathlib import Path


TYPE_PATTERN = re.compile(r"^(?:[A-Za-z][A-Za-z0-9_]*|enum\([^()]+\))(?:\[\])?$")
TOKEN_OR_REF_PATTERN = re.compile(r"^(?:\{\{\w+\}\}|_ref:.+)$")


def _parse_type(type_name):
    if not isinstance(type_name, str):
        return None

    is_list = type_name.endswith('[]')
    base = type_name[:-2] if is_list else type_name
    if not TYPE_PATTERN.match(type_name):
        return None

    if base.startswith('enum(') and base.endswith(')'):
        values = [value.strip() for value in base[5:-1].split(',') if value.strip()]
        return {'kind': 'enum', 'values': values, 'is_list': is_list}

    return {'kind': 'scalar', 'name': base, 'is_list': is_list}


def _resolve_source_path(filepath, source_path):
    recipe_dir = Path(filepath).resolve().parent
    raw_path = Path(source_path)

    if raw_path.is_absolute():
        return raw_path

    for base_dir in (recipe_dir, *recipe_dir.parents):
        candidate = (base_dir / source_path).resolve()
        if candidate.is_file():
            return candidate

    return (recipe_dir / source_path).resolve()


def _load_discover_schema(filepath, source):
    if not isinstance(source, dict):
        return None, None

    discover_path = source.get('discoverPath')
    if not isinstance(discover_path, str) or len(discover_path.strip()) == 0:
        return None, None

    resolved_path = _resolve_source_path(filepath, discover_path)
    if not resolved_path.is_file():
        return None, f'source.discoverPath does not exist: {discover_path}'

    try:
        with open(resolved_path) as fh:
            payload = json.load(fh)
    except Exception as exc:
        return None, f'source.discoverPath is not valid JSON: {exc}'

    schema = payload.get('schema')
    if not isinstance(schema, dict):
        return None, 'source.discoverPath must point to a discover file with a "schema" object'

    models = schema.get('models')
    if not isinstance(models, list):
        return None, 'source.discoverPath schema.models must be a list'

    model_map = {}
    for model in models:
        if not isinstance(model, dict):
            continue
        name = model.get('name')
        fields = model.get('fields')
        if not isinstance(name, str) or not isinstance(fields, list):
            continue
        field_map = {}
        for field in fields:
            if not isinstance(field, dict):
                continue
            field_name = field.get('name')
            field_type = field.get('type')
            if isinstance(field_name, str) and isinstance(field_type, str):
                field_map[field_name] = field
        model_map[name] = field_map

    # Collect relation field names used as nesting keys in nested tree create payloads
    relation_fields = set()
    relations = schema.get('relations')
    if isinstance(relations, list):
        for rel in relations:
            if isinstance(rel, dict) and isinstance(rel.get('parentField'), str):
                relation_fields.add(rel['parentField'])

    return {'models': model_map, 'relation_fields': relation_fields}, None


def _validate_value_against_field(value, field, path):
    parsed_type = _parse_type(field.get('type'))
    if parsed_type is None:
        return f'{path} has unsupported discover type: {field.get("type")}'

    if isinstance(value, str) and TOKEN_OR_REF_PATTERN.match(value):
        return None

    if parsed_type['is_list']:
        if not isinstance(value, list):
            return f'{path} must be a list because discover type is {field.get("type")}'
        return None

    if isinstance(value, list):
        return f'{path} must not be a list because discover type is {field.get("type")}'

    if parsed_type['kind'] == 'enum' and isinstance(value, str):
        if value not in parsed_type['values']:
            return (
                f'{path} has invalid enum value "{value}". '
                f'Expected one of {parsed_type["values"]}'
            )

    return None


def _validate_create_against_discover(create, discover_info, recipe_index):
    if discover_info is None:
        return None

    model_map = discover_info['models']
    relation_fields = discover_info['relation_fields']

    for model_name, entities in create.items():
        if model_name not in model_map:
            return f'recipes[{recipe_index}].create.{model_name} is not present in discover schema'
        if not isinstance(entities, list):
            return f'recipes[{recipe_index}].create.{model_name} must be an array'

        field_map = model_map[model_name]
        for entity_index, entity in enumerate(entities):
            if not isinstance(entity, dict):
                return f'recipes[{recipe_index}].create.{model_name}[{entity_index}] must be an object'
            for field_name, value in entity.items():
                if field_name.startswith('_'):
                    continue
                # Skip relation nesting keys (e.g. userses, projectses)
                if field_name in relation_fields:
                    continue
                if field_name not in field_map:
                    return (
                        f'recipes[{recipe_index}].create.{model_name}[{entity_index}].{field_name} '
                        'is not present in discover schema'
                    )
                error = _validate_value_against_field(
                    value,
                    field_map[field_name],
                    f'recipes[{recipe_index}].create.{model_name}[{entity_index}].{field_name}',
                )
                if error is not None:
                    return error

    return None

filepath = sys.argv[1]

try:
    data = json.load(open(filepath))
except Exception as e:
    print(f'Invalid JSON: {e}')
    sys.exit(1)

if not isinstance(data, dict):
    print('Root must be a JSON object')
    sys.exit(1)

required = ['version', 'source', 'validationMode', 'recipes']
missing = [f for f in required if f not in data]
if missing:
    print(f'Missing required fields: {missing}')
    sys.exit(1)

version = data.get('version')
if version != 1:
    print('version must be exactly 1')
    sys.exit(1)

source = data.get('source')
if not isinstance(source, dict):
    print('source must be an object')
    sys.exit(1)

for field in ['discoverPath', 'scenariosPath']:
    value = source.get(field)
    if not isinstance(value, str) or len(value.strip()) == 0:
        print(f'source.{field} must be a non-empty string')
        sys.exit(1)

discover_info, discover_error = _load_discover_schema(filepath, source)
if discover_error is not None:
    print(discover_error)
    sys.exit(1)

validation_mode = data.get('validationMode')
valid_modes = {'sdk-check', 'endpoint-lifecycle'}
if validation_mode not in valid_modes:
    print(f'validationMode must be one of {valid_modes}, got: {validation_mode}')
    sys.exit(1)

recipes = data.get('recipes')
if not isinstance(recipes, list) or len(recipes) < 3:
    print('recipes must be an array with at least 3 entries')
    sys.exit(1)

required_names = {'standard', 'empty', 'large'}
found_names = set()

for i, recipe in enumerate(recipes):
    if not isinstance(recipe, dict):
        print(f'recipes[{i}] must be an object')
        sys.exit(1)

    for field in ['name', 'description', 'create', 'validation']:
        if field not in recipe:
            print(f'recipes[{i}] missing required field: {field}')
            sys.exit(1)

    name = recipe.get('name')
    if not isinstance(name, str) or len(name.strip()) == 0:
        print(f'recipes[{i}].name must be a non-empty string')
        sys.exit(1)
    found_names.add(name)

    description = recipe.get('description')
    if not isinstance(description, str) or len(description.strip()) == 0:
        print(f'recipes[{i}].description must be a non-empty string')
        sys.exit(1)

    create = recipe.get('create')
    if not isinstance(create, dict) or len(create) == 0:
        print(f'recipes[{i}].create must be a non-empty object')
        sys.exit(1)
    create_error = _validate_create_against_discover(create, discover_info, i)
    if create_error is not None:
        print(create_error)
        sys.exit(1)

    validation = recipe.get('validation')
    if not isinstance(validation, dict):
        print(f'recipes[{i}].validation must be an object')
        sys.exit(1)

    for field in ['status', 'method', 'phase']:
        if field not in validation:
            print(f'recipes[{i}].validation missing required field: {field}')
            sys.exit(1)

    if validation.get('status') != 'validated':
        print(f'recipes[{i}].validation.status must be exactly "validated"')
        sys.exit(1)

    if validation.get('phase') != 'ok':
        print(f'recipes[{i}].validation.phase must be exactly "ok"')
        sys.exit(1)

    method = validation.get('method')
    valid_methods = {'checkScenario', 'checkAllScenarios', 'endpoint-up-down'}
    if method not in valid_methods:
        print(f'recipes[{i}].validation.method must be one of {valid_methods}, got: {method}')
        sys.exit(1)

    for field in ['up_ms', 'down_ms']:
        if field in validation:
            value = validation.get(field)
            if not isinstance(value, int) or value < 0:
                print(f'recipes[{i}].validation.{field} must be a non-negative integer')
                sys.exit(1)

    # --- variables validation (optional) ---
    variables = recipe.get('variables')
    if variables is not None:
        if not isinstance(variables, dict):
            print(f'recipes[{i}].variables must be an object')
            sys.exit(1)

        # Find all tokens used in create
        def _find_tokens(obj):
            tokens = set()
            if isinstance(obj, str):
                tokens.update(re.findall(r'\{\{(\w+)\}\}', obj))
            elif isinstance(obj, list):
                for item in obj:
                    tokens.update(_find_tokens(item))
            elif isinstance(obj, dict):
                for v in obj.values():
                    tokens.update(_find_tokens(v))
            return tokens

        tokens_in_create = _find_tokens(create)
        var_keys = set(variables.keys())

        missing_vars = tokens_in_create - var_keys
        if missing_vars:
            print(f'recipes[{i}]: tokens without variable definitions: {sorted(missing_vars)}')
            sys.exit(1)

        unused_vars = var_keys - tokens_in_create
        if unused_vars:
            print(f'recipes[{i}]: unused variable definitions: {sorted(unused_vars)}')
            sys.exit(1)

        allowed_strategies = {'literal', 'derived', 'faker'}
        for var_name, var_def in variables.items():
            if not isinstance(var_def, dict):
                print(f'recipes[{i}].variables.{var_name} must be an object')
                sys.exit(1)
            strategy = var_def.get('strategy')
            if strategy not in allowed_strategies:
                print(f'recipes[{i}].variables.{var_name}.strategy must be one of {allowed_strategies}, got: {strategy}')
                sys.exit(1)
            if strategy == 'literal':
                if 'value' not in var_def:
                    print(f'recipes[{i}].variables.{var_name}: literal must have "value"')
                    sys.exit(1)
                val = var_def['value']
                if not isinstance(val, (str, int, float, bool)) and val is not None:
                    print(f'recipes[{i}].variables.{var_name}: literal.value must be a scalar')
                    sys.exit(1)
            elif strategy == 'derived':
                if var_def.get('source') != 'testRunId':
                    print(f'recipes[{i}].variables.{var_name}: derived.source must be "testRunId"')
                    sys.exit(1)
                fmt = var_def.get('format')
                if not isinstance(fmt, str) or len(fmt.strip()) == 0:
                    print(f'recipes[{i}].variables.{var_name}: derived.format must be a non-empty string')
                    sys.exit(1)
            elif strategy == 'faker':
                gen = var_def.get('generator')
                if not isinstance(gen, str) or len(gen.strip()) == 0:
                    print(f'recipes[{i}].variables.{var_name}: faker.generator must be a non-empty string')
                    sys.exit(1)

missing_names = required_names - found_names
if missing_names:
    print(f'Missing required recipes: {missing_names}')
    sys.exit(1)

print('OK')
