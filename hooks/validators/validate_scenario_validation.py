#!/usr/bin/env python3
"""Validates autonoma/.scenario-validation.json."""
import json
import sys
from urllib.parse import urlparse


filepath = sys.argv[1]


def fail(message: str) -> None:
    print(message)
    sys.exit(1)


try:
    with open(filepath) as fh:
        payload = json.load(fh)
except Exception as exc:
    fail(f"Invalid JSON: {exc}")

if not isinstance(payload, dict):
    fail("Root must be a JSON object")

required = [
    "status",
    "preflightPassed",
    "smokeTestPassed",
    "validatedScenarios",
    "failedScenarios",
    "blockingIssues",
    "recipePath",
    "validationMode",
    "endpointUrl",
]
missing = [field for field in required if field not in payload]
if missing:
    fail(f"Missing required fields: {missing}")

if payload.get("status") not in {"ok", "failed"}:
    fail('status must be "ok" or "failed"')

for field in ["preflightPassed", "smokeTestPassed"]:
    if not isinstance(payload.get(field), bool):
        fail(f"{field} must be a boolean")

for field in ["validatedScenarios", "failedScenarios", "blockingIssues"]:
    value = payload.get(field)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        fail(f"{field} must be a list of strings")

recipe_path = payload.get("recipePath")
if not isinstance(recipe_path, str) or not recipe_path.strip():
    fail("recipePath must be a non-empty string")

validation_mode = payload.get("validationMode")
if validation_mode not in {"sdk-check", "endpoint-lifecycle"}:
    fail('validationMode must be "sdk-check" or "endpoint-lifecycle"')

endpoint_url = payload.get("endpointUrl")
if not isinstance(endpoint_url, str) or not endpoint_url.strip():
    fail("endpointUrl must be a non-empty string")
parsed = urlparse(endpoint_url)
if parsed.scheme not in {"http", "https"} or not parsed.netloc:
    fail("endpointUrl must be an absolute http/https URL")

print("OK")
