"""Tests for validate_discover.py."""
from conftest import run_validator

SCRIPT = 'validate_discover.py'

VALID = """\
{
  "schema": {
    "models": [
      {
        "name": "Organization",
        "fields": [
          {
            "name": "id",
            "type": "String",
            "isRequired": true,
            "isId": true,
            "hasDefault": true
          }
        ]
      }
    ],
    "edges": [
      {
        "from": "User",
        "to": "Organization",
        "localField": "organizationId",
        "foreignField": "id",
        "nullable": false
      }
    ],
    "relations": [
      {
        "parentModel": "Organization",
        "childModel": "User",
        "parentField": "users",
        "childField": "organizationId"
      }
    ],
    "scopeField": "organizationId"
  }
}
"""


def test_valid_discover():
    code, out = run_validator(SCRIPT, VALID, filename='discover.json')
    assert code == 0
    assert out == 'OK'


def test_invalid_json():
    code, out = run_validator(SCRIPT, '{not-json', filename='discover.json')
    assert code == 1
    assert 'Invalid JSON' in out


def test_missing_schema():
    code, out = run_validator(SCRIPT, '{}', filename='discover.json')
    assert code == 1
    assert 'must contain a "schema" object' in out


def test_missing_scope_field():
    content = VALID.replace('    "scopeField": "organizationId"\n', '')
    content = content.replace('    ],\n  }\n}\n', '    ]\n  }\n}\n')
    code, out = run_validator(SCRIPT, content, filename='discover.json')
    assert code == 1
    assert 'schema is missing required fields' in out


def test_model_requires_fields():
    content = VALID.replace('"fields": [', '"oops": [')
    code, out = run_validator(SCRIPT, content, filename='discover.json')
    assert code == 1
    assert 'fields must be a list' in out


def test_accepts_enum_and_list_type_formats():
    content = VALID.replace(
        '"type": "String"',
        '"type": "enum(slack)"',
        1,
    ).replace(
        '"hasDefault": true',
        '"hasDefault": true\n          },\n          {\n            "name": "teamSlugs",\n            "type": "String[]",\n            "isRequired": true,\n            "isId": false,\n            "hasDefault": true',
        1,
    )
    code, out = run_validator(SCRIPT, content, filename='discover.json')
    assert code == 0
    assert out == 'OK'


def test_rejects_unsupported_type_format():
    content = VALID.replace('"type": "String"', '"type": "enum(slack"', 1)
    code, out = run_validator(SCRIPT, content, filename='discover.json')
    assert code == 1
    assert 'must use a supported type format' in out
