#!/usr/bin/env python3
"""Validates entity-audit.md frontmatter format.

Supports two schemas:

- v2 (current): each model has `independently_created: bool` and
  `created_by: [{owner, via, why}]`. When `independently_created: true` the
  entry must also have `creation_file`, `creation_function`, and optionally
  `side_effects`. Dependents (`independently_created: false`) must have a
  non-empty `created_by` pointing at a model that exists in the audit.

- v1 (legacy): each model has `has_creation_code: bool`. We still accept it
  and translate on read (see _audit_schema.py). v1 audits cannot express
  `created_by`, so the dependent-has-owner invariant is vacuously satisfied.
"""
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

required = ['model_count', 'factory_count', 'models']
missing = [f for f in required if f not in fm]
if missing:
    print(f'Missing required frontmatter fields: {missing}')
    sys.exit(1)

for count_field in ['model_count', 'factory_count']:
    val = fm.get(count_field)
    if not isinstance(val, int) or val < 0:
        print(f'{count_field} must be a non-negative integer')
        sys.exit(1)

if fm['model_count'] < 1:
    print('model_count must be at least 1 — no models were audited')
    sys.exit(1)

models = fm.get('models')
if not isinstance(models, list) or len(models) == 0:
    print('models must be a non-empty list')
    sys.exit(1)

if len(models) != fm['model_count']:
    print(f'model_count ({fm["model_count"]}) does not match models array length ({len(models)})')
    sys.exit(1)


def is_indep(model):
    if 'independently_created' in model:
        return bool(model['independently_created'])
    return bool(model.get('has_creation_code'))


# First pass: sanity + collect names for cross-reference
names = set()
for i, model in enumerate(models):
    if not isinstance(model, dict):
        print(f'models[{i}] must be a mapping')
        sys.exit(1)
    if 'name' not in model or not isinstance(model['name'], str) or not model['name'].strip():
        print(f'models[{i}].name must be a non-empty string')
        sys.exit(1)
    names.add(model['name'])

# Second pass: schema checks per model
factory_count = 0
for i, model in enumerate(models):
    name = model['name']
    has_v2 = 'independently_created' in model
    has_v1 = 'has_creation_code' in model
    if not has_v2 and not has_v1:
        print(f'models[{i}] ({name}) missing classification (independently_created or has_creation_code)')
        sys.exit(1)
    if has_v2 and not isinstance(model['independently_created'], bool):
        print(f'models[{i}] ({name}).independently_created must be a boolean')
        sys.exit(1)
    if has_v1 and not isinstance(model['has_creation_code'], bool):
        print(f'models[{i}] ({name}).has_creation_code must be a boolean')
        sys.exit(1)

    indep = is_indep(model)

    if indep:
        factory_count += 1
        if 'creation_file' not in model or not isinstance(model.get('creation_file'), str):
            print(f'models[{i}] ({name}) independently_created=true but missing creation_file')
            sys.exit(1)
        if 'creation_function' not in model or not isinstance(model.get('creation_function'), str):
            print(f'models[{i}] ({name}) independently_created=true but missing creation_function')
            sys.exit(1)
        if 'side_effects' in model and not isinstance(model['side_effects'], list):
            print(f'models[{i}] ({name}) side_effects must be a list when present')
            sys.exit(1)

    # created_by invariants (v2 only — v1 has no such field)
    cb = model.get('created_by')
    if cb is None:
        # v1 audits don't have it; v2 requires it (empty allowed for roots)
        if has_v2:
            print(f'models[{i}] ({name}) missing required field: created_by (list, may be empty)')
            sys.exit(1)
        continue

    if not isinstance(cb, list):
        print(f'models[{i}] ({name}).created_by must be a list')
        sys.exit(1)

    if not indep and len(cb) == 0:
        print(
            f'models[{i}] ({name}) is marked independently_created=false but has no '
            'created_by entries. Every dependent must have at least one owner — '
            'either find the creation path, or mark the model independently_created=true.'
        )
        sys.exit(1)

    for j, owner_entry in enumerate(cb):
        if not isinstance(owner_entry, dict):
            print(f'models[{i}] ({name}).created_by[{j}] must be a mapping')
            sys.exit(1)
        for req in ('owner', 'via', 'why'):
            val = owner_entry.get(req)
            if not isinstance(val, str) or not val.strip():
                print(
                    f'models[{i}] ({name}).created_by[{j}].{req} must be a non-empty string'
                )
                sys.exit(1)
        if owner_entry['owner'] not in names:
            print(
                f'models[{i}] ({name}).created_by[{j}].owner={owner_entry["owner"]!r} '
                f'does not match any model in the audit. Check the owner name or add the owner model.'
            )
            sys.exit(1)
        if owner_entry['owner'] == name:
            print(f'models[{i}] ({name}).created_by[{j}].owner cannot be the model itself')
            sys.exit(1)

if factory_count != fm['factory_count']:
    print(
        f'factory_count ({fm["factory_count"]}) does not match actual independently_created '
        f'models ({factory_count})'
    )
    sys.exit(1)

print('OK')
