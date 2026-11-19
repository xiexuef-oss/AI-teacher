"""First-learning choice and actual knowledge filtering, without ability claims."""

from urllib.parse import parse_qs, urlsplit

from e2e import data
from e2e.api_client import Api, seed_attempt
from e2e.browser import all_text, onboard, open_flutter, reopen, stored
from e2e.flowbase import Flow
from e2e.flows.student_draft_recovery import _wait


def click(page, text):
    for role in ("menuitem", "option", "radio", "checkbox", "button", "combobox"):
        found = page.get_by_role(role, name=text, exact=True)
        if found.count():
            found.last.click()
            page.wait_for_timeout(500)
            return
    page.get_by_text(text, exact=True).last.click()
    page.wait_for_timeout(500)


def question_response(response, **wanted):
    parts = urlsplit(response.url)
    query = parse_qs(parts.query)
    return (
        response.request.method == "GET"
        and parts.path.endswith("/questions")
        and all(query.get(key) == [value] for key, value in wanted.items())
    )


def run(ctx):
    page = ctx.new_page()
    open_flutter(page)
    onboard(page)
    api = Api(stored(page, "auth.token"))
    ctx.check("新学生显示首次学习选择", _wait(page, lambda: "按知识点选题" in all_text(page)))
    ctx.check("新学生没有伪精确能力诊断", "不代表掌握度诊断" in all_text(page))
    ctx.shot(page, "first-learning-choice")
    click(page, "按知识点选题")
    click(page, "数学")
    topics = api.get("/questions/topics?subject=math")["items"]
    if not ctx.check("目录有当前数学可练知识点", bool(topics)):
        return
    topic = topics[0]
    click(page, "全部知识点")
    label = f"数学 · {topic['title']}（{topic['question_count']}题）"
    with page.expect_response(
        lambda response: question_response(response, knowledge_id=topic["id"])
    ) as pending:
        click(page, label)
    result = pending.value.json()["data"]
    ctx.check("实际请求携带所选知识点", bool(result["items"]))
    ctx.check(
        "实际返回题目全部属于所选知识点",
        all(topic["id"] in {node["id"] for node in q["knowledge"]} for q in result["items"]),
    )
    ctx.check("实际题量与目录一致", len(result["items"]) == min(20, topic["question_count"]))
    ctx.check(
        "页面展示筛选后的题目", _wait(page, lambda: result["items"][0]["title"] in all_text(page))
    )
    ctx.shot(page, "math-topic-selected")
    with page.expect_response(
        lambda response: question_response(response, subject="physics")
    ) as pending:
        click(page, "物理")
    ctx.check(
        "切换科目清除旧知识点条件",
        "knowledge_id" not in parse_qs(urlsplit(pending.value.url).query),
    )
    ctx.check(
        "新科目返回题目不混入数学",
        all(q["subject"] == "physics" for q in pending.value.json()["data"]["items"]),
    )
    # Actual existing APIs create one completed engineering-sample exercise.
    key = "math-ineq-min"
    seed_attempt(api, key, data.answer_for(key, "correct"))
    reopen(page, "#/home")
    ctx.check(
        "已有本人练习记录后不再显示首次选择",
        "按知识点选题" not in all_text(page) and not api.get("/tasks/today")["cold_start"],
    )
    ctx.shot(page, "returning-student-home")


FLOW = Flow("student_topic_choice", "首次学习与知识点选题", frozenset({"flutter"}), run)
