#!/usr/bin/env python3
"""Validates autonoma/.sdk-integration.json."""
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
    "endpointUrl",
    "endpointPath",
    "stack",
    "packagesInstalled",
    "sharedSecretPresent",
    "signingSecretPresent",
    "devServer",
    "verification",
    "branch",
    "blockingIssues",
]
missing = [field for field in required if field not in payload]
if missing:
    fail(f"Missing required fields: {missing}")

status = payload.get("status")
if status not in {"ok", "failed"}:
    fail('status must be "ok" or "failed"')

endpoint_url = payload.get("endpointUrl")
if not isinstance(endpoint_url, str) or not endpoint_url.strip():
    fail("endpointUrl must be a non-empty string")
parsed = urlparse(endpoint_url)
if parsed.scheme not in {"http", "https"} or not parsed.netloc:
    fail("endpointUrl must be an absolute http/https URL")

endpoint_path = payload.get("endpointPath")
if not isinstance(endpoint_path, str) or not endpoint_path.strip():
    fail("endpointPath must be a non-empty string")

stack = payload.get("stack")
if not isinstance(stack, dict):
    fail("stack must be an object")
for field in ["language", "framework", "orm", "packageManager"]:
    if field not in stack:
        fail(f"stack.{field} is required")
    if stack[field] is not None and not isinstance(stack[field], str):
        fail(f"stack.{field} must be a string or null")

packages = payload.get("packagesInstalled")
if not isinstance(packages, list) or not all(isinstance(item, str) and item.strip() for item in packages):
    fail("packagesInstalled must be a list of non-empty strings")

for field in ["sharedSecretPresent", "signingSecretPresent"]:
    if not isinstance(payload.get(field), bool):
        fail(f"{field} must be a boolean")

dev_server = payload.get("devServer")
if not isinstance(dev_server, dict):
    fail("devServer must be an object")
if not isinstance(dev_server.get("startedByPlugin"), bool):
    fail("devServer.startedByPlugin must be a boolean")
pid = dev_server.get("pid")
if pid is not None and not isinstance(pid, int):
    fail("devServer.pid must be an integer or null")

verification = payload.get("verification")
if not isinstance(verification, dict):
    fail("verification must be an object")
for key in ["discover", "up", "down"]:
    section = verification.get(key)
    if not isinstance(section, dict):
        fail(f"verification.{key} must be an object")
    if section.get("status") not in {"ok", "failed"}:
        fail(f'verification.{key}.status must be "ok" or "failed"')

if not isinstance(verification.get("discover", {}).get("validatedByPlugin"), bool):
    fail("verification.discover.validatedByPlugin must be a boolean")

branch = payload.get("branch")
if not isinstance(branch, dict) or not isinstance(branch.get("name"), str) or not branch.get("name", "").strip():
    fail("branch.name must be a non-empty string")

pr = payload.get("pr")
if pr is not None:
    if not isinstance(pr, dict):
        fail("pr must be an object or null")
    url = pr.get("url")
    if url is not None:
        if not isinstance(url, str) or not url.strip():
            fail("pr.url must be a non-empty string or null")

blocking = payload.get("blockingIssues")
if not isinstance(blocking, list) or not all(isinstance(item, str) for item in blocking):
    fail("blockingIssues must be a list of strings")

print("OK")
