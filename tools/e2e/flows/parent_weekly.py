"""家长周报：学生生成邀请码授权 → 家长（另一个浏览器上下文）输入邀请码、看周报、翻周 →
学生撤销 → 家长什么都看不到 → 再授权。

学生的作答用后端接口造（几份对、几份错、一份解答题），周报里的数字从这份计划推出来，不写死。
"""

from __future__ import annotations

import re

from e2e import data
from e2e.api_client import Api, seed_attempt
from e2e.browser import (
    all_text,
    find_text,
    has,
    is_disabled,
    onboard,
    open_flutter,
    reopen,
    stored,
    tap,
    type_into,
)
from e2e.checks import say
from e2e.flowbase import Context, Flow

# (样题, 作答)：correct / wrong 是客观题，written 是解答题
PLAN: list[tuple[str, str]] = [
    ("math-mono-judge", "correct"),
    ("math-ineq-min", "correct"),
    ("chem-conservation-co2", "correct"),
    ("phys-newton2-force", "wrong"),
    ("math-mono-quadratic", "wrong"),
    ("math-quadratic-param-written", "written"),
]
INVITE_CODE = r"[2-9A-HJKMNP-Z]{5} [2-9A-HJKMNP-Z]{5}"


def expected_weekly(plan: list[tuple[str, str]] | None = None) -> dict[str, int]:
    """周报里该出现的数字：开始的练习、提交的作答、解答题、独立正确率。"""
    plan = PLAN if plan is None else plan
    objective = [kind for _, kind in plan if kind != "written"]
    correct = objective.count("correct")
    return {
        "attempts": len(plan),
        "written": len(plan) - len(objective),
        "independent_total": len(objective),
        "independent_correct": correct,
        "rate": round(100 * correct / len(objective)),
    }


