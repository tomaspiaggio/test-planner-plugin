"""Tests for validate_sdk_endpoint.py."""
from conftest import run_validator


SCRIPT = 'validate_sdk_endpoint.py'


def test_accepts_localhost_url():
    code, out = run_validator(SCRIPT, 'http://localhost:3000/api/autonoma\n', filename='.sdk-endpoint')
    assert code == 0
    assert out == 'OK'


def test_accepts_https_url():
    code, out = run_validator(SCRIPT, 'https://example.com/autonoma', filename='.sdk-endpoint')
    assert code == 0
    assert out == 'OK'


def test_rejects_empty_content():
    code, out = run_validator(SCRIPT, '', filename='.sdk-endpoint')
    assert code == 1
    assert 'non-empty URL' in out


def test_rejects_relative_path():
    code, out = run_validator(SCRIPT, '/api/autonoma', filename='.sdk-endpoint')
    assert code == 1
    assert 'http or https' in out


def test_rejects_malformed_url():
    code, out = run_validator(SCRIPT, 'https:///missing-host', filename='.sdk-endpoint')
    assert code == 1
    assert 'include a host' in out
