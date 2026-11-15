"""浏览器联调：真实后端 + Flutter Web 发布版 + 审核后台，用无头 Chromium 走完整的用户流程。

入口是 `tools/e2e/run.py`，用法见 `tools/e2e/README.md`。这个包里不需要浏览器的部分
（检查汇总、构建是否过期、从样题里取数）有 `tests/unit/test_e2e_tooling.py` 守着。
"""
