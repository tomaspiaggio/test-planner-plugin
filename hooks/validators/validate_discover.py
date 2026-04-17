#!/usr/bin/env python3
"""Validates autonoma/discover.json structure."""
import json
import re
import sys


TYPE_PATTERN = re.compile(r"^(?:[A-Za-z][A-Za-z0-9_]*|enum\([^()]+\))(?:\[\])?$")


filepath = sys.argv[1]

try:
    with open(filepath) as fh:
        payload = json.load(fh)
except Exception as e:
    print(f'Invalid JSON: {e}')
    sys.exit(1)

if not isinstance(payload, dict):
    print('discover.json must contain a JSON object')
    sys.exit(1)

schema = payload.get('schema')
if not isinstance(schema, dict):
    print('discover.json must contain a "schema" object')
    sys.exit(1)

required_schema_fields = ['models', 'edges', 'relations', 'scopeField']
missing = [f for f in required_schema_fields if f not in schema]
if missing:
    print(f'schema is missing required fields: {missing}')
    sys.exit(1)

models = schema.get('models')
if not isinstance(models, list) or len(models) == 0:
    print('schema.models must be a non-empty list')
    sys.exit(1)

for i, model in enumerate(models):
    if not isinstance(model, dict):
        print(f'schema.models[{i}] must be an object')
        sys.exit(1)
    if not isinstance(model.get('name'), str) or not model.get('name', '').strip():
        print(f'schema.models[{i}].name must be a non-empty string')
        sys.exit(1)
    fields = model.get('fields')
    if not isinstance(fields, list):
        print(f'schema.models[{i}].fields must be a list')
        sys.exit(1)
    for j, field in enumerate(fields):
        if not isinstance(field, dict):
            print(f'schema.models[{i}].fields[{j}] must be an object')
            sys.exit(1)
        for key in ['name', 'type', 'isRequired', 'isId', 'hasDefault']:
            if key not in field:
                print(f'schema.models[{i}].fields[{j}] missing required field: {key}')
                sys.exit(1)
        field_type = field.get('type')
        if not isinstance(field_type, str) or len(field_type.strip()) == 0:
            print(f'schema.models[{i}].fields[{j}].type must be a non-empty string')
            sys.exit(1)
        if TYPE_PATTERN.match(field_type.strip()) is None:
            print(
                f'schema.models[{i}].fields[{j}].type must use a supported type format, got: {field_type}'
            )
            sys.exit(1)

edges = schema.get('edges')
if not isinstance(edges, list):
    print('schema.edges must be a list')
    sys.exit(1)

for i, edge in enumerate(edges):
    if not isinstance(edge, dict):
        print(f'schema.edges[{i}] must be an object')
        sys.exit(1)
    for key in ['from', 'to', 'localField', 'foreignField', 'nullable']:
        if key not in edge:
            print(f'schema.edges[{i}] missing required field: {key}')
            sys.exit(1)

relations = schema.get('relations')
if not isinstance(relations, list):
    print('schema.relations must be a list')
    sys.exit(1)

for i, relation in enumerate(relations):
    if not isinstance(relation, dict):
        print(f'schema.relations[{i}] must be an object')
        sys.exit(1)
    for key in ['parentModel', 'childModel', 'parentField', 'childField']:
        if key not in relation:
            print(f'schema.relations[{i}] missing required field: {key}')
            sys.exit(1)

scope_field = schema.get('scopeField')
if not isinstance(scope_field, str) or len(scope_field.strip()) == 0:
    print('schema.scopeField must be a non-empty string')
    sys.exit(1)

print('OK')
