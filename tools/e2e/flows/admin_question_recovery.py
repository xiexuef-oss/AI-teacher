"""Real API/UI Question recovery, cross-tab draft previews, and safe evidence."""

from __future__ import annotations

import copy
import json
from urllib.parse import quote

from e2e._paths import REPO_ROOT
from e2e.api_client import Api
from e2e.browser import read_admin_session
from e2e.flowbase import Flow
from e2e.servers import ADMIN_URL


def _journal(page, owner):
    return page.evaluate(
        "k=>JSON.parse(localStorage.getItem(k))", "admin-write/v1/" + quote(owner, safe="")
    )


def _draft_key(owner, question, kind):
    return "admin-question-draft/v1/" + "/".join(quote(v, safe="") for v in (owner, question, kind))


def _saved(page, kind):
    # Public UI boundary is required. It must reflect latest serial == durable serial,
    # not a snapshot that happened to be saved before the last native paste event.
    page.get_by_test_id(kind + "-draft-state").filter(has_text="本机草稿已保存").wait_for()


def _idle(page, testid):
    page.wait_for_function(
        "id=>{const b=document.querySelector(`[data-testid='${id}']`);return b && !b.disabled}",
        arg=testid,
    )


def _login(ctx):
    page = ctx.new_admin_page()
    page.goto(ADMIN_URL)
    page.get_by_test_id("sign-in-reviewer").click()
    page.get_by_test_id("queue").wait_for()
    session = read_admin_session(page)
    return page, session["userId"], Api(session["token"])


def _open(page, question):
    target = ADMIN_URL + "#/questions/" + question
    with page.expect_response(
        lambda r: r.request.method == "GET" and r.url.endswith("/admin/questions/" + question)
    ) as loaded:
        if page.url == target:
            page.reload()
        else:
            page.goto(target)
    title = loaded.value.json()["data"]["title"]
    page.wait_for_function("title=>document.querySelector('h1')?.textContent===title", arg=title)
    page.get_by_test_id("review-draft-state").wait_for()
    page.wait_for_function(
        "()=>!document.querySelector('[data-testid=review-draft-state]')?.textContent.includes('正在读取')"
    )


def _open_editor(page):
    page.get_by_test_id("edit").click()
    page.get_by_test_id("title").wait_for()
    page.get_by_test_id("edit-draft-state").wait_for()
    page.wait_for_function(
        "()=>!document.querySelector('[data-testid=edit-draft-state]')?.textContent.includes('正在读取')"
    )
    page.wait_for_function(
        "()=>{const b=document.querySelector('[data-testid=title]');return b && !b.closest('fieldset')?.disabled}"
    )


def _edit(page, question, title):
    _open(page, question)
    _open_editor(page)
    if page.get_by_test_id("edit-adopt").count():
        page.get_by_test_id("edit-adopt").click()
        page.get_by_test_id("edit-adopt").wait_for(state="hidden")
    page.get_by_test_id("title").fill(title)
    _saved(page, "edit")
    with page.expect_response(
        lambda r: r.request.method == "GET" and r.url.endswith("/admin/questions/" + question)
    ) as refreshed:
        page.get_by_test_id("save").click()
    data = refreshed.value.json()["data"]
    page.get_by_test_id("editor").wait_for(state="hidden")
    return data


def _review(page, question, decision):
    _open(page, question)
    if page.get_by_test_id("review-adopt").count():
        page.get_by_test_id("review-adopt").click()
        page.get_by_test_id("review-adopt").wait_for(state="hidden")
    page.locator(f"input[name=decision][value={decision}]").check()
    if decision == "approve" and page.get_by_test_id("confirm-fast").count():
        page.get_by_test_id("confirm-fast").check()
    page.get_by_test_id("comment").fill("独立工程审校与显式决策 " + decision)
    _saved(page, "review")
    with page.expect_response(
        lambda r: r.request.method == "GET" and r.url.endswith("/admin/questions/" + question)
    ) as refreshed:
        page.get_by_test_id("submit-decision").click()
    return refreshed.value.json()["data"]


