"""Tests for hooks/validate-pipeline-output.sh."""
import json
import os
import subprocess
import tempfile
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'hooks' / 'validate-pipeline-output.sh'

VALID_DISCOVER = {
    'schema': {
        'models': [
            {
                'name': 'Organization',
                'fields': [
                    {
                        'name': 'name',
                        'type': 'String',
                        'isRequired': True,
                        'isId': False,
                        'hasDefault': False,
                    },
                ],
            },
        ],
        'edges': [],
        'relations': [],
        'scopeField': 'organizationId',
    },
}

VALID_RECIPES = {
    'version': 1,
    'source': {
        'discoverPath': 'autonoma/discover.json',
        'scenariosPath': 'autonoma/scenarios.md',
    },
    'validationMode': 'sdk-check',
    'recipes': [
        {
            'name': 'standard',
            'description': 'Standard baseline',
            'create': {'Organization': [{'name': 'Acme Standard'}]},
            'validation': {'status': 'validated', 'method': 'checkScenario', 'phase': 'ok'},
        },
        {
            'name': 'empty',
            'description': 'Empty workspace',
            'create': {'Organization': [{'name': 'Acme Empty'}]},
            'validation': {'status': 'validated', 'method': 'checkScenario', 'phase': 'ok'},
        },
        {
            'name': 'large',
            'description': 'Large workspace',
            'create': {'Organization': [{'name': 'Acme Large'}]},
            'validation': {'status': 'validated', 'method': 'endpoint-up-down', 'phase': 'ok'},
        },
    ],
}


def test_sdk_endpoint_hook_accepts_valid_url():
    env = os.environ.copy()

    code, out, err = _run_hook(
        {
            'autonoma/.sdk-endpoint': 'http://127.0.0.1:3000/api/autonoma\n',
        },
        'autonoma/.sdk-endpoint',
        env,
    )

    assert code == 0
    assert out == ''
    assert err == ''


def test_sdk_endpoint_hook_blocks_invalid_url():
    env = os.environ.copy()

    code, _, err = _run_hook(
        {
            'autonoma/.sdk-endpoint': '/api/autonoma\n',
        },
        'autonoma/.sdk-endpoint',
        env,
    )

    assert code == 2
    assert 'validate-sdk-endpoint' in err
    assert 'http or https' in err


def test_sdk_integration_hook_accepts_valid_json():
    env = os.environ.copy()

    code, out, err = _run_hook(
        {
            'autonoma/.sdk-integration.json': json.dumps(
                {
                    'status': 'ok',
                    'endpointUrl': 'http://127.0.0.1:3000/api/autonoma',
                    'endpointPath': '/api/autonoma',
                    'stack': {
                        'language': 'TypeScript',
                        'framework': 'Express',
                        'orm': 'Prisma',
                        'packageManager': 'pnpm',
                    },
                    'packagesInstalled': ['@autonoma-ai/sdk'],
                    'sharedSecretPresent': True,
                    'signingSecretPresent': True,
                    'devServer': {'startedByPlugin': True, 'pid': 1234},
                    'verification': {
                        'discover': {'status': 'ok', 'validatedByPlugin': True},
                        'up': {'status': 'ok'},
                        'down': {'status': 'ok'},
                    },
                    'branch': {'name': 'autonoma/feat-autonoma-sdk'},
                    'pr': {'url': 'https://github.com/example/repo/pull/1'},
                    'blockingIssues': [],
                }
            ),
        },
        'autonoma/.sdk-integration.json',
        env,
    )

    assert code == 0
    assert out == ''
    assert err == ''


def test_sdk_integration_hook_blocks_invalid_json():
    env = os.environ.copy()

    code, _, err = _run_hook(
        {
            'autonoma/.sdk-integration.json': json.dumps({'status': 'ok'}),
        },
        'autonoma/.sdk-integration.json',
        env,
    )

    assert code == 2
    assert 'validate-sdk-integration' in err
    assert 'Missing required fields' in err


