"""学生端证明题：引导 → 练习页（筛"证明题"）→ 打开证明题 → 一步一步写（每步带依据）→ 添加、挪动 →
本机草稿 → 重新打开 → 提交 → 对照参考证明 → 自查 → 学情。

题目的标题、已知、求证、参考证明、要点数量都从样题里取，不写死；服务端给的参考证明再和页面上显示的逐个核对。
"""

from __future__ import annotations

import json
import re

from e2e import data
from e2e.api_client import Api
from e2e.browser import (
    all_text,
    has,
    is_disabled,
    labels,
    onboard,
    open_flutter,
    reopen,
    stored,
    stored_all,
    tap,
    type_into,
)
from e2e.checks import say
from e2e.flowbase import Context, Flow

KEY = "math-mono-def-proof"
STAGE_LABEL = {"premise": "前提", "construction": "构造", "reasoning": "推理", "conclusion": "结论"}

# 学生写的三步：第 3 步故意没写依据；写完之后把第 3 步上移一位，所以提交的顺序是 甲、丙、乙
STEP_A = ("任取两个数，设 x1 小于 x2，都在区间里", "单调性的定义")
STEP_B = ("作差之后通分、提公因式", "通分，提公因式")
STEP_C = ("所以 f(x1) 小于 f(x2)，函数递增", "")
SUBMITTED = [STEP_A, STEP_C, STEP_B]  # 第 3 步上移之后


def _as_steps(pairs):
    return [{"text": text, "reason": reason} for text, reason in pairs]


def _open_proof_questions(page, title: str) -> None:
    """练习页里筛"证明题"，再点开这道题。"""
    tap(page, "练习", wait=2500)
    for role in ("button", "checkbox", "radio"):
        if has(page, "证明题", role=role, exact=True):
            tap(page, "证明题", role=role, exact=True, wait=2500)
            break
    tap(page, title, wait=3500)


