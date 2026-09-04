from pathlib import Path
import sys


CODE_DIR = Path(__file__).resolve().parents[1] / "代码"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))
