"""Real diagnostic recovery, UI submission, history and native browser downloads."""

import json

from e2e import data
from e2e.api_client import Api
from e2e.browser import all_text, open_flutter, reopen, stored, stored_all, tap, type_into
from e2e.flowbase import Flow
from e2e.flows.student_draft_recovery import _wait
from e2e.servers import API_URL
from support.flows import CORRECT


def run(ctx):
    page = ctx.new_page()
    open_flutter(page)
    tap(page, "四川")
    tap(page, "下一步")
    tap(page, "高一", role="checkbox")
    tap(page, "下一步")
    tap(page, "开始学习", wait=2000)
    api = Api(stored(page, "auth.token"))
    tap(page, "三题摸底")
    ctx.check("首次打开不创建摸底", api.get("/diagnostics") == {"revision": 0, "run": None})
    sent = []

    def lose_first(route):
        if route.request.method != "POST":
            route.continue_()
            return
        sent.append((route.request.headers.get("idempotency-key"), route.request.post_data_json))
        response = route.fetch()
        if len(sent) == 1 and response.status == 201:
            route.abort("connectionclosed")
        else:
            route.fulfill(response=response)

    page.context.route(API_URL + "/diagnostics", lose_first)
    tap(page, "开始三题摸底", exact=True)
    ctx.check("创建真实成功丢响应后保留原操作", _wait(page, lambda: "重试原操作" in all_text(page)))
    original = api.get("/diagnostics")["run"]
    reopen(page, "#/diagnostic")
    ctx.check("重载不自动重发摸底创建", len(sent) == 1)
    tap(page, "重试原操作", exact=True)
    ctx.check(
        "明确重试沿用完整请求与原键", _wait(page, lambda: len(sent) == 2) and sent[0] == sent[1]
    )
    ctx.check("重试没有多开轮次", api.get("/diagnostics")["run"]["id"] == original["id"])
    ctx.shot(page, "diagnostic-restored")

    for position, item in enumerate(original["items"], 1):
        # Earlier submitted items become '回看作答', leaving the next unopened button first.
        tap(page, "开始作答", exact=True, wait=2000)
        opened = api.get("/diagnostics")["run"]
        session_id = opened["items"][position - 1]["session_id"]
        ctx.check(
            f"第{position}题绑定原会话",
            bool(session_id)
            and any(
                method == "GET" and path == f"/sessions/{session_id}/question"
                for method, path, _ in page.responses
            )
            and not any(
                method == "POST" and path == "/sessions" for method, path, _ in page.responses
            ),
        )
        key = next(key for key in CORRECT if data.question_id(key) == item["question"]["id"])
        answer = data.answer_for(key, "correct")
        if "selected_options" in answer:
            for option in answer["selected_options"]:
                tap(page, f"选项 {option}")
        else:
            for index, blank in enumerate(answer["blanks"]):
                type_into(page, page.get_by_role("textbox").nth(index), blank["value"])
        tap(page, "提交", exact=True, wait=1600)
        ctx.check(
            f"第{position}题通过UI提交首份作答",
            _wait(
                page, lambda p=position: api.get("/diagnostics")["run"]["summary"]["submitted"] == p
            ),
        )
        reopen(page, "#/diagnostic")
        ctx.check(
            f"第{position}题重载恢复原绑定与进度",
            api.get("/diagnostics")["run"]["items"][position - 1]["session_id"] == session_id
            and f"已提交 {position} 题" in all_text(page),
        )

    result = api.get("/diagnostics")["run"]
    ctx.check(
        "三题均完成且只计本轮首份提交",
        result["status"] == "completed"
        and result["summary"]["independent_correct"] == 3
        and result["summary"]["submitted"] == 3,
    )
    ctx.check(
        "页面显示本轮计数而非能力分数",
        "本轮已完成" in all_text(page) and "不推算掌握度或分数" in all_text(page),
    )
    ctx.check("页面明确标注工程样题", "自编工程样题未经过学科审校" in all_text(page))
    ctx.check("没有未捕获页面异常", not page.errors)
    ctx.shot(page, "diagnostic-completed")
    before = stored_all(page)
    with page.expect_download() as pending:
        tap(page, "导出本机摸底记录", exact=True)
    local_path = ctx.out_dir / "local-diagnostic-records.json"
    pending.value.save_as(local_path)
    local_raw = local_path.read_text(encoding="utf-8")
    local = json.loads(local_raw)
    ctx.check(
        "实际下载本人本机摸底记录",
        local["scope"] == "local_diagnostic_records"
        and local["owner_id"] == stored(page, "auth.userId"),
    )
    ctx.check(
        "本机导出保留原命令和最新计数",
        len(local["commands"]) == 4
        and local["commands"][0]["key"] == sent[0][0]
        and local["workspace"]["run"]["summary"]["submitted"] == 3,
    )
    ctx.check("本机导出不包含登录凭据", stored(page, "auth.token") not in local_raw)
    ctx.check("导出没有改写本机记录", stored_all(page) == before)

    reopen(page, "#/profile")
    with page.expect_download() as pending:
        tap(page, "导出服务端学习记录", exact=True)
    server_path = ctx.out_dir / "server-learning-records.json"
    pending.value.save_as(server_path)
    server = json.loads(server_path.read_text(encoding="utf-8"))
    ctx.check(
        "实际云端导出包含原轮次与工作区",
        {run["id"] for run in server["diagnostic_runs"]} == {original["id"]}
        and server["diagnostic_workspace"]["run"]["id"] == original["id"],
    )

    reopen(page, "#/diagnostic")
    writes = sum(method == "POST" for method, _, _ in page.responses)
    tap(page, "历史摸底", exact=True)
    tap(page, "数学 · 已完成")
    ctx.check(
        "历史展开显示原三题",
        all(item["question"]["title"] in all_text(page) for item in original["items"]),
    )
    ctx.shot(page, "diagnostic-history")
    tap(page, "回看首份作答", exact=True, wait=2000)
    ctx.check(
        "历史回看没有新建会话或作答",
        sum(method == "POST" for method, _, _ in page.responses) == writes,
    )
    submit_button = page.get_by_role("button", name="提交", exact=True)
    ctx.check(
        "历史首份提交只读",
        submit_button.count() == 0 or submit_button.first.get_attribute("aria-disabled") == "true",
    )


FLOW = Flow("student_diagnostic", "三题摸底与原操作恢复", frozenset({"flutter"}), run)
