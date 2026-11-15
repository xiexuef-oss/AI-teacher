"""生成学生端打包的中文字体子集（apps/flutter_student/assets/fonts）。

    uv run --with fonttools python tools/build_cjk_font.py

为什么需要：Flutter 的 Web 版（CanvasKit）渲染中文要从网络下载回退字体，网络受限时中文全是方块。
Android 与 iOS 用系统字体，不受影响；但 Web 版是本地联调的主要手段，所以把字体打进应用。

做法：下载 Noto Sans SC（SIL OFL 1.1，允许打包与裁剪），只保留
  - ASCII、常用标点、全角形式、数学与单位符号、箭头；
  - GB2312 一级汉字（3755 个，覆盖现代汉语 99% 以上的用字）；
  - 仓库里实际出现过的所有非 ASCII 字符（界面文字、样题、后端的中文提示）。
裁剪后约 2 MB。题库将来出现一级字表以外的生僻字时，Web 版会显示成方块，Android/iOS 不受影响；
遇到时重新运行本脚本即可（它会重新扫描仓库）。

下载的源字体会校验 SHA-256，防止上游文件被替换后悄悄进了仓库。
"""

from __future__ import annotations

import contextlib
import hashlib
import sys
import tempfile
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = REPO_ROOT / "apps" / "flutter_student" / "assets" / "fonts"

SOURCE_FONT_URL = "https://raw.githubusercontent.com/notofonts/noto-cjk/main/Sans/SubsetOTF/SC/NotoSansSC-Regular.otf"
SOURCE_LICENSE_URL = "https://raw.githubusercontent.com/notofonts/noto-cjk/main/Sans/LICENSE"
# 首次下载后记录。上游更新字体后校验会失败，需要人确认变更再更新这个值。
SOURCE_FONT_SHA256: str | None = "faa6c9df652116dde789d351359f3d7e5d2285a2b2a1f04a2d7244df706d5ea9"

OUTPUT_FONT = OUTPUT_DIR / "NotoSansSC-Subset.otf"
OUTPUT_LICENSE = OUTPUT_DIR / "OFL.txt"

SCAN_DIRS = [
    REPO_ROOT / "apps" / "flutter_student" / "lib",
    REPO_ROOT / "services",
    REPO_ROOT / "contracts",
    REPO_ROOT / "packages" / "visual_templates",
]
SCAN_SUFFIXES = {".dart", ".py", ".yaml", ".yml", ".json", ".md"}

# 额外保留的码位范围（字体里没有的会被忽略）
EXTRA_RANGES = [
    (0x0020, 0x007E),  # ASCII
    (0x00A0, 0x00BF),  # 拉丁补充：° ² ³ · 等
    (0x00D7, 0x00D7),  # ×
    (0x00F7, 0x00F7),  # ÷
    (0x0370, 0x03FF),  # 希腊字母：θ α β μ π ω …
    (0x2010, 0x2027),  # 破折号、引号、省略号
    (0x2030, 0x205E),  # ‰ ′ ″ 等
    (0x2070, 0x209F),  # 上下标
    (0x2190, 0x21FF),  # 箭头
    (0x2200, 0x22FF),  # 数学运算符：≤ ≥ ≠ ∞ ∈ …
    (0x2460, 0x24FF),  # 带圈数字
    (0x25A0, 0x25FF),  # 几何图形
    (0x2600, 0x26FF),  # 杂项符号：✓ 等
    (0x3000, 0x303F),  # CJK 标点
    (0xFF00, 0xFFEF),  # 全角形式
]


def gb2312_level1() -> set[str]:
    chars: set[str] = set()
    for lead in range(0xB0, 0xD8):  # 一级汉字区
        for trail in range(0xA1, 0xFF):
            with contextlib.suppress(UnicodeDecodeError):  # 区位表里的空位
                chars.add(bytes([lead, trail]).decode("gb2312"))
    return chars


def repository_characters() -> set[str]:
    chars: set[str] = set()
    for directory in SCAN_DIRS:
        for path in directory.rglob("*"):
            if path.suffix not in SCAN_SUFFIXES or not path.is_file():
                continue
            if any(
                part in {".venv", "__pycache__", "build", ".dart_tool", "node_modules"}
                for part in path.parts
            ):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            chars.update(c for c in text if ord(c) > 0x7F)
    return chars


def download(url: str, target: Path) -> None:
    print(f"下载 {url}")
    with urllib.request.urlopen(url, timeout=120) as response:  # noqa: S310 - 固定的 https 地址
        target.write_bytes(response.read())


def main() -> int:
    from fontTools import subset
    from fontTools.ttLib import TTFont

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    # Windows 上字体文件的句柄可能比 with 块活得久，清理失败不影响结果
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        source = Path(tmp) / "NotoSansSC-Regular.otf"
        download(SOURCE_FONT_URL, source)
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        print(f"源字体 SHA-256：{digest}")
        if SOURCE_FONT_SHA256 is not None and digest != SOURCE_FONT_SHA256:
            print(
                "源字体与记录的校验值不一致，拒绝继续。上游可能更新了文件，请人工确认后更新脚本里的值。",
                file=sys.stderr,
            )
            return 1

        wanted = gb2312_level1() | repository_characters()
        for low, high in EXTRA_RANGES:
            wanted.update(chr(code) for code in range(low, high + 1))
        print(
            f"保留 {len(wanted)} 个字符（其中仓库里出现过的非 ASCII 字符 {len(repository_characters())} 个）"
        )

        options = subset.Options()
        options.layout_features = ["kern", "locl", "ccmp", "vert", "vrt2", "liga"]
        options.hinting = False
        options.desubroutinize = True
        options.notdef_outline = True
        options.name_IDs = ["*"]
        font = subset.load_font(str(source), options)
        subsetter = subset.Subsetter(options)
        subsetter.populate(unicodes=[ord(c) for c in wanted])
        subsetter.subset(font)
        subset.save_font(font, str(OUTPUT_FONT), options)
        font.close()

        with TTFont(str(OUTPUT_FONT)) as result:
            cmap = result.getBestCmap()
        missing = sorted(c for c in repository_characters() if ord(c) not in cmap)
        print(
            f"输出 {OUTPUT_FONT.relative_to(REPO_ROOT)}：{OUTPUT_FONT.stat().st_size / 1024 / 1024:.2f} MB，{len(cmap)} 个字形"
        )
        if missing:
            print(f"仓库里用到、但源字体里没有的字符（{len(missing)} 个）：{''.join(missing)}")

        download(SOURCE_LICENSE_URL, OUTPUT_LICENSE)
    print(f"许可文件：{OUTPUT_LICENSE.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
