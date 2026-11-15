"""浏览器辅助：Flutter Web 页面怎么找元素、怎么读文字、怎么截图。

Flutter Web 把界面画在 canvas 上，要点一下"开启无障碍"的占位元素，才会生成可以按角色和文字查找的
语义节点（`flt-semantics`）。之后 `page.get_by_role("button", name=...)` 就能用了；文字在子 `<span>` 里，
名字按子串匹配，短的名字要加 `exact=True`。

这个模块在导入时不碰 playwright（只在类型检查时导入），所以没装浏览器也能 `--list`、也能跑单元测试。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from e2e.servers import FLUTTER_URL, FLUTTER_WEB

if TYPE_CHECKING:
    from playwright.sync_api import Browser, BrowserContext, Page

# 无头模式下没有 GPU：用软件渲染，Flutter 的 CanvasKit 才画得出来
CHROMIUM_ARGS = ["--enable-unsafe-swiftshader", "--use-angle=swiftshader", "--ignore-gpu-blocklist"]


def launch(playwright: Any, *, headed: bool = False) -> Browser:
    return playwright.chromium.launch(headless=not headed, args=CHROMIUM_ARGS)


def serve_canvaskit_locally(context: BrowserContext) -> None:
    """CanvasKit 默认从 gstatic 的 CDN 下载（约 7 MB，每个新浏览器上下文都要下一遍，还可能被墙）；
    换成构建产物里的同一份，联调不依赖外网。"""

    def handler(route: Any) -> None:
        relative = route.request.url.split("/flutter-canvaskit/", 1)[1].split("/", 1)[1]
        local = FLUTTER_WEB / "canvaskit" / relative.split("?")[0]
        if local.exists():
            route.fulfill(path=str(local))
        else:
            route.continue_()

    context.route("**/flutter-canvaskit/**", handler)


def new_flutter_page(browser: Browser, *, width: int = 1100, height: int = 2600) -> tuple[Any, Any]:
    """一个全新的浏览器上下文（本机存储互相隔离）和它的页面。

    页面上多挂了三样东西，检查时用：`errors`（未捕获的异常）、`responses`（后端的 方法、路径、状态码）、
    `submit_bodies`（提交请求的请求体）。视口开得很高，一屏放得下整页，免得去滚动。
    """
    context = browser.new_context(viewport={"width": width, "height": height}, locale="zh-CN")
    serve_canvaskit_locally(context)
    page = context.new_page()
    page.errors = []
    page.responses = []
    page.submit_bodies = []
    page.on("pageerror", lambda error: page.errors.append(f"[pageerror] {error}"))
    page.on(
        "response",
        lambda response: (
            page.responses.append(
                (response.request.method, response.url.split("/api/v1")[1], response.status)
            )
            if "/api/v1/" in response.url
            else None
        ),
    )
    page.on(
        "request",
        lambda request: (
            page.submit_bodies.append(json.loads(request.post_data))
            if request.method == "POST" and request.url.endswith("/submit") and request.post_data
            else None
        ),
    )
    return context, page


def new_admin_page(browser: Browser, *, width: int = 1300, height: int = 1800) -> Any:
    """审核后台是普通的 Vue 网页：用 data-testid 找元素就行。同样记下异常、控制台错误和后端响应。"""
    context = browser.new_context(viewport={"width": width, "height": height}, locale="zh-CN")
    page = context.new_page()
    page.errors = []
    page.responses = []
    page.on("pageerror", lambda error: page.errors.append(f"[pageerror] {error}"))
    page.on(
        "console",
        lambda message: (
            page.errors.append(f"[console.{message.type}] {message.text}")
            if message.type == "error"
            else None
        ),
    )
    page.on(
        "response",
        lambda response: (
            page.responses.append(
                (response.request.method, response.url.split("/api/v1")[1], response.status)
            )
            if "/api/v1/" in response.url
            else None
        ),
    )
    return page


def enable_semantics(page: Page) -> None:
    page.evaluate(
        "() => { const p = document.querySelector('flt-semantics-placeholder'); if (p) p.click(); }"
    )
    page.wait_for_selector("flt-semantics", timeout=30000, state="attached")
    page.wait_for_timeout(500)


def open_flutter(page: Page, path: str = "") -> None:
    """打开学生端并等它画出来（首次要几秒）。"""
    page.goto(FLUTTER_URL + path)
    page.wait_for_selector("flt-glass-pane", timeout=90000, state="attached")
    enable_semantics(page)
    page.wait_for_timeout(2500)


def reopen(page: Page, path: str) -> None:
    """重新加载到某个路由。只有 # 后面不同的地址，goto 不会重新加载页面，所以明确 reload 一次。"""
    page.goto(FLUTTER_URL + path)
    page.reload()
    page.wait_for_selector("flt-glass-pane", timeout=60000, state="attached")
    enable_semantics(page)
    page.wait_for_timeout(2500)