def test_scenario_validation_hook_accepts_valid_json():
    env = os.environ.copy()

    code, out, err = _run_hook(
        {
            'autonoma/.scenario-validation.json': json.dumps(
                {
                    'status': 'ok',
                    'preflightPassed': True,
                    'smokeTestPassed': True,
                    'validatedScenarios': ['standard', 'empty', 'large'],
                    'failedScenarios': [],
                    'blockingIssues': [],
                    'recipePath': 'autonoma/scenario-recipes.json',
                    'validationMode': 'sdk-check',
                    'endpointUrl': 'http://127.0.0.1:3000/api/autonoma',
                }
            ),
        },
        'autonoma/.scenario-validation.json',
        env,
    )

    assert code == 0
    assert out == ''
    assert err == ''


def test_scenario_validation_hook_blocks_invalid_json():
    env = os.environ.copy()

    code, _, err = _run_hook(
        {
            'autonoma/.scenario-validation.json': json.dumps(
                {
                    'status': 'failed',
                    'preflightPassed': False,
                }
            ),
        },
        'autonoma/.scenario-validation.json',
        env,
    )

    assert code == 2
    assert 'validate-scenario-validation' in err
    assert 'Missing required fields' in err


def _run_hook(files: dict[str, str], target: str, env: dict[str, str]) -> tuple[int, str, str]:
    with tempfile.TemporaryDirectory() as tmpdir:
        for relpath, content in files.items():
            fullpath = Path(tmpdir) / relpath
            fullpath.parent.mkdir(parents=True, exist_ok=True)
            fullpath.write_text(content)

        target_path = str(Path(tmpdir) / target)
        payload = json.dumps({'tool_input': {'file_path': target_path}})
        result = subprocess.run(
            ['bash', str(SCRIPT)],
            input=payload,
            text=True,
            capture_output=True,
            env=env,
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()


@contextmanager
def _sdk_server(up_status: int = 200, down_status: int = 200):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get('Content-Length', '0'))
            body = json.loads(self.rfile.read(length) or '{}')
            action = body.get('action')

            if action == 'up':
                status = up_status
                response = {'auth': {}, 'refs': {'organization': ['org_1']}, 'refsToken': 'token_1'}
                if status >= 400:
                    response = {'error': 'up failed'}
            elif action == 'down':
                status = down_status
                response = {'ok': True}
                if status >= 400:
                    response = {'error': 'down failed'}
            else:
                status = 400
                response = {'error': 'unknown action'}

            encoded = json.dumps(response).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, format, *args):
            return

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_address[1]}'
    finally:
        server.shutdown()
        thread.join()


def test_scenario_recipes_hook_requires_preflight_env():
    env = os.environ.copy()
    env.pop('AUTONOMA_SDK_ENDPOINT', None)
    env.pop('AUTONOMA_SHARED_SECRET', None)

    code, _, err = _run_hook(
        {
            'autonoma/scenario-recipes.json': json.dumps(VALID_RECIPES),
            'autonoma/discover.json': json.dumps(VALID_DISCOVER),
        },
        'autonoma/scenario-recipes.json',
        env,
    )

    assert code == 2
    assert 'scenario-recipes-preflight' in err
    assert 'AUTONOMA_SDK_ENDPOINT is not set' in err


def test_scenario_recipes_hook_runs_preflight_successfully():
    with _sdk_server() as endpoint:
        env = os.environ.copy()
        env['AUTONOMA_SDK_ENDPOINT'] = endpoint
        env['AUTONOMA_SHARED_SECRET'] = 'test-secret'

        code, out, err = _run_hook(
            {
                'autonoma/scenario-recipes.json': json.dumps(VALID_RECIPES),
                'autonoma/discover.json': json.dumps(VALID_DISCOVER),
            },
            'autonoma/scenario-recipes.json',
            env,
        )

    assert code == 0
    assert out == ''
    assert err == ''


def test_scenario_recipes_hook_blocks_failed_preflight():
    with _sdk_server(up_status=500) as endpoint:
        env = os.environ.copy()
        env['AUTONOMA_SDK_ENDPOINT'] = endpoint
        env['AUTONOMA_SHARED_SECRET'] = 'test-secret'

        code, _, err = _run_hook(
            {
                'autonoma/scenario-recipes.json': json.dumps(VALID_RECIPES),
                'autonoma/discover.json': json.dumps(VALID_DISCOVER),
            },
            'autonoma/scenario-recipes.json',
            env,
        )

    assert code == 2
    assert 'scenario-recipes-preflight' in err
    assert 'HTTP 500' in err
