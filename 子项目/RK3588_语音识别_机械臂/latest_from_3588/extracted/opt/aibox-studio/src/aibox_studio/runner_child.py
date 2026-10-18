from __future__ import annotations

import runpy
import sys


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    runpy.run_path(sys.argv[2], run_name="__main__")


if __name__ == "__main__":
    main()
