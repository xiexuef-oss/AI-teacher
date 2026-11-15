"""审核后台里的实验题：队列 → 审核页（安全提示、数据表、参考值、要点）→ 下线 → 改安全提示存成新版本 →
版本对比 → 改成高风险，程序校验必须拦住。

安全提示、表、参考值、要点的数量都从样题里取，不写死。
"""

from __future__ import annotations

from e2e import data
from e2e.checks import say
from e2e.flowbase import Context, Flow
from e2e.servers import ADMIN_URL

KEY = "chem-titration-experiment"
NEW_NOTE = "联调新增：废液按老师的要求倒进指定的回收容器。"


def _saved(page, version: int) -> None:
    """等"已保存为第 N 版"出现。页面上先前的提示（比如"下线"之后的）也在 done 里，所以要等具体的文字。"""
    page.wait_for_function(
        "(v) => (document.querySelector('[data-testid=done]')?.innerText || '').includes(v)",
        arg=f"已保存为第 {version} 版",
        timeout=15000,
    )


def run(ctx: Context) -> None:
    check = ctx.check
    title = data.title_of(KEY)
    content = data.question(KEY)["content"]
    safety = content["safety"]
    notes = safety["notes"]
    cells = data.blank_cells(KEY)
    references = data.reference_values(KEY)
    points = data.points_of(KEY)
    first_cell, last_cell = cells[0], cells[-1]
    given_cell = next(
        (table["key"], row["key"], cell["col"], cell["text"])
        for table in content["data_tables"]
        for row in table["rows"]
        for cell in row["cells"]
        if cell["text"]
    )

    page = ctx.new_admin_page()

    say("== 登录审核员，打开队列里的实验题")
    page.goto(ADMIN_URL)
    page.get_by_test_id("sign-in-reviewer").click()
    page.wait_for_selector("[data-testid=queue]", timeout=20000)
    page.get_by_test_id("tab-published").click()
    page.wait_for_timeout(1200)
    # 队列每页 20 道：要翻完所有页才数得全
    while page.get_by_test_id("more").count():
        page.get_by_test_id("more").click()
        page.wait_for_timeout(1000)
    queue = page.get_by_test_id("queue")
    check(
        f"已上线共 {data.published_count()} 道（样题里发布的数量）",
        queue.locator("tbody tr").count() == data.published_count(),
        queue.locator("tbody tr").count(),
    )
    check(
        f"其中实验题 {data.published_count('experiment')} 道",
        queue.locator("tbody tr", has_text="实验题").count() == data.published_count("experiment"),
    )
    page.locator("tr", has_text=title).click()
    page.wait_for_selector("[data-testid=safety-view]", timeout=15000)
    page.wait_for_timeout(800)
    ctx.shot(page, "01_view")

    say("== 审核页：安全提示、数据表、参考数据、要点")
    safety_view = page.get_by_test_id("safety-view")
    check(
        f"安全提示带风险等级 {safety['level']}",
        f"风险等级 {safety['level']}" in safety_view.inner_text(),
    )
    check("安全提示的每一条都在", all(note in safety_view.inner_text() for note in notes))
    check(f"安全提示有 {len(notes)} 条", safety_view.locator("li").count() == len(notes))
    tables = content["data_tables"]
    check(
        f"有 {len(tables)} 张数据表",
        all(page.get_by_test_id(f"table-{table['key']}").count() == 1 for table in tables),
    )
    given_table, given_row, given_col, given_text = given_cell
    check(
        "题目给定的数据是文字",
        given_text in page.get_by_test_id(f"table-{given_table}").inner_text(),
        given_text,
    )
    for label, cell in (("第一个", first_cell), ("最后一个", last_cell)):
        text = page.get_by_test_id("blank-" + "-".join(cell)).inner_text()
        check(
            f"{label}留空的格子标明学生填写，并显示参考值 {references[cell]}",
            "学生填写" in text and references[cell] in text,
            text,
        )
    check(
        f"一共 {len(cells)} 个留空的格子",
        page.locator("[data-testid^=blank-]").count() == len(cells),
    )
    check(
        "给定的格子没有被标成留空",
        page.get_by_test_id(f"blank-{given_table}-{given_row}-{given_col}").count() == 0,
    )
    rubric = page.get_by_test_id("rubric-points")
    check(f"自查要点有 {len(points)} 条，不带分值", rubric.locator("li").count() == len(points))
    check(
        "要点页写明不是评分标准",
        "不是评分标准" in rubric.inner_text() and "实验题不自动评分" in rubric.inner_text(),
    )
    check("程序校验通过", "✓ 通过" in page.get_by_test_id("checks").inner_text())
    check("已上线的题不能直接编辑", page.get_by_test_id("edit").is_disabled())

    say("== 下线（必须写原因），再编辑安全提示")
    page.get_by_role("radio", name="下线").check()
    page.get_by_test_id("comment").last.fill("联调：下线之后修改安全提示")
    page.get_by_test_id("submit-decision").click()
    page.wait_for_function(
        "() => (document.body.innerText || '').includes('已下线')", timeout=15000
    )
    check("下线成功", "已下线" in page.inner_text("body"))
    check("下线之后可以编辑", not page.get_by_test_id("edit").is_disabled())
    page.get_by_test_id("edit").click()
    page.wait_for_selector("[data-testid=editor]", timeout=10000)
    page.wait_for_timeout(600)
    ctx.shot(page, "02_editor")
    check(
        "编辑器里有安全提示、数据表和留空格子的参考值",
        all(
            page.get_by_test_id(name).count() == 1
            for name in ("safety", "data-tables", "data-tables-json", "reference-cells-json")
        ),
    )
    check(
        "数据表那段 JSON 里留空的格子是 null",
        '"text": null' in page.get_by_test_id("data-tables-json").input_value(),
    )
    key = ".".join(first_cell)
    check(
        "参考值那段 JSON 的键是 表键.行键.列键",
        f'"{key}": "{references[first_cell]}"'
        in page.get_by_test_id("reference-cells-json").input_value(),
    )
    check("没改动时不能保存", page.get_by_test_id("save").is_disabled())
    boxes = page.get_by_test_id("safety").locator("textarea")
    check(f"安全提示 {len(notes)} 条，一条一个文本框", boxes.count() == len(notes), boxes.count())
    page.get_by_test_id("safety").get_by_test_id("add-item").click()
    page.wait_for_timeout(300)
    page.get_by_test_id("safety").locator("textarea").nth(len(notes)).fill(NEW_NOTE)
    page.get_by_test_id("comment").last.fill("联调：补一条安全提示")
    page.wait_for_timeout(500)
    check("改了之后可以保存", not page.get_by_test_id("save").is_disabled())
    page.get_by_test_id("save").click()
    _saved(page, 2)
    done = page.get_by_test_id("done").inner_text()
    check("保存成新版本（第 2 版），回到待审", "第 2 版" in done and "待审" in done, done)
    check(
        f"新版本的安全提示是 {len(notes) + 1} 条",
        page.get_by_test_id("safety-view").locator("li").count() == len(notes) + 1,
    )
    check(
        "新版本数据表和参考值还在",
        all(page.get_by_test_id(f"table-{table['key']}").count() == 1 for table in tables)
        and references[last_cell]
        in page.get_by_test_id("blank-" + "-".join(last_cell)).inner_text(),
    )
    check("新版本程序校验通过", "✓ 通过" in page.get_by_test_id("checks").inner_text())

    say("== 对比两个版本")
    page.get_by_test_id("saved-compare").click()
    page.wait_for_selector("[data-testid=summary]", timeout=10000)
    page.wait_for_timeout(800)
    ctx.shot(page, "03_compare")
    check("对比页能看到新增的那条安全提示", NEW_NOTE in page.inner_text("body"))
    check("对比页有改动汇总", page.get_by_test_id("summary").inner_text().strip() != "")
    changed = [
        element.get_attribute("data-testid")
        for element in page.locator("[data-testid^=field-].changed").all()
    ]
    say("   有改动的字段：", changed)
    check("安全提示那一行有改动", "field-safety" in changed, changed)
    check("数据表那一行没有改动", "field-data_tables" not in changed, changed)
    check("标准答案（含留空格子的参考值）没有改动", "field-answer" not in changed, changed)

    say("== 把安全级别改成 high：程序校验必须拦住")
    page.get_by_test_id("back-question").click()
    page.wait_for_selector("[data-testid=edit]", timeout=10000)
    page.get_by_test_id("edit").click()
    page.wait_for_selector("[data-testid=editor]", timeout=10000)
    page.get_by_test_id("safety-level").select_option("high")
    page.get_by_test_id("comment").last.fill("联调：试一下高风险")
    page.wait_for_timeout(400)
    page.get_by_test_id("save").click()
    _saved(page, 3)
    checks_text = page.get_by_test_id("checks").inner_text()
    ctx.shot(page, "04_high_risk")
    check("保存成第 3 版", "第 3 版" in page.get_by_test_id("done").inner_text())
    check(
        "程序校验指出高风险实验不收录",
        "high" in checks_text and "不收录" in checks_text and "发现" in checks_text,
        checks_text,
    )
    check("决策面板还在（审核不会被悄悄放行）", page.get_by_test_id("decision-panel").count() == 1)

    say("== 汇总")
    bad = [r for r in page.responses if r[2] >= 400]
    check("没有 4xx/5xx 响应", not bad, bad)
    check("页面没有未捕获的异常或控制台错误", not page.errors, page.errors)


FLOW = Flow(
    name="admin_experiment",
    title="审核后台实验题：查看、下线、改安全提示存新版本、版本对比、高风险拦截",
    needs=frozenset({"admin"}),
    run=run,
)