def labels(page: Page) -> list[str]:
    """语义树里每个有文字的节点：`角色[状态] | 文字`。"""
    return page.evaluate(
        """() => Array.from(document.querySelectorAll('flt-semantics')).map(e => {
            const own = (e.getAttribute('aria-label') || '').trim();
            const text = Array.from(e.childNodes).filter(n => n.nodeType === 3 || (n.tagName === 'SPAN')).map(n => n.textContent).join('').trim();
            const flags = ['aria-checked', 'aria-selected', 'aria-disabled', 'aria-current'].map(a => e.hasAttribute(a) ? a.replace('aria-', '') + '=' + e.getAttribute(a) : '').filter(Boolean).join(',');
            return (e.getAttribute('role') || '-') + (flags ? '[' + flags + ']' : '') + ' | ' + (own || text);
        }).filter(s => s.split(' | ')[1])"""
    )


def all_text(page: Page) -> str:
    return "\n".join(item.split(" | ", 1)[1] for item in labels(page))


def find_text(page: Page, pattern: str) -> str | None:
    found = re.search(pattern, all_text(page))
    return found.group(0) if found else None


def tap(
    page: Page,
    text: str,
    *,
    role: str = "button",
    nth: int = 0,
    exact: bool = False,
    wait: int = 900,
    timeout: int = 15000,
) -> None:
    page.get_by_role(role, name=text, exact=exact).nth(nth).click(timeout=timeout)
    page.wait_for_timeout(wait)


def type_into(page: Page, locator: Any, text: str) -> None:
    """点一下输入框再输入。

    Flutter Web 的输入框是点了才接上键盘的：点完马上输入，会丢掉第一个字符（联调里出现过，
    "2.00" 变成 ".00"、"T 等于…" 变成"等于…"），所以先等焦点落稳，再一个一个字符慢一点敲。
    """
    locator.click()
    page.wait_for_timeout(300)
    page.keyboard.type(text, delay=20)
    page.wait_for_timeout(300)


def has(page: Page, text: str, *, role: str = "button", exact: bool = False) -> bool:
    return page.get_by_role(role, name=text, exact=exact).count() > 0


def is_disabled(locator: Any) -> bool:
    return locator.first.get_attribute("aria-disabled") == "true"


def stored_all(page: Page) -> dict[str, str]:
    """localStorage 里的全部键值（shared_preferences 在 Web 上存成 `flutter.<键>`，值是 JSON 编码的）。"""
    return page.evaluate(
        "() => Object.fromEntries(Object.keys(localStorage).map(k => [k, localStorage.getItem(k)]))"
    )


def stored(page: Page, name: str) -> Any:
    value = stored_all(page).get("flutter." + name)
    return None if value is None else json.loads(value)


def onboard(page: Page) -> None:
    """首次使用的三步引导：四川 → 高三 → 教材暂不清楚，进到首页。"""
    tap(page, "四川")
    tap(page, "下一步")
    tap(page, "高三", role="checkbox")
    tap(page, "下一步")
    tap(page, "开始学习", wait=2000)


def screenshot(page: Page, directory: Path, name: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.png"
    page.screenshot(path=str(path))
    return path