def _wire(req, response):
    return {
        "body": json.loads(req.post_data),
        "key": req.all_headers().get("idempotency-key"),
        "status": response.status,
        "data": response.json().get("data"),
    }


def _check_prepared(ctx, page, owner, req, resource):
    body = json.loads(req.post_data)
    key = req.all_headers().get("idempotency-key")
    row = next(c for c in _journal(page, owner)["commands"] if c["key"] == key)
    ctx.check(
        "发网前已持久精确生成body/key与双CAS来源",
        row["body"] == body
        and row["phase"] == "prepared"
        and row["resource"] == resource
        and isinstance(body.get("expected_version"), int)
        and isinstance(body.get("expected_review_revision"), int),
    )


def _scenario(ctx):
    author_page, _, author_api = _login(ctx)
    page, owner, api = _login(ctx)
    independent, _, _ = _login(ctx)
    ctx.check(
        "真实浏览器支持WebLocks", page.evaluate("typeof navigator.locks?.request === 'function'")
    )
    fixture = json.loads(
        (REPO_ROOT / "apps/admin_web/public/examples/question-import.json").read_text(
            encoding="utf-8"
        )
    )
    evidence = {
        "scope": "public_self_authored_example_only; no token or auth storage",
        "edit": [],
        "review": [],
        "conflict": [],
    }

    def create(label):
        body = copy.deepcopy(fixture)
        body["question"]["title"] += " " + label
        return author_api.post("/admin/question-imports", body)

    # 201 has committed before loss. B is persisted while A is still pending.
    q = create("Question recovery A/B")
    qid = q["id"]
    _open(page, qid)
    _open_editor(page)
    title_a, title_b = q["title"] + " saved A", q["title"] + " continuation B"
    stem_b = q["content"]["stem"] + "\n工程续改B第一行\n工程续改B第二行"
    page.get_by_test_id("title").fill(title_a)
    _saved(page, "edit")

    def edit_wire(route):
        req = route.request
        if req.method != "POST":
            route.continue_()
            return
        _check_prepared(ctx, page, owner, req, "question:" + qid + ":edit")
        response = route.fetch()
        item = _wire(req, response)
        evidence["edit"].append(item)
        if len(evidence["edit"]) == 1:
            ctx.check("编辑A真实201成功后才丢响应", response.status == 201)
            page.get_by_test_id("title").fill(title_b)
            page.get_by_test_id("stem").fill(stem_b)
            _saved(page, "edit")
            saved = page.evaluate(
                "k=>JSON.parse(JSON.parse(localStorage.getItem(k)).raw)",
                _draft_key(owner, qid, "edit"),
            )
            ctx.check(
                "201在途B普通输入已落本机",
                saved["form"]["title"] == title_b and saved["form"]["stem"] == stem_b,
            )
            route.abort("failed")
        else:
            route.fulfill(response=response)

    pattern = "**/api/v1/admin/questions/" + qid + "/versions"
    page.route(pattern, edit_wire)
    page.get_by_test_id("save").click()
    _idle(page, "edit-retry")
    after_a = api.get("/admin/questions/" + qid)
    history_a = len(after_a["history"])
    page.reload()
    page.get_by_test_id("question-history-retry").wait_for()
    ctx.check("编辑刷新无自动POST", len(evidence["edit"]) == 1)
    _open_editor(page)
    page.wait_for_function(
        "t=>document.querySelector('[data-testid=title]')?.value===t", arg=title_b
    )
    _idle(page, "edit-retry")
    page.get_by_test_id("edit-retry").click()
    page.get_by_test_id("edit-retry").wait_for(state="hidden")
    a1, a2 = evidence["edit"][:2]
    ctx.check(
        "编辑原请求双CAS/key/body精确重放",
        a1["body"] == a2["body"] and a1["key"] == a2["key"] and a1["data"] == a2["data"],
    )
    current = api.get("/admin/questions/" + qid)
    ctx.check(
        "编辑重放不新增历史或版本",
        len(current["history"]) == history_a and current["version"] == after_a["version"],
    )
    ctx.check(
        "A旧回执不清B不导航",
        page.get_by_test_id("title").input_value() == title_b
        and page.get_by_test_id("stem").input_value() == stem_b
        and page.url.endswith("#/questions/" + qid),
    )
    page.get_by_test_id("edit-adopt").click()
    page.get_by_test_id("edit-adopt").wait_for(state="hidden")
    _saved(page, "edit")
    page.get_by_test_id("save").click()
    page.get_by_test_id("editor").wait_for(state="hidden")
    new = evidence["edit"][-1]
    ctx.check(
        "明确采用来源后B新key新双CAS保存",
        len(evidence["edit"]) == 3
        and new["key"] != a1["key"]
        and new["body"]["title"] == title_b
        and new["body"]["expected_version"] == current["version"]
        and new["body"]["expected_review_revision"] == current["review_revision"],
    )
    ctx.check(
        "B真实新版本", api.get("/admin/questions/" + qid)["version"] == current["version"] + 1
    )
    page.unroute(pattern, edit_wire)

    # Review A commits at v1. Other legitimate UI actions advance to published v3.
    q = create("Review lost response")
    qid = q["id"]
    _open(page, qid)
    note_b = "保留的审核续改B\n不同于原A的第二行"
    page.get_by_test_id("comment").fill("原A工程审核意见")
    if page.get_by_test_id("confirm-fast").count():
        page.get_by_test_id("confirm-fast").check()
    _saved(page, "review")

    def review_wire(route):
        req = route.request
        if req.method != "POST":
            route.continue_()
            return
        _check_prepared(ctx, page, owner, req, "question:" + qid + ":review")
        response = route.fetch()
        evidence["review"].append(_wire(req, response))
        if len(evidence["review"]) == 1:
            ctx.check("单审真实200后才丢响应", response.status == 200)
            page.get_by_test_id("comment").fill(note_b)
            _saved(page, "review")
            route.abort("failed")
        else:
            route.fulfill(response=response)

    pattern = "**/api/v1/admin/questions/" + qid + "/review"
    page.route(pattern, review_wire)
    page.get_by_test_id("submit-decision").click()
    _idle(page, "review-retry")
    _edit(author_page, qid, q["title"] + " current v2")
    v3 = _edit(author_page, qid, q["title"] + " current v3")
    _review(independent, qid, "approve")
    published = _review(independent, qid, "publish")
    ctx.check(
        "独立真实UI推进当前v3已上线",
        v3["version"] == 3 and published["version"] == 3 and published["status"] == "published",
    )
    before = api.get("/admin/questions/" + qid)
    page.reload()
    _idle(page, "review-retry")
    ctx.check(
        "单审刷新无自动POST且B意见保留",
        len(evidence["review"]) == 1 and page.get_by_test_id("comment").input_value() == note_b,
    )
    page.get_by_test_id("review-retry").click()
    page.get_by_test_id("review-retry").wait_for(state="hidden")
    r1, r2 = evidence["review"]
    after = api.get("/admin/questions/" + qid)
    ctx.check(
        "单审原key/body/双CAS回执不变",
        r1["key"] == r2["key"] and r1["body"] == r2["body"] and r1["data"] == r2["data"],
    )
    ctx.check(
        "历史审核不新增audit不回退currentv3",
        after["history"] == before["history"]
        and after["version"] == 3
        and after["status"] == "published"
        and page.locator("h1").inner_text() == before["title"],
    )
    ctx.check("历史审核ACK不清续改B", page.get_by_test_id("comment").input_value() == note_b)
    page.unroute(pattern, review_wire)

    # A never executes here: another reviewer advances only the review CAS first.
    # We still persist A as unknown after 409: client must not infer nonexecution.
    q = create("CAS explicit new intent")
    qid = q["id"]
    _open(page, qid)
    page.get_by_test_id("comment").fill("旧来源A")
    _saved(page, "review")

    def conflict_wire(route):
        req = route.request
        if req.method != "POST":
            route.continue_()
            return
        _check_prepared(ctx, page, owner, req, "question:" + qid + ":review")
        if not evidence["conflict"]:
            _review(independent, qid, "approve")
            history = api.get("/admin/questions/" + qid)["history"]
            response = route.fetch()
            ctx.check(
                "旧prepared真实双CAS409无新增audit",
                response.status == 409 and api.get("/admin/questions/" + qid)["history"] == history,
            )
        else:
            response = route.fetch()
        evidence["conflict"].append(_wire(req, response))
        route.fulfill(response=response)

    pattern = "**/api/v1/admin/questions/" + qid + "/review"
    page.route(pattern, conflict_wire)
    page.get_by_test_id("submit-decision").click()
    _idle(page, "review-retry")
    page.get_by_test_id("comment").fill("409后保留续改B")
    _saved(page, "review")
    release = page.get_by_test_id("review-release")
    release.locator("xpath=ancestor::details/summary").click()
    release.click()
    page.get_by_test_id("review-retry").wait_for(state="hidden")
    old = evidence["conflict"][0]
    page.reload()
    page.get_by_test_id("review-adopt").wait_for()
    page.get_by_test_id("review-adopt").click()
    page.get_by_test_id("review-adopt").wait_for(state="hidden")
    page.locator("input[name=decision][value=publish]").check()
    _saved(page, "review")
    source = api.get("/admin/questions/" + qid)
    with page.expect_response(
        lambda r: r.request.method == "GET" and r.url.endswith("/admin/questions/" + qid)
    ):
        page.get_by_test_id("submit-decision").click()
    page.get_by_test_id("done").wait_for()
    newer = evidence["conflict"][-1]
    history = _journal(page, owner)
    record = next(c for c in history["commands"] if c["key"] == old["key"])
    draft = page.evaluate(
        "k=>JSON.parse(localStorage.getItem(k))", _draft_key(owner, qid, "review")
    )
    ctx.check(
        "旧409记录仍unknown/body/key不变且明确released",
        record["phase"] == "prepared"
        and record["body"] == old["body"]
        and any(
            t["key"] == old["key"] and t["snapshot"] == record["snapshot"]
            for t in draft["released"]
        ),
    )
    ctx.check(
        "单独采用新来源再新intent成功",
        len(evidence["conflict"]) == 2
        and newer["status"] == 200
        and newer["key"] != old["key"]
        and newer["body"]["expected_version"] == source["version"]
        and newer["body"]["expected_review_revision"] == source["review_revision"]
        and newer["body"]["comment"] == "409后保留续改B",
    )
    # Two real tabs read the same empty draft source. B is a preserved branch;
    # C subsequently replaces the main draft before B explicitly loads its branch.
    q = create("Cross-tab current head preview")
    qid = q["id"]
    _open(page, qid)
    _open_editor(page)
    other = page.context.new_page()
    ctx.pages.append(other)
    _open(other, qid)
    _open_editor(other)
    title_a, title_b, title_c = (
        q["title"] + suffix for suffix in (" tab A", " branch B", " current C")
    )
    page.get_by_test_id("title").fill(title_a)
    _saved(page, "edit")
    other.get_by_test_id("title").fill(title_b)
    other.get_by_test_id("edit-draft-state").filter(has_text="来源待确认").wait_for()
    draft_key = _draft_key(owner, qid, "edit")
    before = other.evaluate("k=>JSON.parse(localStorage.getItem(k))", draft_key)
    branch = next(
        item for item in before["branches"] if json.loads(item["raw"])["form"]["title"] == title_b
    )
    ctx.check(
        "双tab普通输入保留主A及分支B",
        json.loads(before["raw"])["form"]["title"] == title_a and bool(branch),
    )
    page.get_by_test_id("title").fill(title_c)
    _saved(page, "edit")
    other.get_by_role("button", name="载入独立编辑分支", exact=True).click()
    other.wait_for_function(
        "title=>document.querySelector('[data-testid=title]')?.value===title", arg=title_b
    )
    preview = other.get_by_text("比较当前主草稿", exact=True).locator("xpath=parent::details")
    preview.locator("summary").click()
    other.wait_for_function(
        "title=>{const summary=[...document.querySelectorAll('summary')].find(x=>x.textContent==='比较当前主草稿');const raw=summary?.parentElement?.querySelector('pre')?.textContent;return !!raw && JSON.parse(raw).form.title===title}",
        arg=title_c,
    )
    ctx.check(
        "载入B时公开比较预览同步为最新C",
        json.loads(preview.locator("pre").inner_text())["form"]["title"] == title_c
        and other.get_by_test_id("title").input_value() == title_b,
    )
    ctx.shot(other, "cross_tab_branch_b_compares_current_c")
    other.get_by_test_id("edit-adopt").click()
    other.get_by_test_id("edit-adopt").wait_for(state="hidden")
    _saved(other, "edit")
    other.wait_for_function(
        "title=>{const summary=[...document.querySelectorAll('summary')].find(x=>x.textContent==='比较当前主草稿');const raw=summary?.parentElement?.querySelector('pre')?.textContent;return !!raw && JSON.parse(raw).form.title===title}",
        arg=title_b,
    )
    after = other.evaluate("k=>JSON.parse(localStorage.getItem(k))", draft_key)
    ctx.check(
        "明确采用后公开预览显示B且表单仍B",
        json.loads(preview.locator("pre").inner_text())["form"]["title"] == title_b
        and other.get_by_test_id("title").input_value() == title_b,
    )
    ctx.check(
        "采用B保留C持久备份且原tab仍C",
        json.loads(after["raw"])["form"]["title"] == title_b
        and any(json.loads(item["raw"])["form"]["title"] == title_c for item in after["branches"])
        and page.get_by_test_id("title").input_value() == title_c,
    )
    ctx.check(
        "双tab来源选择不暗中创建服务器版本",
        api.get("/admin/questions/" + qid)["version"] == q["version"],
    )
    evidence["cross_tab"] = {
        "before": before,
        "after": after,
        "ui_head_after_load": title_c,
        "ui_head_after_adopt": title_b,
    }
    ctx.shot(other, "cross_tab_adopt_b_preview_and_c_backup")

    (ctx.out_dir / "evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    ctx.shot(page, "question_recovery_final")


def _snapshot(ctx):
    states = []
    for page in ctx.pages:
        try:
            if page.is_closed():
                continue
            states.append(
                page.evaluate("""()=>({url:location.href,title:document.querySelector('h1')?.textContent,
            alerts:[...document.querySelectorAll('[role=alert]')].map(x=>x.textContent),
            drafts:Object.fromEntries(Object.keys(localStorage).filter(k=>k.startsWith('admin-question-draft/')||k.startsWith('admin-write/')).map(k=>[k,localStorage.getItem(k)]))})""")
            )
        except Exception as error:
            states.append({"snapshot_error_type": type(error).__name__})
    (ctx.out_dir / "terminal_safe_state.json").write_text(
        json.dumps(states, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def run_flow(ctx):
    try:
        _scenario(ctx)
    finally:
        try:
            _snapshot(ctx)
        except Exception as error:
            (ctx.out_dir / "snapshot_failure_type.txt").write_text(
                type(error).__name__, encoding="utf-8"
            )


FLOW = Flow(
    "admin_question_recovery", "题目编辑与单审真实丢响应恢复", frozenset({"admin"}), run_flow
)