def run(ctx: Context) -> None:
    check = ctx.check
    expected = expected_weekly()
    titles = [data.title_of(key) for key, _ in PLAN]

    say("== 学生：引导")
    student = ctx.new_page()
    open_flutter(student)
    onboard(student)
    token = stored(student, "auth.token")
    student_id = stored(student, "auth.userId")
    check("学生本机存了凭据，角色是学生", token and stored(student, "auth.role") == "student")

    say("== 学生：用后端接口补作答（几份对、几份错、一份解答题）")
    api = Api(token)
    for key, kind in PLAN:
        seed_attempt(api, key, data.answer_for(key, kind))

    say("== 学生：我的页——称呼、家长查看、生成邀请码")
    reopen(student, "#/profile")
    type_into(student, student.get_by_role("textbox", name="你的称呼"), "小明")
    tap(student, "保存", exact=True, wait=1800)
    check("称呼随资料保存（PUT /profile 200）", ("PUT", "/profile", 200) in student.responses)
    text = all_text(student)
    check(
        '我的页有"家长查看"，说清楚家长只看汇总、可随时撤销',
        "只能看到你授权的" in text and "随时撤销" in text,
    )
    check("还没有授权任何家长", "还没有授权任何家长" in text)
    tap(student, "生成邀请码", wait=2200)
    code_shown = find_text(student, INVITE_CODE)
    check("弹窗里是五位一组的十位邀请码", code_shown is not None)
    ctx.shot(student, "01_invite_dialog")
    check(
        "弹窗说明有效期、一次有效、重新生成会让旧的失效",
        "重新生成会让这一个失效" in all_text(student),
    )
    code = (code_shown or "").replace(" ", "")
    tap(student, "我知道了", wait=1000)
    check(
        "关掉之后哪里都看不到邀请码",
        code_shown not in all_text(student) and code not in all_text(student),
    )
    check('但看得到"有一个还没用掉的邀请码"', "有一个还没用掉的邀请码" in all_text(student))

    say("== 家长（另一个浏览器上下文）：先用学生身份打开家长页，会被挡住")
    parent = ctx.new_page()
    open_flutter(parent, "#/parent")
    check("学生身份打开家长页：只给一句说明", "这是家长看的页面" in all_text(parent))
    check(
        "……而且没有请求任何家长接口",
        not [r for r in parent.responses if r[1].startswith("/parents")],
        parent.responses,
    )
    first_student_in_parent_context = stored(parent, "auth.userId")

    say('== 家长：从"我的"切到家长身份（本机演示）')
    reopen(parent, "#/profile")
    tap(parent, "切换到家长身份", wait=3500)
    check("进了家长首页", "已授权的学生" in all_text(parent))
    check(
        "本机存了家长身份，学生身份收在 other 里",
        stored(parent, "auth.role") == "parent"
        and stored(parent, "auth.other.role") == "student"
        and stored(parent, "auth.other.userId") == first_student_in_parent_context,
    )
    check(
        "切身份没有产生任何 4xx/5xx",
        not [r for r in parent.responses if r[2] >= 400],
        [r for r in parent.responses if r[2] >= 400],
    )
    check(
        "家长没有再请求学生的资料",
        [r for r in parent.responses if r[1] == "/profile"] == [("GET", "/profile", 200)],
    )
    check(
        "家长页说明了只看汇总、可撤销、原型",
        all(word in all_text(parent) for word in ("汇总", "撤销", "原型")),
    )
    check("还没有授权：说明怎么拿邀请码", "还没有学生授权给你" in all_text(parent))
    ctx.shot(parent, "02_parent_home_empty")

    say("== 家长：输入邀请码（小写、带空格）并绑定")
    invite_box = parent.get_by_role("textbox", name="邀请码")
    type_into(parent, invite_box, code[:5].lower() + " " + code[5:].lower())
    tap(parent, "绑定", exact=True, wait=3200)
    check(
        "绑定成功（POST /parents/links 201）",
        ("POST", "/parents/links", 201) in parent.responses,
        parent.responses[-4:],
    )
    check("出现这位学生，用的是学生设置的称呼", has(parent, "小明", role="button"))
    linked_text = all_text(parent)
    check(
        "明确确认原绑定，并说明当前授权以上方列表为准",
        "原绑定操作已确认" in linked_text
        and "目前可查看的学生以上方授权列表为准" in linked_text
        and has(parent, "小明", role="button"),
    )
    ctx.shot(parent, "03_parent_home_linked")

    say("== 家长：看周报")
    tap(parent, "小明", wait=3500)
    text = all_text(parent)
    ctx.shot(parent, "04_weekly_current")
    check("周报里有这一周的起止日期", re.search(r"\d+月\d+日 – \d+月\d+日", text) is not None)
    check("这一周还没结束", "这一周还没结束" in text)
    check("有作答的天数 1 天", "有作答的天数" in text and "1 天" in text)
    check(f"开始的练习 {expected['attempts']} 次", f"{expected['attempts']} 次" in text)
    check(f"提交作答 {expected['attempts']} 份", f"{expected['attempts']} 份" in text)
    check(
        f"独立正确率 {expected['rate']}%（{expected['independent_correct']}/{expected['independent_total']}）",
        f"{expected['rate']}%" in text
        and f"{expected['independent_correct']}/{expected['independent_total']}" in text,
        text[:400],
    )
    check(
        "提示依赖率、复测成功率、辅助正确率都在",
        all(w in text for w in ("提示依赖率", "复测成功率", "辅助正确率")),
    )
    check(
        f"解答题、实验题和证明题只说 {expected['written']} 份、不自动评分、不进比例",
        f"解答题、实验题和证明题 {expected['written']} 份" in text and "不自动评分" in text,
    )
    check("趋势：上一周没有数据，暂时比不了", "暂时比不了" in text)
    check("按科目", "按科目" in text)
    check("说明不是官方成绩", "不是官方成绩" in text)
    check("周报里没有题目标题（家长只看汇总）", not any(title in text for title in titles), titles)
    check(
        "下一周按钮是灰的（当前这一周）",
        is_disabled(parent.get_by_role("button", name="下一周")),
    )

    say("== 家长：翻到上一周，再回来")
    tap(parent, "上一周", wait=3000)
    text = all_text(parent)
    ctx.shot(parent, "05_weekly_previous")
    check(
        "上一周：这一周已经结束，还没有学习记录",
        "这一周已经结束" in text and "这一周还没有学习记录" in text,
    )
    check("上一周请求带了 week_start", any("week_start=" in r[1] for r in parent.responses))
    tap(parent, "下一周", wait=3000)
    check("回到当前这一周", "这一周还没结束" in all_text(parent))
    weekly_requests = [r for r in parent.responses if "/weekly" in r[1]]
    check("周报请求都是 200", all(r[2] == 200 for r in weekly_requests), weekly_requests)

    say("== 学生：我的页看到授权，撤销（先确认）")
    reopen(student, "#/profile")
    text = all_text(student)
    ctx.shot(student, "06_student_link")
    check("学生看到一位授权的家长", "家长 " in text and "授权，可以看每周汇总" in text)
    tap(student, "撤销", exact=True, wait=1500)
    text = all_text(student)
    ctx.shot(student, "07_revoke_dialog")
    check("撤销要先确认，说明立刻看不到", "立刻就看不到你的周报" in text)
    tap(student, "取消", exact=True, wait=1200)
    check("取消之后授权还在", "授权，可以看每周汇总" in all_text(student))
    tap(student, "撤销", exact=True, wait=1500)
    tap(student, "撤销授权", exact=True, wait=2500)
    check(
        "撤销请求成功（POST …/revoke 200）",
        any(r[0] == "POST" and r[1].endswith("/revoke") and r[2] == 200 for r in student.responses),
        student.responses[-4:],
    )
    check('撤销后这一行消失，又是"还没有授权任何家长"', "还没有授权任何家长" in all_text(student))

    say("== 家长：刷新周报页，什么都看不到")
    reopen(parent, "#/parent/weekly/" + student_id)
    text = all_text(parent)
    ctx.shot(parent, "08_weekly_revoked")
    check(
        "看不到这位学生的周报，说明授权已经撤销",
        "看不到这位学生的周报" in text and "授权已经撤销" in text,
    )
    check(
        "页面上没有任何数据",
        not any(w in text for w in ("独立正确率", f"{expected['rate']}%", "提交作答")),
    )
    last = [r for r in parent.responses if "/weekly" in r[1]][-1]
    check("服务端是 404", last[2] == 404, last)
    tap(parent, "回到家长页", wait=3000)
    text = all_text(parent)
    check(
        "家长首页上这位学生没有了",
        not has(parent, "小明", role="button") and "还没有学生授权给你" in text,
    )

    say("== 再授权：学生生成新码，家长输入；旧码已经用过")
    reopen(student, "#/profile")
    tap(student, "生成邀请码", wait=2200)
    code2 = find_text(student, INVITE_CODE)
    check("第二个邀请码和第一个不一样", code2 and code2.replace(" ", "") != code)
    tap(student, "我知道了", wait=1000)
    type_into(parent, invite_box, code2 or "")
    tap(parent, "绑定", exact=True, wait=3200)
    check("重新授权成功，又能看到这位学生", has(parent, "小明", role="button"))
    type_into(parent, invite_box, code)
    tap(parent, "绑定", exact=True, wait=2500)
    check(
        "旧码（已经用过）：只说邀请码不对或已失效",
        "邀请码不对，或者已经过期、已经被用过" in all_text(parent),
    )
    ctx.shot(parent, "09_old_code")
    tap(parent, "小明", wait=3500)
    check(
        "重新授权之后周报又能看",
        "有作答的天数" in all_text(parent) and f"{expected['rate']}%" in all_text(parent),
    )

    say("== 家长：切回学生身份，还是原来那个学生")
    open_flutter(parent, "#/parent")
    before = len(parent.responses)
    tap(parent, "切换到学生身份", wait=3500)
    check(
        "切回学生：学生身份还是原来那个",
        stored(parent, "auth.userId") == first_student_in_parent_context
        and stored(parent, "auth.role") == "student",
    )
    check("家长身份收进了 other", stored(parent, "auth.other.role") == "parent")
    after = parent.responses[before:]
    check("切回学生没有产生任何 4xx/5xx", not [r for r in after if r[2] >= 400], after)

    say("== 汇总所有响应")
    bad = [r for r in student.responses + parent.responses if r[2] >= 400]
    say("非 2xx 响应:", bad)
    check(
        "所有非 2xx 都是预期的（撤销后的 404、旧邀请码的 404）",
        all(r[2] in {404, 409} for r in bad),
        bad,
    )
    check(
        "页面没有未捕获的异常",
        not student.errors and not parent.errors,
        student.errors + parent.errors,
    )


FLOW = Flow(
    name="parent_weekly",
    title="家长周报：学生授权、家长看周报与翻周、撤销、再授权",
    needs=frozenset({"flutter"}),
    run=run,
)
