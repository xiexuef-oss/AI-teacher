"""Real batch partial-result recovery using the public self-authored example.

Each item uses a savepoint; successes and the receipt commit in one outer
transaction. UI input and explicit replay create every tested state. Evidence
reads only owner journals and the isolated database's audit count, never auth.
"""

from __future__ import annotations

import copy
import json
import re
import sqlite3

from e2e._paths import REPO_ROOT
from e2e.api_client import Api
from e2e.browser import read_admin_session
from e2e.flowbase import Flow
from e2e.servers import ADMIN_URL

COMMENT_B = "自编批量恢复：续改B\n重新核对来源与条件\n仅明确提交失败题"


def _wait_saved(page):
    page.wait_for_function(
        "()=>document.querySelector('[data-testid=batch-draft-state]')?.textContent.includes('本机批量草稿已保存')"
    )


def _audit_count(ctx, question_id):
    path = (ctx.out_dir / "tutor.sqlite3").resolve().as_posix()
    with sqlite3.connect("file:" + path + "?mode=ro", uri=True) as db:
        return db.execute(
            "SELECT count(*) FROM audit_logs WHERE target_type=? AND target_id=?",
            ("question", question_id),
        ).fetchone()[0]


def _snapshot(ctx, name):
    pages = []
    for page in ctx.pages:
        if page.is_closed():
            continue
        pages.append(
            page.evaluate("""()=>({url:location.href,draftStatus:document.querySelector('[data-testid=batch-draft-state]')?.textContent,
         rows:[...document.querySelectorAll('article')].map(r=>({title:r.querySelector('h2')?.textContent,comment:r.querySelector('textarea')?.value,confirmed:r.querySelector('[data-testid=batch-confirm]')?.checked})),
         alerts:[...document.querySelectorAll('[role=alert]')].map(e=>e.textContent),
         journals:Object.fromEntries(Object.keys(localStorage).filter(k=>k.startsWith('admin-batch-draft/')||k.startsWith('admin-write/')||k.startsWith('admin-batch-legacy-stop/')).map(k=>[k,JSON.parse(localStorage.getItem(k))]))})""")
        )
    (ctx.out_dir / (name + ".json")).write_text(
        json.dumps(pages, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _scenario(ctx):
    payload = json.loads(
        (REPO_ROOT / "apps/admin_web/public/examples/question-import.json").read_text(
            encoding="utf-8"
        )
    )
    author = Api(Api("").post("/dev/local-identities?role=reviewer")["access_token"])
    first_body = copy.deepcopy(payload)
    first_body["question"]["title"] += " batch-recovery Q1"
    second_body = copy.deepcopy(payload)
    second_body["question"]["title"] += " batch-recovery Q2"
    first = author.post("/admin/question-imports", first_body)
    second = author.post("/admin/question-imports", second_body)
    page = ctx.new_admin_page()
    page.goto(ADMIN_URL)
    page.get_by_test_id("sign-in-reviewer").click()
    page.get_by_test_id("queue").wait_for()
    reviewer_session = read_admin_session(page)
    reviewer = Api(reviewer_session["token"])
    ctx.check("作者A与独立UI审核员B不同", reviewer_session["userId"] != first["created_by"])
    page.get_by_label("选择 " + first["title"], exact=True).check()
    page.get_by_label("选择 " + second["title"], exact=True).check()
    page.get_by_role("link", name=re.compile("逐题确认批量审核")).click()
    page.get_by_test_id("batch-confirm").nth(1).wait_for()
    page.get_by_test_id("batch-confirm").nth(0).check()
    page.get_by_test_id("batch-confirm").nth(1).check()
    _wait_saved(page)
    ctx.check(
        "真实浏览器WebLocks可用", page.evaluate("typeof navigator.locks?.request==='function'")
    )
    changed = author.post(
        "/admin/questions/" + second["id"] + "/versions",
        {
            "expected_version": second["version"],
            "expected_review_revision": second["review_revision"],
            **second_body["question"],
            "title": second["title"] + " author-v2",
            "comment": "自编样题真实并发版本更新",
        },
    )
    ctx.check(
        "作者A真实API将q2更新为v2而审核页仍选旧v1", changed["version"] == second["version"] + 1
    )
    requests = []
    audit_after_first = []

    def intercept(route):
        request = route.request
        if request.method != "POST":
            route.continue_()
            return
        response = route.fetch()
        body = json.loads(request.post_data)
        data = response.json().get("data")
        requests.append(
            {
                "body": body,
                "key": request.all_headers().get("idempotency-key"),
                "status": response.status,
                "result": data,
            }
        )
        (ctx.out_dir / "wire-progress-safe.json").write_text(
            json.dumps(requests, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if len(requests) == 1:
            ctx.check(
                "真实batch200部分成功保留q1成功与q2版本409",
                response.status == 200
                and [i["status"] for i in data["items"]] == ["succeeded", "failed"]
                and data["items"][1]["error"]["code"] == "version_conflict",
            )
            ctx.check(
                "原items顺序与每题双CAS完整固定",
                [i["question_id"] for i in body["items"]] == [first["id"], second["id"]]
                and all(
                    i["expected_version"] == 1 and isinstance(i["expected_review_revision"], int)
                    for i in body["items"]
                ),
            )
            journal = page.evaluate(
                "o=>JSON.parse(localStorage.getItem('admin-write/v1/'+encodeURIComponent(o)))",
                reviewer_session["userId"],
            )
            ctx.check(
                "发网前完整原batch body/key已落本机",
                any(
                    c["body"] == body
                    and c["key"] == requests[0]["key"]
                    and c["phase"] == "prepared"
                    for c in journal["commands"]
                ),
            )
            audit_after_first.append(_audit_count(ctx, first["id"]))
            row = page.locator("article").nth(1)
            row.get_by_label("原因 / 备注", exact=True).fill(COMMENT_B)
            row.get_by_test_id("batch-confirm").check()
            _wait_saved(page)
            _snapshot(ctx, "a_inflight_b_saved")
            route.abort("failed")
        else:
            route.fulfill(response=response)

    page.route("**/api/v1/admin/question-reviews/batch", intercept)
    page.get_by_test_id("batch-submit").click()
    page.wait_for_function(
        "()=>{const b=document.querySelector('[data-testid=batch-submit]');return b&&!b.disabled}"
    )
    batch_url = page.url
    context = page.context
    page.close()
    page = context.new_page()
    ctx.pages.append(page)
    page.route("**/api/v1/admin/question-reviews/batch", intercept)
    page.goto(batch_url)
    page.get_by_test_id("batch-confirm").nth(1).wait_for()
    _wait_saved(page)
    ctx.check(
        "关闭tab同context重开不自动POST且B意见和确认恢复",
        len(requests) == 1
        and page.locator("article").nth(1).get_by_label("原因 / 备注", exact=True).input_value()
        == COMMENT_B
        and page.get_by_test_id("batch-confirm").nth(1).is_checked(),
    )
    page.get_by_test_id("batch-submit").click()
    page.get_by_role("status").filter(has_text="历史逐题结果").wait_for()
    page.wait_for_function(
        "()=>{const b=document.querySelector('[data-testid=batch-submit]');return b&&!b.disabled}"
    )
    ctx.check(
        "原batch明确重放同key同完整body同部分成功回执",
        len(requests) == 2 and requests[1] == requests[0],
    )
    ctx.check(
        "重放不会重复q1审核审计或推进其revision",
        _audit_count(ctx, first["id"]) == audit_after_first[0]
        and reviewer.get("/admin/questions/" + first["id"])["status"] == "reviewed",
    )
    ctx.check(
        "原A历史回执不清q2续改B不导航",
        page.locator("article").nth(1).get_by_label("原因 / 备注", exact=True).input_value()
        == COMMENT_B
        and page.url == batch_url,
    )
    _snapshot(ctx, "historical_partial_recovered_b_retained")
    row = page.locator("article").nth(1)
    row.get_by_role("button", name="刷新本题版本并重新核对", exact=True).click()
    row.get_by_role(
        "heading", name=changed["title"] + " · v" + str(changed["version"]), exact=True
    ).wait_for()
    _wait_saved(page)
    row.get_by_test_id("batch-confirm").check()
    _wait_saved(page)
    page.get_by_test_id("batch-submit").click()
    page.wait_for_function(
        "()=>{const b=document.querySelector('[data-testid=batch-submit]');return b&&!b.disabled}"
    )
    ctx.check(
        "失败q2明确采用当前双CAS并新key只提交q2",
        len(requests) == 3
        and len(requests[2]["body"]["items"]) == 1
        and requests[2]["body"]["items"][0]["question_id"] == second["id"]
        and requests[2]["body"]["items"][0]["expected_version"] == changed["version"]
        and requests[2]["body"]["items"][0]["expected_review_revision"]
        == changed["review_revision"]
        and requests[2]["key"] != requests[0]["key"]
        and requests[2]["result"]["items"][0]["status"] == "succeeded",
    )
    ctx.check(
        "q2真实审核成功且q1审计仍不重复",
        reviewer.get("/admin/questions/" + second["id"])["status"] == "reviewed"
        and _audit_count(ctx, first["id"]) == audit_after_first[0],
    )
    ctx.shot(page, "batch_original_partial_and_explicit_q2_retry")
    (ctx.out_dir / "wire-evidence.json").write_text(
        json.dumps(
            {
                "requests": requests,
                "q1_audit_count_after_first": audit_after_first[0],
                "q1_audit_count_final": _audit_count(ctx, first["id"]),
                "scope": "public_self_authored_fixture_only_no_auth",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def run_flow(ctx):
    try:
        _scenario(ctx)
    finally:
        _snapshot(ctx, "terminal_safe_state")


FLOW = Flow(
    "admin_batch_write_recovery", "批量审核真实部分成功与写命令恢复", frozenset({"admin"}), run_flow
)
