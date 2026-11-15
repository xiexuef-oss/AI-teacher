"""学生端实验题：引导 → 练习页 → 打开实验题 → 填表、写文字 → 本机草稿 → 重新打开 → 提交 →
对照参考数据 → 自查 → 学情。

题目的标题、数据表、参考值、要点数量都从样题里取，不写死；服务端给的参考值再和页面上显示的逐个核对。
"""

from __future__ import annotations

import json
import re

from e2e import data
from e2e.api_client import Api
from e2e.browser import (
    all_text,
    is_disabled,
    labels,
    onboard,
    open_flutter,
    reopen,
    stored,
    stored_all,
    tap,
)
from e2e.checks import say
from e2e.flowbase import Context, Flow

KEY = "phys-tape-experiment"
PART_TEXT = "T 等于 0.10 秒"
LEVEL_LABEL = {"low": "低风险", "medium": "中等风险"}


def _cell_boxes(page):
    return page.get_by_role("textbox", name=re.compile("请填写"))


def run(ctx: Context) -> None:
    check = ctx.check
    title = data.title_of(KEY)
    content = data.question(KEY)["content"]
    safety = content["safety"]
    cells = data.blank_cells(KEY)
    points = data.points_of(KEY)
    subquestions = content["subquestions"]
    table_titles = [table["title"] for table in content["data_tables"]]
    given = [
        cell["text"]
        for table in content["data_tables"]
        for row in table["rows"]
        for cell in row["cells"]
        if cell["text"]
    ][:2]
    # 填三个格子：第 1 个（和参考值不一样）、第 2 个（只是少了尾巴的 0）、最后一个（和参考值一样）；其余留空
    typed = {0: "0.41", 1: "0.6", len(cells) - 1: "2.00"}
    filled = {cells[index]: value for index, value in typed.items()}
    submitted_cells = [
        {"table": table, "row": row, "col": col, "value": filled[(table, row, col)]}
        for table, row, col in cells
        if (table, row, col) in filled
    ]
    local_cells = {f"{table}.{row}.{col}": value for (table, row, col), value in filled.items()}

    page = ctx.new_page()

    say("== 引导，进练习页，打开实验题")
    open_flutter(page)
    onboard(page)
    tap(page, "练习", wait=2500)
    tap(page, title, wait=3500)
    text = all_text(page)
    ctx.shot(page, "01_solve")
    token = stored(page, "auth.token")
    check("拿到了学生凭据", token)
    api = Api(token)

    say("== 题面：安全提示、数据表、留空格子的输入框")
    check(
        "安全提示在题干下面，带风险等级",
        "实验安全提示" in text and LEVEL_LABEL[safety["level"]] in text,
        text[:300],
    )
    check("安全提示的每一条都在", all(note in text for note in safety["notes"]))
    check("安全提示说明这是纸面练习、不是操作指导", "不是操作指导" in text)
    check("数据表的标题都在", all(name in text for name in table_titles), table_titles)
    check("题目给定的数据是文字", all(value in text for value in given), given)
    boxes = _cell_boxes(page)
    check(
        f"留空的格子各有一个输入框（{len(cells)} 个）", boxes.count() == len(cells), boxes.count()
    )
    reference = {value for value in data.reference_values(KEY).values() if len(value) >= 3}
    check(
        '提交前页面上没有参考数据和"你填的"',
        "你填的" not in text
        and "没填" not in text
        and not any(value in text for value in reference),
    )
    check("提交前没有请求自查要点", not [r for r in page.responses if "self-check" in r[1]])
    submit_button = page.get_by_role("button", name="提交")
    check("什么都没填，提交按钮是灰的", is_disabled(submit_button))

    say("== 填格子，写第 1 问")
    for index, value in typed.items():
        _cell_boxes(page).nth(index).click()
        page.keyboard.type(value)
        page.wait_for_timeout(300)
    part_boxes = [
        box
        for box in page.get_by_role("textbox").all()
        if "请填写" not in (box.get_attribute("aria-label") or "")
    ]
    check("文字小问各有一个输入框", len(part_boxes) == len(subquestions), len(part_boxes))
    part_boxes[0].click()
    page.keyboard.type(PART_TEXT)
    page.wait_for_timeout(300)
    check("填了之后提交按钮可以点", not is_disabled(submit_button))

    say("== 先落本机：2 秒后草稿在 localStorage 里，格子在里面")
    page.wait_for_timeout(2600)
    drafts = {key: value for key, value in stored_all(page).items() if "/draft/" in key}
    check("本机有这道题的草稿", len(drafts) == 1, list(drafts))
    local = {}
    if drafts:
        raw = json.loads(next(iter(drafts.values())))
        local = json.loads(raw) if isinstance(raw, str) else raw
    check(
        "草稿里是 表.行.列 为键的格子",
        (local.get("answer") or {}).get("cells") == local_cells,
        (local.get("answer") or {}).get("cells"),
    )
    page.wait_for_timeout(2500)
    check(
        "停笔后同步到云端（PUT 草稿 200）",
        any(r[0] == "PUT" and r[1].endswith("/draft") and r[2] == 200 for r in page.responses),
        page.responses[-6:],
    )

    say("== 重新打开（相当于重启）：格子从本机恢复")
    reopen(page, "")
    tap(page, "练习", wait=2500)
    tap(page, title, wait=3500)
    ctx.shot(page, "02_after_reopen")
    check("草稿状态提示在", "草稿状态" in all_text(page))
    check("重新打开后提交按钮可以点（本机草稿恢复了）", not is_disabled(submit_button))

    say("== 提交")
    tap(page, "提交", wait=3500)
    text = all_text(page)
    ctx.shot(page, "03_submitted")
    attempt_id = next(
        (
            re.search(r"/attempts/([^/]+)/", r[1]).group(1)
            for r in page.responses
            if "/attempts/" in r[1]
        ),
        None,
    )
    submit_calls = [r for r in page.responses if r[1].endswith("/submit")]
    check(
        "提交成功（POST /submit 2xx）",
        submit_calls and submit_calls[-1][2] in (200, 201),
        submit_calls,
    )
    body = page.submit_bodies[-1] if page.submit_bodies else {}
    check(
        "提交带的是重新打开后恢复的格子（按表、行、列的顺序）和第 1 问",
        (body.get("answer") or {}).get("cells") == submitted_cells
        and (body.get("answer") or {}).get("parts")
        == [{"key": subquestions[0]["key"], "text": PART_TEXT}],
        body,
    )
    check("说明这道题不自动评分", "这道题不自动评分" in text, text[:300])
    check("没有判对错的措辞", not re.search(r"回答正确|没有答对|这次没答对|答对了", text))
    check('出现"对照要点自查"和"对照参考数据"', "对照要点自查" in text and "对照参考数据" in text)
    check(
        "提交后取了自查（GET /self-check 200）",
        any(r[0] == "GET" and r[1].endswith("/self-check") and r[2] == 200 for r in page.responses),
    )
    check("并排标题：你填的、参考数据", "你填的" in text and "参考数据" in text)
    blank_count = len(cells) - len(filled)
    check(
        f'没填的格子写明"没填"（{blank_count} 格）',
        text.count("没填") >= blank_count,
        text.count("没填"),
    )
    check("参考数据不是评分的说明", "不是评分" in text)

    say("== 参考数据和服务端一致")
    served = api.get(f"/attempts/{attempt_id}/self-check")["reference_cells"]
    check(f"服务端给了 {len(cells)} 个留空格子的参考值", len(served) == len(cells), served)
    check(
        "服务端的参考值就是样题里的参考值",
        {(c["table"], c["row"], c["col"]): c["value"] for c in served}
        == data.reference_values(KEY),
    )
    check(
        "每个参考值都显示在页面上",
        all(c["value"] in text for c in served),
        [c["value"] for c in served if c["value"] not in text],
    )
    check("你填的数和参考值并排显示", all(value in text for value in typed.values()))
    check(
        "本机草稿提交后已清除",
        not [key for key in stored_all(page) if "/draft/" in key and "draft-corrupt" not in key],
    )

    say("== 自查：每一条标做到了，保存")
    chip_lines = [line for line in labels(page) if line.endswith("| 做到了")]
    chip_role = re.match(r"([a-z]+)", chip_lines[0]).group(1) if chip_lines else "button"
    done_buttons = page.get_by_role(chip_role, name="做到了", exact=True)
    count = done_buttons.count()
    check(f"每个要点一组选项（{len(points)} 条）", count == len(points), count)
    for index in range(count):
        done_buttons.nth(index).click()
        page.wait_for_timeout(150)
    tap(page, "保存自查", wait=2500)
    text = all_text(page)
    ctx.shot(page, "04_selfcheck_saved")
    check(
        "保存成功（PUT /self-check 200）",
        any(r[0] == "PUT" and r[1].endswith("/self-check") and r[2] == 200 for r in page.responses),
        page.responses[-5:],
    )
    total = len(points)
    check(
        "只显示三档计数，没有分数",
        f"做到了 {total}" in text
        and "做到一部分 0" in text
        and "没做到 0" in text
        and "得分" not in text,
        text[-300:],
    )

    say("== 学情页：只有计数，仍然没有比例")
    reopen(page, "#/progress")
    text = all_text(page)
    ctx.shot(page, "05_progress")
    check('学情页有"解答题和实验题"这一块', "解答题和实验题" in text, text[:300])
    check("提交了 1 份，其中 1 份做了对照自查", "提交了 1 份，其中 1 份做了对照自查" in text)
    check(f"自查里做到了 {total} 条", f"做到了 {total} 条" in text)
    check(
        "正确率仍然是信息不足（实验题没有进分母）",
        "信息不足" in text or "样本不足" in text or "还不够" in text,
        text[:500],
    )

    say("== 汇总")
    bad = [r for r in page.responses if r[2] >= 400]
    check("没有 4xx/5xx 响应", not bad, bad)
    check("页面没有未捕获的异常", not page.errors, page.errors)


FLOW = Flow(
    name="student_experiment",
    title="学生端实验题：填表、本机草稿、提交、对照参考数据、自查、学情",
    needs=frozenset({"flutter"}),
    run=run,
)
