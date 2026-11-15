"""流程的公共定义：一条流程是什么（Flow），它运行时拿到什么（Context）。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from e2e import browser
from e2e.checks import Checks


@dataclass
class Context:
    browser: Any
    checks: Checks
    out_dir: Path  # 这条流程自己的输出目录：后端日志、数据库、截图都放在这里
    pages: list[Any] = field(default_factory=list)

    @property
    def check(self):
        return self.checks.check

    def new_page(self, *, width: int = 1100, height: int = 2600) -> Any:
        """学生端用的页面：新的浏览器上下文（本机存储隔离），带 Flutter 需要的 CanvasKit 本地托管。"""
        _, page = browser.new_flutter_page(self.browser, width=width, height=height)
        self.pages.append(page)
        return page

    def new_admin_page(self, *, width: int = 1300, height: int = 1800) -> Any:
        """审核后台用的页面：普通的网页，不需要 Flutter 那一套。"""
        page = browser.new_admin_page(self.browser, width=width, height=height)
        self.pages.append(page)
        return page

    def shot(self, page: Any, name: str) -> Path:
        return browser.screenshot(page, self.out_dir / "screenshots", name)

    def shot_all(self, prefix: str) -> list[Path]:
        """给登记过的页面都截一张图（流程出错时留个现场）。"""
        saved = []
        for index, page in enumerate(self.pages):
            try:
                saved.append(self.shot(page, f"{prefix}_{index}"))
            except Exception:  # noqa: BLE001  页面可能已经关了；截图失败不该盖住原来的错误
                continue
        return saved

    def close(self) -> None:
        for page in self.pages:
            try:
                page.context.close()
            except Exception:  # noqa: BLE001
                continue
        self.pages.clear()


@dataclass(frozen=True)
class Flow:
    name: str
    title: str
    needs: frozenset[str]  # "flutter"：学生端 Web 版；"admin"：审核后台
    run: Callable[[Context], None]
