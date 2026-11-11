"""本地开发 API（ADR-006 原型）。

    uv run python tools/run_dev_api.py
    uv run python tools/run_dev_api.py --port 8010 --review-minutes 1,2,3

这个入口会显式开启两样只属于原型期的东西，并且只监听回环地址 127.0.0.1：
- 本地身份 Mock（Q-03）：`POST /api/v1/dev/local-identities` 发放随机 bearer；
- 自编工程样题（Q-05）：题库为空时写入 services/api/seed 下的样题。

演示状态保存在 var/tutor_dev.sqlite3（已被 .gitignore 忽略）；删掉这个文件就回到初始状态。
已经在环境变量里设置过的 TUTOR_* 不会被这里覆盖。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HOST = "127.0.0.1"  # 原型只绑定回环地址，不提供改成其他地址的选项


def main() -> None:
    parser = argparse.ArgumentParser(description="启动本地开发 API（仅回环地址）")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--review-minutes",
        help="覆盖间隔复测的间隔（分钟，逗号分隔），便于演示；默认 1440,4320,10080",
    )
    args = parser.parse_args()

    for package_dir in ("services/api", "services/ai_gateway"):
        sys.path.insert(0, str(REPO_ROOT / package_dir))
    os.environ.setdefault("TUTOR_ENV", "local")
    os.environ.setdefault("TUTOR_LOCAL_IDENTITY_MOCK", "true")
    os.environ.setdefault("TUTOR_SEED_SAMPLE_CONTENT", "true")
    if args.review_minutes:
        os.environ["TUTOR_REVIEW_INTERVALS_MINUTES"] = args.review_minutes

    import uvicorn

    print(f"本地 API：http://{HOST}:{args.port}/api/v1/health  （身份 Mock 与样题已显式开启）")
    uvicorn.run("tutor_api.main:create_app", factory=True, host=HOST, port=args.port)


if __name__ == "__main__":
    main()
