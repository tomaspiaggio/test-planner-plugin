"""Tests for validate_scenario_validation.py."""
import json

from conftest import run_validator


SCRIPT = "validate_scenario_validation.py"


def valid_payload(**overrides):
    payload = {
        "status": "ok",
        "preflightPassed": True,
        "smokeTestPassed": True,
        "validatedScenarios": ["standard", "empty", "large"],
        "failedScenarios": [],
        "blockingIssues": [],
        "recipePath": "autonoma/scenario-recipes.json",
        "validationMode": "sdk-check",
        "endpointUrl": "http://127.0.0.1:3000/api/autonoma",
    }
    payload.update(overrides)
    return payload


def test_accepts_valid_payload():
    code, out = run_validator(SCRIPT, json.dumps(valid_payload()), filename=".scenario-validation.json")
    assert code == 0
    assert out == "OK"


def test_accepts_failed_status_payload():
    code, out = run_validator(
        SCRIPT,
        json.dumps(
            valid_payload(
                status="failed",
                preflightPassed=False,
                validatedScenarios=["standard"],
                failedScenarios=["empty", "large"],
                blockingIssues=["duplicate email"],
            )
        ),
        filename=".scenario-validation.json",
    )
    assert code == 0
    assert out == "OK"


def test_rejects_missing_required_field():
    payload = valid_payload()
    payload.pop("recipePath")
    code, out = run_validator(SCRIPT, json.dumps(payload), filename=".scenario-validation.json")
    assert code == 1
    assert "Missing required fields" in out


def test_rejects_invalid_endpoint_url():
    code, out = run_validator(
        SCRIPT,
        json.dumps(valid_payload(endpointUrl="relative/path")),
        filename=".scenario-validation.json",
    )
    assert code == 1
    assert "absolute http/https URL" in out
