"""把后端、模型网关和测试辅助放进 sys.path。

联调脚本是单独运行的，不经过 pytest（pytest 的 pythonpath 配置在 pyproject.toml 里），
而它要用到样题加载、判题和测试里的答案表。导入这个模块就够了，它没有别的作用。
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

for _extra in ("services/api", "services/ai_gateway", "tests"):
    _path = str(REPO_ROOT / _extra)
    if _path not in sys.path:
        sys.path.insert(0, _path)
