"""联调里的检查项：边做边打印 ✓ / ✗，最后汇总并给出退出码。"""

from __future__ import annotations

import sys
from collections.abc import Callable

MAX_DETAIL = 400


def say(*parts: object) -> None:
    """打印中文。Windows 控制台的默认编码不是 UTF-8，直接 print 会乱码，甚至抛异常。"""
    text = " ".join(str(part) for part in parts)
    sys.stdout.buffer.write((text + "\n").encode("utf-8", "replace"))
    sys.stdout.flush()


class Checks:
    def __init__(self, echo: Callable[[str], None] = say) -> None:
        self._echo = echo
        self._results: list[tuple[str, bool]] = []

    def check(self, name: str, condition: object, detail: object = "") -> bool:
        """记一项检查。只有没通过的才打印 detail（太长的截断），通过的不啰嗦。"""
        ok = bool(condition)
        self._results.append((name, ok))
        line = ("  ✓ " if ok else "  ✗ ") + name
        if not ok and detail:
            line += f"   [{str(detail)[:MAX_DETAIL]}]"
        self._echo(line)
        return ok

    def extend(self, other: Checks) -> None:
        self._results.extend(other._results)

    def failed(self) -> list[str]:
        return [name for name, ok in self._results if not ok]

    def summary(self) -> str:
        failed = len(self.failed())
        total = len(self._results)
        return f"共 {total} 项检查，通过 {total - failed} 项，失败 {failed} 项"

    def exit_code(self) -> int:
        return 1 if self.failed() else 0
