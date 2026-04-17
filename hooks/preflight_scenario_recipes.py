#!/usr/bin/env python3
"""Preflight resolver and endpoint lifecycle checker for scenario recipes.

Reads autonoma/scenario-recipes.json, resolves tokenized recipes into transient
concrete payloads, then sends signed up/down requests to AUTONOMA_SDK_ENDPOINT
for each recipe. Exits non-zero on any failure. Never rewrites the recipe file.
"""
import hashlib
import hmac
import json
import os
import re
import sys
import time
import urllib.request

# ---------------------------------------------------------------------------
# Variable resolution
# ---------------------------------------------------------------------------

ALLOWED_STRATEGIES = {'literal', 'derived', 'faker'}
ALLOWED_FAKER_GENERATORS = {
    'person.firstName',
    'person.lastName',
    'internet.email',
    'company.name',
    'lorem.words',
}

# Seeded Faker generators — deterministic: same (testRunId + ":" + tokenName) → same value.
# Uses the `Faker` library (pip install Faker) for realistic data generation.

def _seed_int(seed_str: str) -> int:
    return int(hashlib.sha256(seed_str.encode()).hexdigest(), 16)


def _get_faker(seed_str: str):
    """Return a seeded Faker instance."""
    from faker import Faker
    fake = Faker()
    fake.seed_instance(_seed_int(seed_str))
    return fake


# Map generator ids to Faker method calls.
_FAKER_METHOD_MAP = {
    'person.firstName': lambda f: f.first_name(),
    'person.lastName':  lambda f: f.last_name(),
    'internet.email':   lambda f: f.email(),
    'company.name':     lambda f: f.company(),
    'lorem.words':      lambda f: ' '.join(f.words(3)),
}


def _faker_generate(generator: str, seed_str: str) -> str:
    method = _FAKER_METHOD_MAP.get(generator)
    if method is None:
        raise ValueError(f'Unsupported faker generator: {generator}')
    fake = _get_faker(seed_str)
    return method(fake)


def resolve_variable(var_def: dict, test_run_id: str, token_name: str) -> object:
    """Resolve a single variable definition to a concrete value."""
    strategy = var_def.get('strategy')
    if strategy not in ALLOWED_STRATEGIES:
        raise ValueError(f'Unsupported variable strategy: {strategy}')

    if strategy == 'literal':
        return var_def['value']

    if strategy == 'derived':
        source = var_def.get('source')
        if source != 'testRunId':
            raise ValueError(f'derived.source must be "testRunId", got: {source}')
        fmt = var_def.get('format')
        if not fmt or not isinstance(fmt, str):
            raise ValueError(f'derived.format must be a non-empty string')
        return fmt.replace('{testRunId}', test_run_id)

    if strategy == 'faker':
        generator = var_def.get('generator')
        if not generator or not isinstance(generator, str):
            raise ValueError(f'faker.generator must be a non-empty string')
        if generator not in ALLOWED_FAKER_GENERATORS:
            raise ValueError(f'Unsupported faker generator: {generator}')
        seed_str = f'{test_run_id}:{token_name}'
        return _faker_generate(generator, seed_str)

    raise ValueError(f'Unsupported variable strategy: {strategy}')


def _find_tokens(obj) -> set:
    """Find all {{token}} placeholders in a JSON-like structure."""
    tokens = set()
    if isinstance(obj, str):
        tokens.update(re.findall(r'\{\{(\w+)\}\}', obj))
    elif isinstance(obj, list):
        for item in obj:
            tokens.update(_find_tokens(item))
    elif isinstance(obj, dict):
        for v in obj.values():
            tokens.update(_find_tokens(v))
    return tokens


def _resolve_value(val, resolved_vars: dict):
    """Deep-resolve a single value, replacing {{token}} patterns."""
    if isinstance(val, str):
        # Check for full-string replacement (entire string is one token)
        m = re.fullmatch(r'\{\{(\w+)\}\}', val)
        if m:
            token = m.group(1)
            if token not in resolved_vars:
                raise ValueError(f'Unresolved token: {{{{{token}}}}}')
            return resolved_vars[token]
        # Embedded replacement
        def _replace(match):
            token = match.group(1)
            if token not in resolved_vars:
                raise ValueError(f'Unresolved token: {{{{{token}}}}}')
            return str(resolved_vars[token])
        result = re.sub(r'\{\{(\w+)\}\}', _replace, val)
        return result
    if isinstance(val, list):
        return [_resolve_value(item, resolved_vars) for item in val]
    if isinstance(val, dict):
        return {k: _resolve_value(v, resolved_vars) for k, v in val.items()}
    return val


def resolve_recipe(recipe: dict, test_run_id: str) -> dict:
    """Resolve a tokenized recipe create payload into a concrete payload.

    Returns the resolved create dict. Raises on any resolution failure.
    """
    create = recipe.get('create', {})
    variables = recipe.get('variables', {})

    # Validate: every token in create has a variable definition
    tokens_in_create = _find_tokens(create)
    var_keys = set(variables.keys())

    missing = tokens_in_create - var_keys
    if missing:
        raise ValueError(f'Tokens without variable definitions: {missing}')

    unused = var_keys - tokens_in_create
    if unused:
        raise ValueError(f'Unused variable definitions: {unused}')

    # Resolve all variables
    resolved = {}
    for name, var_def in variables.items():
        resolved[name] = resolve_variable(var_def, test_run_id, name)

    # Deep-resolve the create payload
    resolved_create = _resolve_value(create, resolved)

    # Final check: no unresolved tokens remain
    remaining = _find_tokens(resolved_create)
    if remaining:
        raise ValueError(f'Unresolved tokens after resolution: {remaining}')

    return resolved_create


