"""Run a fixed, self-authored image probe against the configured DeepSeek adapter."""

import argparse
import base64
import io
import os
import re
import time
import unicodedata
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageDraw, ImageFont
from setup_deepseek import load_environment, read_key

from ai_gateway import Constraints, GatewayRequest, InputPart, ProviderError, TaskType
from ai_gateway.providers import OpenAICompatAdapter

CASES = (
    ("equation", ("7. Solve 9x + 14 = 77.",), 0),
    ("units", ("8. A train travels 84 m in 12 s.", "Find its average speed."), 0),
    ("two_columns", ("9. Expand (x + 3)^2.", "10. Simplify 18 / 6."), 2),
    ("tilted", ("11. Given p = 5 and q = 13,", "find 2q - p."), -7),
    ("zh_physics", ("12. 小车在 4 s 内运动 12 m。", "求小车的平均速度，单位为 m/s。"), -3),
    (
        "zh_dense",
        (
            "13. 已知函数 f(x) = 2x + 1。",
            "（1）求 f(3) 的值。",
            "（2）若 f(x) = 9，求 x。",
            "14. 将 24 g 水分成 3 份。",
            "（1）求每份的质量。",
            "（2）写出质量的单位。",
        ),
        0,
    ),
    (
        "zh_red_no_score",
        ("15. 将 x = −3 代入函数。", "作答  y = −5", "检查负号"),
        -4,
    ),
)

CJK_FONT = (
    Path(__file__).resolve().parents[1] / "apps/flutter_student/assets/fonts/NotoSansSC-Subset.otf"
)


def image_part(lines, angle, *, columns=False, chinese=False, red_last=False, region=None):
    image = Image.new("RGB", (740, 180), "white")
    draw = ImageDraw.Draw(image)
    size = 18 if len(lines) > 3 else 30
    font = ImageFont.truetype(str(CJK_FONT), size) if chinese else ImageFont.load_default(size=size)
    for index, line in enumerate(lines):
        point = (24 + index * 355, 25) if columns else (24, 16 + index * (size + 6))
        color = "firebrick" if red_last and index == len(lines) - 1 else "black"
        draw.text(point, line, fill=color, font=font)
    if region is not None:
        boundary = 16 + (len(lines) - 1) * (size + 6)
        top, bottom = (0, boundary) if region == "student" else (boundary, image.height)
        crop = image.crop((0, top, image.width, bottom))
        image = Image.new("RGB", image.size, "white")
        image.paste(crop, (0, 0))
    buffer = io.BytesIO()
    image.rotate(angle, resample=Image.Resampling.BICUBIC, fillcolor="white").save(
        buffer, format="PNG"
    )
    return InputPart(
        kind="image_ref",
        media_ref="data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii"),
    )


def normalized(text):
    return "".join(unicodedata.normalize("NFKC", text).split())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=[case[0] for case in CASES], action="append")
    parser.add_argument(
        "--separate-red-ink",
        action="store_true",
        help="Transcribe two preselected regions of the authored red-ink fixture separately.",
    )
    args = parser.parse_args()
    selected = args.case
    if args.separate_red_ink and selected != ["zh_red_no_score"]:
        parser.error("--separate-red-ink requires --case zh_red_no_score")
    cases = [case for case in CASES if not selected or case[0] in selected]
    load_environment()
    secret = read_key()
    if not secret:
        raise SystemExit("DeepSeek credentials unavailable")
    endpoint = os.environ["DEEPSEEK_BASE_URL"]
    if endpoint.rstrip("/") != "https://api.deepseek.com":
        raise SystemExit("Use the designated DeepSeek endpoint")
    adapter = OpenAICompatAdapter(base_url=endpoint, api_key=secret)
    tasks = [
        (name, lines, angle, region)
        for name, lines, angle in cases
        for region in (("student", "teacher") if args.separate_red_ink else (None,))
    ]
    matched = 0
    for name, lines, angle, region in tasks:
        request_id = uuid4().hex
        request = GatewayRequest(
            request_id=request_id,
            trace_id=request_id,
            student_pseudonym="engineering-fixture",
            task_type=TaskType.OCR_EXTRACT,
            constraints=Constraints(max_output_tokens=1600 if len(lines) > 3 else 800),
            input_parts=[
                InputPart(
                    kind="text",
                    text="Transcribe all visible text exactly in reading order in stem_text. "
                    "Keep original punctuation and formulas. Return JSON. Do not solve.",
                ),
                image_part(
                    lines,
                    angle,
                    columns=name == "two_columns",
                    chinese=name.startswith("zh_"),
                    red_last=name == "zh_red_no_score",
                    region=region,
                ),
            ],
        )
        start = time.monotonic()
        try:
            result = adapter.invoke(
                model=os.environ["DEEPSEEK_MODEL_FLASH"], request=request, timeout_s=45
            )
        except ProviderError as error:
            print(f"{name} error={error.kind}")
            continue
        actual = result.output.get("stem_text")
        if region is not None:
            expected = "\n".join(lines[:-1] if region == "student" else lines[-1:])
            match = isinstance(actual, str) and normalized(actual).replace("−", "-") == normalized(
                expected
            ).replace("−", "-")
            matched += match
            print(
                f"{name} region={region} match={match} input_tokens={result.input_tokens} output_tokens={result.output_tokens}"
            )
            continue
        match = isinstance(actual, str) and normalized(actual) == normalized("\n".join(lines))
        matched += match
        print(
            f"{name} exact={match} input_tokens={result.input_tokens} "
            f"output_tokens={result.output_tokens} elapsed_ms={round((time.monotonic() - start) * 1000)}"
        )
        if name == "zh_red_no_score" and isinstance(actual, str):
            transcript = normalized(actual)
            signs = set(re.findall(r"-[35]", transcript.replace("−", "-")))
            negatives_preserved = {"-3", "-5"} <= signs
            print(
                f"{name} annotation_present={normalized(lines[-1]) in transcript} "
                f"negative_values_preserved={negatives_preserved}"
            )
    metric = "region_matches" if args.separate_red_ink else "exact_matches"
    print(f"{metric}={matched}/{len(tasks)}")
    return 0 if matched == len(tasks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
