"""浏览器联调的入口：起真实后端、托管 Flutter Web 发布版、（需要时）起审核后台，用无头 Chromium 走流程。

    uv run --group e2e python tools/e2e/run.py                 # 全部流程（Web 版过期会先重新构建）
    uv run --group e2e python tools/e2e/run.py --list          # 列出流程
    uv run --group e2e python tools/e2e/run.py --only parent_weekly student_experiment
    uv run --group e2e python tools/e2e/run.py --no-build      # 不检查、不构建 Web 版（用现成的）
    uv run --group e2e python tools/e2e/run.py --headed        # 显示浏览器窗口（排查用）

第一次要装浏览器：`uv run --group e2e playwright install chromium`。
输出（每条流程的后端日志、数据库、截图）在 var/e2e/ 下，已被 .gitignore 忽略。
退出码：0 全部通过，1 有检查没通过，2 环境问题（缺依赖、端口被占、构建失败……）。
"""

from __future__ import annotations

import argparse
import shutil
import sys
import traceback
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from e2e import servers  # noqa: E402
from e2e.checks import Checks, say  # noqa: E402
from e2e.flowbase import Context  # noqa: E402
from e2e.flows import FLOWS  # noqa: E402

OUT_ROOT = servers.REPO_ROOT / "var" / "e2e"
ENVIRONMENT = 2


def _parse(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="浏览器联调")
    parser.add_argument("--list", action="store_true", help="列出流程后退出")
    parser.add_argument("--only", nargs="+", metavar="流程", help="只跑这几条流程")
    parser.add_argument("--no-build", action="store_true", help="不检查、不构建 Flutter Web 版")
    parser.add_argument("--headed", action="store_true", help="显示浏览器窗口")
    parser.add_argument(
        "--flutter", help="flutter 可执行文件的路径（默认按 FLUTTER_BIN、PATH、C:/src/flutter 找）"
    )
    return parser.parse_args(argv)


def _print_flows() -> None:
    for flow in FLOWS.values():
        say(f"{flow.name:<20} {flow.title}")


def _ensure_web_build(args: argparse.Namespace) -> bool:
    reason = servers.needs_rebuild(servers.FLUTTER_WEB / "main.dart.js", servers.FLUTTER_SOURCES)
    if reason is None:
        return True
    if args.no_build:
        say(f"警告：Web 版可能是旧的（{reason}），但指定了 --no-build，照旧用现成的。")
        return (servers.FLUTTER_WEB / "main.dart.js").exists()
    flutter = servers.find_flutter(args.flutter)
    if flutter is None:
        say(
            f"需要重新构建 Web 版（{reason}），但找不到 flutter：用 --flutter 指定，或设置 FLUTTER_BIN。"
        )
        return False
    say(f"重新构建 Web 版（{reason}），约 2~3 分钟……")
    try:
        servers.build_flutter_web(flutter, OUT_ROOT / "flutter_build.log")
    except servers.ServiceError as error:
        say(str(error))
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    args = _parse(argv)
    if args.list:
        _print_flows()
        return 0

    names = args.only or list(FLOWS)
    unknown = [name for name in names if name not in FLOWS]
    if unknown:
        say(f"没有这些流程：{', '.join(unknown)}。可用的：{', '.join(FLOWS)}")
        return ENVIRONMENT
    selected = [FLOWS[name] for name in names]
    needs = set().union(*(flow.needs for flow in selected))

    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError:
        say(
            "缺少 playwright：用 `uv run --group e2e python tools/e2e/run.py` 运行（第一次还要 "
            "`uv run --group e2e playwright install chromium`）。"
        )
        return ENVIRONMENT

    wanted_ports = [servers.API_PORT]
    if "flutter" in needs:
        wanted_ports.append(servers.FLUTTER_PORT)
    if "admin" in needs:
        wanted_ports.append(servers.ADMIN_PORT)
    busy = [port for port in wanted_ports if servers.port_in_use(port)]
    if busy:
        say(f"端口被占用：{', '.join(map(str, busy))}。联调用固定端口，先停掉本机的开发服务再跑。")
        return ENVIRONMENT

    shutil.rmtree(OUT_ROOT, ignore_errors=True)
    OUT_ROOT.mkdir(parents=True)
    if "flutter" in needs and not _ensure_web_build(args):
        return ENVIRONMENT

    from e2e.browser import launch

    total = Checks()
    static: servers.StaticServer | None = None
    admin: servers.Service | None = None
    try:
        if "flutter" in needs:
            static = servers.StaticServer(servers.FLUTTER_WEB)
        if "admin" in needs:
            admin = servers.start_admin_dev(OUT_ROOT)
        with sync_playwright() as playwright:
            try:
                browser = launch(playwright, headed=args.headed)
            except PlaywrightError as error:
                say(
                    f"浏览器没能启动：{error}\n第一次要执行 `uv run --group e2e playwright install chromium`。"
                )
                return ENVIRONMENT
            for flow in selected:
                say(f"\n===== {flow.name}：{flow.title} =====")
                flow_dir = OUT_ROOT / flow.name
                api = servers.start_api(
                    flow_dir,
                    media_enabled=flow.name
                    in {
                        "document_import",
                        "admin_media_write_recovery",
                        "admin_document_write_recovery",
                    },
                    scan_enabled=flow.name
                    in {"student_scan", "student_scan_recovery", "local_draft_export"},
                    review_minutes=flow.review_minutes,
                )  # 每条流程一个全新的数据库
                checks = Checks()
                ctx = Context(browser=browser, checks=checks, out_dir=flow_dir)
                try:
                    flow.run(ctx)
                except Exception as error:  # noqa: BLE001  流程中途出错也要把现场留下，并算作失败
                    checks.check(f"流程没有中途出错（{type(error).__name__}）", False, repr(error))
                    say(traceback.format_exc())
                    for path in ctx.shot_all("failure"):
                        say(f"  现场截图：{path}")
                finally:
                    ctx.close()
                    api.stop()
                total.extend(checks)
                say(f"-- {flow.name}：{checks.summary()}")
            browser.close()
    except servers.ServiceError as error:
        say(str(error))
        return ENVIRONMENT
    finally:
        if admin is not None:
            admin.stop()
        if static is not None:
            static.stop()

    say(f"\n{total.summary()}（输出在 {OUT_ROOT}）")
    for name in total.failed():
        say(f"  失败：{name}")
    return total.exit_code()


if __name__ == "__main__":
    sys.exit(main())