def run(ctx: Context) -> None:
    check = ctx.check
    seed = data.question(KEY)
    title = data.title_of(KEY)
    statement = seed["content"]["proof"]
    reference = seed["answer"]["value"]["steps"]
    points = data.points_of(KEY)
    # 参考证明里没有公式的依据：页面上能直接按文字找到（含公式的文字在页面上是排版出来的，不按原文找）
    plain_reasons = [step["reason"] for step in reference if "$" not in step["reason"]]
    plain_claim = re.split(r"\$", statement["claim"])[0]

    page = ctx.new_page()

    say("== 引导，进练习页，筛证明题，打开这道题")
    open_flutter(page)
    onboard(page)
    _open_proof_questions(page, title)
    text = all_text(page)
    ctx.shot(page, "01_solve")
    token = stored(page, "auth.token")
    check("拿到了学生凭据", token)
    api = Api(token)

    say("== 题面：已知（编号）、求证；一张空白的步骤卡片；没有参考证明")
    check("有「已知」和「求证」", "已知" in text and "求证" in text, text[:300])
    check(
        f"已知按 ①②… 编号（{len(statement['givens'])} 条）",
        all("①②③④⑤⑥⑦⑧"[i] in text for i in range(len(statement["givens"]))),
        text[:300],
    )
    check("求证的文字在", plain_claim.strip() in text, plain_claim)
    check("说明这道题不自动评分、证明的写法不止一种", "不自动评分" in text and "参考证明" in text)
    check("说明每一步要写依据", "每一步写上依据" in text)
    text_boxes = page.get_by_role("textbox", name=re.compile("这一步写什么"))
    reason_boxes = page.get_by_role("textbox", name=re.compile("的依据"))
    check(
        "一开始有一张空白卡片：文字和依据各一个输入框",
        text_boxes.count() == 1 and reason_boxes.count() == 1,
    )
    check(
        "提交之前页面上没有参考证明里的依据，也没有请求过自查",
        not any(reason in text for reason in plain_reasons)
        and not [r for r in page.responses if "self-check" in r[1]],
        plain_reasons,
    )
    submit_button = page.get_by_role("button", name="提交")
    check("什么都没写，提交按钮是灰的", is_disabled(submit_button))
    check("有「添加一步」", has(page, "添加一步"))

    say("== 一步一步写：添加两步，第 3 步没写依据")
    type_into(
        page, page.get_by_role("textbox", name=re.compile("第 1 步：这一步写什么")), STEP_A[0]
    )
    type_into(page, page.get_by_role("textbox", name=re.compile("第 1 步的依据")), STEP_A[1])
    tap(page, "添加一步", wait=700)
    type_into(
        page, page.get_by_role("textbox", name=re.compile("第 2 步：这一步写什么")), STEP_B[0]
    )
    type_into(page, page.get_by_role("textbox", name=re.compile("第 2 步的依据")), STEP_B[1])
    tap(page, "添加一步", wait=700)
    type_into(
        page, page.get_by_role("textbox", name=re.compile("第 3 步：这一步写什么")), STEP_C[0]
    )
    check("写了之后提交按钮可以点", not is_disabled(submit_button))
    check(
        "现在有 3 张卡片", page.get_by_role("textbox", name=re.compile("这一步写什么")).count() == 3
    )

    say("== 挪动、删除：第 3 步上移；多加一张空白卡片再删掉")
    tap(page, "第 3 步上移", wait=800)
    tap(page, "添加一步", wait=700)
    check(
        "加了一张，现在有 4 张卡片",
        page.get_by_role("textbox", name=re.compile("这一步写什么")).count() == 4,
    )
    tap(page, "删除第 4 步", wait=800)
    check(
        "删掉空白的第 4 张，回到 3 张",
        page.get_by_role("textbox", name=re.compile("这一步写什么")).count() == 3,
    )
    ctx.shot(page, "02_written")

    say("== 先落本机：2 秒后草稿在 localStorage 里，步骤按排好的顺序")
    page.wait_for_timeout(2600)
    drafts = {key: value for key, value in stored_all(page).items() if "/draft/" in key}
    check("本机有这道题的草稿", len(drafts) == 1, list(drafts))
    local = {}
    if drafts:
        raw = json.loads(next(iter(drafts.values())))
        local = json.loads(raw) if isinstance(raw, str) else raw
    check(
        "草稿里是按顺序排好的步骤（文字和依据）",
        (local.get("answer") or {}).get("steps") == _as_steps(SUBMITTED),
        (local.get("answer") or {}).get("steps"),
    )
    page.wait_for_timeout(2500)
    check(
        "停笔后同步到云端（PUT 草稿 200）",
        any(r[0] == "PUT" and r[1].endswith("/draft") and r[2] == 200 for r in page.responses),
        page.responses[-6:],
    )

    say("== 重新打开（相当于重启）：步骤从本机恢复")
    reopen(page, "")
    _open_proof_questions(page, title)
    ctx.shot(page, "03_after_reopen")
    check("草稿状态提示在", "草稿状态" in all_text(page))
    check(
        "重新打开后有 3 张卡片",
        page.get_by_role("textbox", name=re.compile("这一步写什么")).count() == 3,
    )
    check("重新打开后提交按钮可以点（本机草稿恢复了）", not is_disabled(submit_button))

    say("== 提交")
    tap(page, "提交", wait=3500)
    text = all_text(page)
    ctx.shot(page, "04_submitted")
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
        "提交带的是重新打开后恢复的步骤（顺序是学生排的，没写的依据是空串）",
        (body.get("answer") or {}).get("steps") == _as_steps(SUBMITTED),
        body,
    )
    check("说明这道题不自动评分", "这道题不自动评分" in text, text[:300])
    check("没有判对错的措辞", not re.search(r"回答正确|没有答对|这次没答对|答对了", text))
    check('出现"对照要点自查"和"对照参考证明"', "对照要点自查" in text and "对照参考证明" in text)
    check(
        "提交后取了自查（GET /self-check 200）",
        any(r[0] == "GET" and r[1].endswith("/self-check") and r[2] == 200 for r in page.responses),
    )
    check("并排标题：你的证明、参考证明", "你的证明" in text and "参考证明" in text)
    check("说明参考证明只是一种写法", "只是一种写法" in text)
    check("没写依据的那一步明说「没写」", "依据：没写" in text)
    check(
        "参考证明的阶段标签都在（前提、构造、推理、结论）",
        all(name in text for name in STAGE_LABEL.values()),
    )

    say("== 参考证明和服务端一致")
    served = api.get(f"/attempts/{attempt_id}/self-check")["reference_steps"]
    check(f"服务端给了 {len(reference)} 步参考证明", len(served) == len(reference), len(served))
    check("服务端的参考证明就是样题里的参考证明", served == reference)
    check(
        "每个不含公式的依据都显示在页面上",
        all(reason in text for reason in plain_reasons),
        [reason for reason in plain_reasons if reason not in text],
    )
    check(
        "你的证明的每一步都显示在页面上",
        all(step[0] in text for step in SUBMITTED),
        [step[0] for step in SUBMITTED if step[0] not in text],
    )
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
    check(
        "要点按证明阶段分组，还有一组整份证明",
        all(name in all_text(page) for name in ("前提", "构造", "推理", "结论", "整份证明")),
    )
    for index in range(count):
        done_buttons.nth(index).click()
        page.wait_for_timeout(150)
    tap(page, "保存自查", wait=2500)
    text = all_text(page)
    ctx.shot(page, "05_selfcheck_saved")
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
    ctx.shot(page, "06_progress")
    check('学情页有"解答题、实验题和证明题"这一块', "解答题、实验题和证明题" in text, text[:300])
    check("提交了 1 份，其中 1 份做了对照自查", "提交了 1 份，其中 1 份做了对照自查" in text)
    check(f"自查里做到了 {total} 条", f"做到了 {total} 条" in text)
    check(
        "正确率仍然是信息不足（证明题没有进分母）",
        "信息不足" in text or "样本不足" in text or "还不够" in text,
        text[:500],
    )

    say("== 汇总")
    bad = [r for r in page.responses if r[2] >= 400]
    check("没有 4xx/5xx 响应", not bad, bad)
    check("页面没有未捕获的异常", not page.errors, page.errors)


FLOW = Flow(
    name="student_proof",
    title="学生端证明题：已知求证、一步一步写、挪动、本机草稿、提交、对照参考证明、自查、学情",
    needs=frozenset({"flutter"}),
    run=run,
)
