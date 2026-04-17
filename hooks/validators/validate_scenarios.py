#!/usr/bin/env python3
"""Validates scenarios.md frontmatter format."""
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

# Required fields
required = ['scenario_count', 'scenarios', 'entity_types']
missing = [f for f in required if f not in fm]
if missing:
    print(f'Missing required frontmatter fields: {missing}')
    sys.exit(1)

# Validate scenario_count
sc = fm.get('scenario_count')
if not isinstance(sc, int) or sc < 3:
    print('scenario_count must be an integer >= 3')
    sys.exit(1)

# Validate scenarios list
scenarios = fm.get('scenarios')
if not isinstance(scenarios, list) or len(scenarios) != sc:
    print(f'scenarios list length ({len(scenarios) if isinstance(scenarios, list) else "N/A"}) must match scenario_count ({sc})')
    sys.exit(1)

required_scenario_names = {'standard', 'empty', 'large'}
found_names = set()

for i, s in enumerate(scenarios):
    if not isinstance(s, dict):
        print(f'scenarios[{i}] must be a mapping')
        sys.exit(1)
    for field in ['name', 'description', 'entity_types', 'total_entities']:
        if field not in s:
            print(f'scenarios[{i}] missing required field: {field}')
            sys.exit(1)
    found_names.add(s['name'])

missing_names = required_scenario_names - found_names
if missing_names:
    print(f'Missing required scenarios: {missing_names}')
    sys.exit(1)

# Validate entity_types
et = fm.get('entity_types')
if not isinstance(et, list) or len(et) == 0:
    print('entity_types must be a non-empty list')
    sys.exit(1)

for i, e in enumerate(et):
    if not isinstance(e, dict) or 'name' not in e:
        print(f'entity_types[{i}] must be a mapping with at least a "name" field')
        sys.exit(1)

# Validate variable_fields (required, may be empty list)
if 'variable_fields' not in fm:
    print('Missing required frontmatter field: variable_fields (use [] if none)')
    sys.exit(1)

scenario_name_set = {s['name'] for s in scenarios}
variable_fields = fm.get('variable_fields')
if not isinstance(variable_fields, list):
    print('variable_fields must be a list')
    sys.exit(1)

for i, variable in enumerate(variable_fields):
    if not isinstance(variable, dict):
        print(f'variable_fields[{i}] must be a mapping')
        sys.exit(1)
    for field in ['token', 'entity', 'scenarios', 'reason', 'test_reference']:
        if field not in variable:
            print(f'variable_fields[{i}] missing required field: {field}')
            sys.exit(1)

    token = variable.get('token')
    if not isinstance(token, str) or len(token) < 5 or not token.startswith('{{') or not token.endswith('}}'):
        print(f'variable_fields[{i}].token must use double curly braces, e.g. {{title}}')
        sys.exit(1)

    for field in ['entity', 'reason', 'test_reference']:
        value = variable.get(field)
        if not isinstance(value, str) or len(value.strip()) == 0:
            print(f'variable_fields[{i}].{field} must be a non-empty string')
            sys.exit(1)

    vscenarios = variable.get('scenarios')
    if not isinstance(vscenarios, list) or len(vscenarios) == 0:
        print(f'variable_fields[{i}].scenarios must be a non-empty list')
        sys.exit(1)
    for name in vscenarios:
        if name not in scenario_name_set:
            print(f'variable_fields[{i}].scenarios references unknown scenario: {name}')
            sys.exit(1)

# Validate planning_sections (required; must contain the four core sections)
if 'planning_sections' not in fm:
    print('Missing required frontmatter field: planning_sections')
    sys.exit(1)

planning = fm.get('planning_sections')
if not isinstance(planning, list) or len(planning) == 0:
    print('planning_sections must be a non-empty list')
    sys.exit(1)

required_sections = {'schema_summary', 'relationship_map', 'variable_data_strategy'}
missing_sections = required_sections - set(planning)
if missing_sections:
    print(f'planning_sections missing required entries: {sorted(missing_sections)}')
    sys.exit(1)

print('OK')
