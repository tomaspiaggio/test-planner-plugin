#!/usr/bin/env python3
"""Validates entity-audit.md frontmatter format."""
import sys
import yaml

filepath = sys.argv[1]
content = open(filepath).read()

if not content.startswith('---'):
    print('File must start with YAML frontmatter (---)')
    sys.exit(1)

parts = content.split('---', 2)
if len(parts) < 3:
    print('Missing closing --- for frontmatter')
    sys.exit(1)

try:
    fm = yaml.safe_load(parts[1])
except Exception as e:
    print(f'Invalid YAML in frontmatter: {e}')
    sys.exit(1)

if not isinstance(fm, dict):
    print('Frontmatter must be a YAML mapping')
    sys.exit(1)

# Required top-level fields
required = ['model_count', 'factory_count', 'models']
missing = [f for f in required if f not in fm]
if missing:
    print(f'Missing required frontmatter fields: {missing}')
    sys.exit(1)

# Validate counts are non-negative integers
for count_field in ['model_count', 'factory_count']:
    val = fm.get(count_field)
    if not isinstance(val, int) or val < 0:
        print(f'{count_field} must be a non-negative integer')
        sys.exit(1)

if fm['model_count'] < 1:
    print('model_count must be at least 1 — no models were audited')
    sys.exit(1)

# Validate models array
models = fm.get('models')
if not isinstance(models, list) or len(models) == 0:
    print('models must be a non-empty list')
    sys.exit(1)

if len(models) != fm['model_count']:
    print(f'model_count ({fm["model_count"]}) does not match models array length ({len(models)})')
    sys.exit(1)

factory_count = 0
for i, model in enumerate(models):
    if not isinstance(model, dict):
        print(f'models[{i}] must be a mapping')
        sys.exit(1)

    # Every model needs name and needs_factory
    for field in ['name', 'needs_factory']:
        if field not in model:
            print(f'models[{i}] missing required field: {field}')
            sys.exit(1)

    if not isinstance(model['name'], str) or len(model['name'].strip()) == 0:
        print(f'models[{i}].name must be a non-empty string')
        sys.exit(1)

    if not isinstance(model['needs_factory'], bool):
        print(f'models[{i}].needs_factory must be a boolean (true/false)')
        sys.exit(1)

    # Every model needs a reason
    if 'reason' not in model or not isinstance(model.get('reason'), str):
        print(f'models[{i}] ({model["name"]}) missing required field: reason (string)')
        sys.exit(1)

    if model['needs_factory']:
        factory_count += 1

        # Models needing factories must have creation_file and side_effects
        if 'creation_file' not in model or not isinstance(model.get('creation_file'), str):
            print(f'models[{i}] ({model["name"]}) needs_factory=true but missing creation_file')
            sys.exit(1)

        if 'side_effects' not in model:
            print(f'models[{i}] ({model["name"]}) needs_factory=true but missing side_effects')
            sys.exit(1)

        effects = model['side_effects']
        if not isinstance(effects, list) or len(effects) == 0:
            print(f'models[{i}] ({model["name"]}) side_effects must be a non-empty list when needs_factory=true')
            sys.exit(1)

if factory_count != fm['factory_count']:
    print(f'factory_count ({fm["factory_count"]}) does not match actual factories in models ({factory_count})')
    sys.exit(1)

print('OK')