# ---------------------------------------------------------------------------
# Signed HTTP helpers
# ---------------------------------------------------------------------------

def _sign(body_bytes: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body_bytes, hashlib.sha256).hexdigest()


def _post(url: str, payload: dict, secret: str) -> tuple:
    """POST JSON to url with HMAC signature. Returns (status, response_dict, elapsed_ms)."""
    body = json.dumps(payload).encode()
    sig = _sign(body, secret)
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            'Content-Type': 'application/json',
            'x-signature': sig,
        },
        method='POST',
    )
    start = time.time()
    try:
        resp = urllib.request.urlopen(req)
        elapsed = int((time.time() - start) * 1000)
        data = json.loads(resp.read())
        return resp.status, data, elapsed
    except urllib.error.HTTPError as e:
        elapsed = int((time.time() - start) * 1000)
        try:
            data = json.loads(e.read())
        except Exception:
            data = {'error': str(e)}
        return e.code, data, elapsed


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def generate_test_run_id(scenario_name: str) -> str:
    ms = int(time.time() * 1000)
    suffix = hashlib.sha256(f'{scenario_name}{ms}'.encode()).hexdigest()[:6]
    return f'autonoma-preflight-{scenario_name}-{ms}-{suffix}'


def preflight(recipe_path: str, endpoint: str, secret: str) -> bool:
    """Run preflight for all recipes. Returns True on success."""
    with open(recipe_path) as f:
        data = json.load(f)

    recipes = data.get('recipes', [])
    all_ok = True
    results = []

    for recipe in recipes:
        name = recipe.get('name', '<unnamed>')
        test_run_id = generate_test_run_id(name)

        # Step 1: Resolve
        print(f'\n--- Preflight: {name} ---')
        print(f'  testRunId: {test_run_id}')
        try:
            resolved_create = resolve_recipe(recipe, test_run_id)
        except ValueError as e:
            print(f'  FAIL (recipe compilation): {e}')
            all_ok = False
            results.append({'name': name, 'status': 'fail', 'phase': 'compilation', 'error': str(e)})
            continue

        # Step 2: Signed up
        up_payload = {
            'action': 'up',
            'create': resolved_create,
            'testRunId': test_run_id,
        }
        status, resp, up_ms = _post(endpoint, up_payload, secret)
        print(f'  up: HTTP {status} ({up_ms}ms)')
        if status < 200 or status >= 300:
            print(f'  FAIL (endpoint up): HTTP {status} — {json.dumps(resp)}')
            all_ok = False
            results.append({'name': name, 'status': 'fail', 'phase': 'up', 'http': status})
            continue

        # Validate up response
        for field in ('auth', 'refs', 'refsToken'):
            if field not in resp:
                print(f'  FAIL (endpoint up): missing field "{field}" in response')
                all_ok = False
                results.append({'name': name, 'status': 'fail', 'phase': 'up', 'error': f'missing {field}'})
                break
        else:
            # Step 3: Signed down
            down_payload = {
                'action': 'down',
                'refs': resp['refs'],
                'refsToken': resp['refsToken'],
                'testRunId': test_run_id,
            }
            d_status, d_resp, down_ms = _post(endpoint, down_payload, secret)
            print(f'  down: HTTP {d_status} ({down_ms}ms)')
            if d_status < 200 or d_status >= 300:
                print(f'  FAIL (endpoint down): HTTP {d_status} — {json.dumps(d_resp)}')
                all_ok = False
                results.append({'name': name, 'status': 'fail', 'phase': 'down', 'http': d_status})
                continue

            print(f'  OK (up: {up_ms}ms, down: {down_ms}ms)')
            results.append({'name': name, 'status': 'ok', 'up_ms': up_ms, 'down_ms': down_ms})
            continue
        # If we broke out of the for-else, continue to next recipe
        continue

    print(f'\n--- Summary ---')
    for r in results:
        status_str = 'OK' if r['status'] == 'ok' else f"FAIL ({r.get('phase', '?')})"
        print(f"  {r['name']}: {status_str}")

    return all_ok


def main():
    if len(sys.argv) < 2:
        print(f'Usage: {sys.argv[0]} <scenario-recipes.json>')
        sys.exit(1)

    recipe_path = sys.argv[1]

    # Ensure Faker is available
    try:
        import faker  # noqa: F401
    except ImportError:
        import subprocess
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'Faker', '-q'],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    endpoint = os.environ.get('AUTONOMA_SDK_ENDPOINT')
    secret = os.environ.get('AUTONOMA_SHARED_SECRET')

    if not endpoint:
        print('ERROR: AUTONOMA_SDK_ENDPOINT is not set')
        sys.exit(1)
    if not secret:
        print('ERROR: AUTONOMA_SHARED_SECRET is not set')
        sys.exit(1)

    ok = preflight(recipe_path, endpoint, secret)
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
