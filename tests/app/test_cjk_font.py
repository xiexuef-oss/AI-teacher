"""学生端打包的中文字体子集（tools/build_cjk_font.py）。

Web 版渲染中文要联网下载回退字体，网络受限时会显示成方块，所以字体打进了应用。
这里确认：字体登记了、许可文件在、界面和样题里出现的每个汉字都在子集里。
"""

from __future__ import annotations

import re

import pytest

from support import REPO_ROOT

APP = REPO_ROOT / "apps" / "flutter_student"
FONT = APP / "assets" / "fonts" / "NotoSansSC-Subset.otf"
LICENSE = APP / "assets" / "fonts" / "OFL.txt"

# 汉字与 CJK 标点、全角形式（字体子集里必须有）。数学上下标等符号不要求。
CJK = re.compile(r"[　-〿一-鿿＀-￯]")
SCANNED = [
    (APP / "lib", {".dart"}),
    (REPO_ROOT / "services" / "api" / "seed", {".yaml"}),
    (REPO_ROOT / "services" / "api" / "tutor_api", {".py"}),
]


def test_font_is_registered_in_pubspec_with_its_license():
    pubspec = (APP / "pubspec.yaml").read_text(encoding="utf-8")
    assert "family: NotoSansSC" in pubspec
    assert "assets/fonts/NotoSansSC-Subset.otf" in pubspec
    assert FONT.exists() and FONT.stat().st_size > 100_000
    assert "SIL Open Font License" in LICENSE.read_text(encoding="utf-8")


def test_theme_and_painters_fall_back_to_the_bundled_font():
    theme = (APP / "lib" / "core" / "theme.dart").read_text(encoding="utf-8")
    assert "kCjkFontFallback = ['NotoSansSC']" in theme
    assert "fontFamilyFallback: kCjkFontFallback" in theme
    painters = (APP / "lib" / "features" / "visual" / "painters.dart").read_text(encoding="utf-8")
    assert "fontFamilyFallback: kCjkFontFallback" in painters, "画布上的自绘文字不走主题"


def test_every_chinese_character_used_in_the_app_is_in_the_font():
    fontTools = pytest.importorskip("fontTools.ttLib")
    with fontTools.TTFont(str(FONT)) as font:
        cmap = font.getBestCmap()

    used: dict[str, set[str]] = {}
    for directory, suffixes in SCANNED:
        for path in directory.rglob("*"):
            if path.suffix in suffixes and path.is_file():
                for char in set(CJK.findall(path.read_text(encoding="utf-8"))):
                    if ord(char) not in cmap:
                        used.setdefault(char, set()).add(str(path.relative_to(REPO_ROOT)))

    assert not used, (
        "这些字不在中文字体子集里，Web 版会显示成方块；运行 "
        "`uv run --with fonttools python tools/build_cjk_font.py` 重新生成：\n"
        + "\n".join(f"{char} ← {sorted(files)[0]}" for char, files in sorted(used.items()))
    )


def test_font_script_pins_the_source_checksum():
    script = (REPO_ROOT / "tools" / "build_cjk_font.py").read_text(encoding="utf-8")
    assert re.search(r'SOURCE_FONT_SHA256: str \| None = "[0-9a-f]{64}"', script)
