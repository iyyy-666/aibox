from __future__ import annotations

import sys

from .runtime import run_worker


def main() -> int:
    if len(sys.argv) != 2:
        sys.stderr.write("用法：python -m feature_demo.workers <worker-name>\n")
        return 2
    return run_worker(sys.argv[1])


if __name__ == "__main__":
    raise SystemExit(main())
