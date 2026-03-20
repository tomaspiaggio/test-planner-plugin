"""Shared helpers for validator tests."""
import os
import subprocess
import tempfile

VALIDATORS_DIR = os.path.join(os.path.dirname(__file__), '..', 'hooks', 'validators')


def run_validator(script_name: str, content: str, filename: str = 'test.md') -> tuple[int, str]:
    """Write content to a temp file, run the validator, return (exit_code, output)."""
    script = os.path.join(VALIDATORS_DIR, script_name)
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = os.path.join(tmpdir, filename)
        with open(filepath, 'w') as f:
            f.write(content)
        result = subprocess.run(
            ['python3', script, filepath],
            capture_output=True, text=True,
        )
        output = (result.stdout + result.stderr).strip()
        return result.returncode, output


def run_validator_with_dir(script_name: str, files: dict[str, str], target: str) -> tuple[int, str]:
    """Write multiple files into a temp dir tree, run validator on target, return (exit_code, output).

    files: mapping of relative paths to content (e.g. {'autonoma/qa-tests/INDEX.md': '...'})
    target: relative path within the temp dir to validate
    """
    script = os.path.join(VALIDATORS_DIR, script_name)
    with tempfile.TemporaryDirectory() as tmpdir:
        for relpath, content in files.items():
            fullpath = os.path.join(tmpdir, relpath)
            os.makedirs(os.path.dirname(fullpath), exist_ok=True)
            with open(fullpath, 'w') as f:
                f.write(content)
        filepath = os.path.join(tmpdir, target)
        result = subprocess.run(
            ['python3', script, filepath],
            capture_output=True, text=True,
        )
        output = (result.stdout + result.stderr).strip()
        return result.returncode, output
