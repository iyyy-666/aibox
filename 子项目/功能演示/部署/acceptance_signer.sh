#!/bin/bash
set -euo pipefail

KEY_FILE="${FEATURE_DEMO_ACCEPTANCE_KEY:-/var/lib/feature-demo/acceptance.key}"
[[ $# -eq 1 ]] || { echo "Usage: $0 PAYLOAD" >&2; exit 2; }
[[ -r "$KEY_FILE" ]] || { echo "Acceptance key is unavailable: $KEY_FILE" >&2; exit 1; }

python3 - "$KEY_FILE" "$1" <<'PY'
import hashlib
import hmac
from pathlib import Path
import sys

key = Path(sys.argv[1]).read_bytes()
if len(key) < 32:
    raise SystemExit("Acceptance key must contain at least 32 bytes")
print(hmac.new(key, sys.argv[2].encode("utf-8"), hashlib.sha256).hexdigest())
PY
