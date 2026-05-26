"""兼容入口 → 项目根目录 ``python main.py``。"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from main import main  # noqa: E402

if __name__ == "__main__":
    main()
