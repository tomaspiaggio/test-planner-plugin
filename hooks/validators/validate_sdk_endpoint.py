#!/usr/bin/env python3
"""Validates autonoma/.sdk-endpoint."""
import sys
from urllib.parse import urlparse


filepath = sys.argv[1]

try:
    with open(filepath) as fh:
        value = fh.read().strip()
except Exception as exc:
    print(f'Unable to read file: {exc}')
    sys.exit(1)

if not value:
    print('.sdk-endpoint must contain a non-empty URL')
    sys.exit(1)

parsed = urlparse(value)
if parsed.scheme not in {'http', 'https'}:
    print('.sdk-endpoint must use http or https')
    sys.exit(1)

if not parsed.netloc:
    print('.sdk-endpoint must include a host')
    sys.exit(1)

print('OK')
