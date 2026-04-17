"""Tests for validate_sdk_integration.py."""
import json

from conftest import run_validator


SCRIPT = "validate_sdk_integration.py"


def valid_payload(**overrides):
    payload = {
        "status": "ok",
        "endpointUrl": "http://127.0.0.1:3000/api/autonoma",
        "endpointPath": "/api/autonoma",
        "stack": {
            "language": "TypeScript",
            "framework": "Express",
            "orm": "Prisma",
            "packageManager": "pnpm",
        },
        "packagesInstalled": ["@autonoma-ai/sdk", "@autonoma-ai/sdk-prisma"],
        "sharedSecretPresent": True,
        "signingSecretPresent": True,
        "devServer": {"startedByPlugin": True, "pid": 1234},
        "verification": {
            "discover": {"status": "ok", "validatedByPlugin": True},
            "up": {"status": "ok"},
            "down": {"status": "ok"},
        },
        "branch": {"name": "autonoma/feat-autonoma-sdk"},
        "pr": {"url": "https://github.com/example/repo/pull/1"},
        "blockingIssues": [],
    }
    payload.update(overrides)
    return payload


def test_accepts_valid_payload():
    code, out = run_validator(SCRIPT, json.dumps(valid_payload()), filename=".sdk-integration.json")
    assert code == 0
    assert out == "OK"


def test_rejects_missing_required_field():
    payload = valid_payload()
    payload.pop("verification")
    code, out = run_validator(SCRIPT, json.dumps(payload), filename=".sdk-integration.json")
    assert code == 1
    assert "Missing required fields" in out


def test_rejects_invalid_endpoint_url():
    code, out = run_validator(
        SCRIPT,
        json.dumps(valid_payload(endpointUrl="/api/autonoma")),
        filename=".sdk-integration.json",
    )
    assert code == 1
    assert "absolute http/https URL" in out


def test_accepts_failed_status_with_blocking_issues():
    code, out = run_validator(
        SCRIPT,
        json.dumps(
            valid_payload(
                status="failed",
                verification={
                    "discover": {"status": "failed", "validatedByPlugin": False},
                    "up": {"status": "failed"},
                    "down": {"status": "failed"},
                },
                blockingIssues=["discover request failed"],
            )
        ),
        filename=".sdk-integration.json",
    )
    assert code == 0
    assert out == "OK"
