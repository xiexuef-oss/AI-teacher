"""Real single-question import recovery and browser WebLocks draft CAS.

Uses only the public self-authored example. UI actions create every state;
read-only snapshots exclude authentication storage. HTTP response loss occurs
only after the real API committed, and explicit replay must preserve body/key.
"""

from __future__ import annotations

import copy
import json

from e2e._paths import REPO_ROOT
from e2e.api_client import Api
from e2e.browser import read_admin_session
from e2e.flowbase import Context, Flow
from e2e.servers import ADMIN_URL


def _fill_and_wait_saved(page, raw, key, *, conflict=False):
    before = page.evaluate("(k)=>JSON.parse(localStorage.getItem(k))", key)
    page.get_by_label("JSON 内容", exact=True).fill(raw)
    expected = "冲突分支已保存" if conflict else "本机草稿已保存"
    page.wait_for_function(
        "x=>document.querySelector('textarea')?.value===x.raw && document.querySelector('[data-testid=import-draft-state]')?.textContent.includes(x.state)",
        arg={"raw": raw, "state": expected},
    )
    after = page.evaluate("(k)=>JSON.parse(localStorage.getItem(k))", key)
    return before, after


def _scenario(ctx: Context) -> None:
    page = ctx.new_admin_page()
    page.add_init_script(
        """window.__importInputEvents=[];document.addEventListener('input',e=>{if(e.target instanceof HTMLTextAreaElement)window.__importInputEvents.push({inputType:e.inputType??null,isTrusted:e.isTrusted,length:e.target.value.length,time:Date.now()});},true);"""
    )
    page.goto(ADMIN_URL)
    page.get_by_test_id("sign-in-reviewer").click()
    page.get_by_test_id("queue").wait_for()
    session = read_admin_session(page)
    owner = session["userId"]
    api = Api(session["token"])
    draft_key = "admin-import-draft/v1/" + owner
    command_key = "admin-write/v1/" + owner
    fixture = REPO_ROOT / "apps/admin_web/public/examples/question-import.json"
    a = json.loads(fixture.read_text(encoding="utf-8"))
    b = copy.deepcopy(a)
    b["question"]["title"] += " B continuation engineering"
    raw_b = json.dumps(b, ensure_ascii=False, indent=2)
    page.goto(ADMIN_URL + "#/import")
    page.get_by_label("题目文件").set_input_files(str(fixture))
    page.wait_for_function("(k)=>!!localStorage.getItem(k)", arg=draft_key)
    ctx.check(
        "真实Chromium提供WebLocks", page.evaluate("typeof navigator.locks?.request === 'function'")
    )
    requests = []

    def wire(route):
        req = route.request
        if req.method != "POST":
            route.continue_()
            return
        response = route.fetch()
        item = {
            "body": json.loads(req.post_data),
            "key": req.all_headers().get("idempotency-key"),
            "status": response.status,
            "id": response.json().get("data", {}).get("id"),
        }
        requests.append(item)
        if len(requests) == 1:
            ctx.check("A真实API已经提交201", response.status == 201 and bool(item["id"]))
            stored = page.evaluate("(k)=>JSON.parse(localStorage.getItem(k))", command_key)
            ctx.check(
                "发网前已持久完整A请求与固定key",
                stored["commands"][0]["body"] == a
                and stored["commands"][0]["key"] == item["key"]
                and stored["commands"][0]["phase"] == "prepared",
            )
            before_paste, after_paste = _fill_and_wait_saved(page, raw_b, draft_key)
            ctx.check(
                "一次真实多行粘贴仅增加一代草稿",
                after_paste["generation"] == before_paste["generation"] + 1,
            )
            page.wait_for_function(
                "x=>JSON.parse(localStorage.getItem(x.key)).raw===x.raw",
                arg={"key": draft_key, "raw": raw_b},
            )
            ctx.check("A响应在途时普通UI续改B已落本机", True)
            route.abort("failed")
        else:
            route.fulfill(response=response)

    page.route("**/api/v1/admin/question-imports", wire)
    _snapshot(ctx, "before_submit_" + str(len(requests)))
    page.get_by_role("checkbox").check()
    page.get_by_test_id("import-submit").click()
    page.get_by_test_id("import-retry").wait_for()
    page.wait_for_function(
        "()=>{const b=document.querySelector('[data-testid=import-retry]');return b && !b.disabled}"
    )
    page.reload()
    page.get_by_test_id("import-retry").wait_for()
    ctx.check(
        "完整刷新恢复续改B且未自动POST",
        page.get_by_label("JSON 内容", exact=True).input_value() == raw_b and len(requests) == 1,
    )
    page.get_by_test_id("import-retry").click()
    page.get_by_role("status").filter(has_text="这是历史命令结果").wait_for()
    ctx.check(
        "恢复原key与完整body且服务端返回同一题ID",
        len(requests) == 2
        and requests[1]["key"] == requests[0]["key"]
        and requests[1]["body"] == requests[0]["body"]
        and requests[1]["id"] == requests[0]["id"],
    )
    ctx.check(
        "历史A回执不清B不导航",
        page.get_by_label("JSON 内容", exact=True).input_value() == raw_b
        and page.url.endswith("#/import"),
    )
    ctx.check(
        "真实后端原ID可读且仍待审草稿",
        api.get("/admin/questions/" + requests[0]["id"])["status"] == "draft",
    )
    _snapshot(ctx, "before_submit_" + str(len(requests)))
    page.get_by_role("checkbox").check()
    page.get_by_test_id("import-submit").click()
    page.get_by_role("link", name="打开草稿，检查并编辑").wait_for()
    ctx.check(
        "B再次明确提交是新body新key新题ID",
        len(requests) == 3
        and requests[2]["body"] == b
        and requests[2]["key"] != requests[0]["key"]
        and requests[2]["id"] != requests[0]["id"],
    )
    ctx.shot(page, "a_recovered_b_explicit_new_intent")
    other = page.context.new_page()
    other.add_init_script(
        """window.__importInputEvents=[];document.addEventListener('input',e=>{if(e.target instanceof HTMLTextAreaElement)window.__importInputEvents.push({inputType:e.inputType??null,isTrusted:e.isTrusted,length:e.target.value.length,time:Date.now()});},true);"""
    )
    ctx.pages.append(other)
    other.goto(ADMIN_URL + "#/import")
    page.reload()
    page.get_by_label("JSON 内容", exact=True).wait_for()
    other.get_by_label("JSON 内容", exact=True).wait_for()
    page.wait_for_function('() => !!document.querySelector("textarea")?.value')
    other.wait_for_function('() => !!document.querySelector("textarea")?.value')
    c = copy.deepcopy(b)
    c["question"]["title"] += " tab A"
    d = copy.deepcopy(b)
    d["question"]["title"] += " tab B"
    raw_c = json.dumps(c, ensure_ascii=False, indent=2)
    raw_d = json.dumps(d, ensure_ascii=False, indent=2)
    _snapshot(ctx, "before_tab_edits")
    _fill_and_wait_saved(page, raw_c, draft_key)
    page.wait_for_function(
        "x=>JSON.parse(localStorage.getItem(x.key)).raw===x.raw",
        arg={"key": draft_key, "raw": raw_c},
    )
    _snapshot(ctx, "after_tab_a_edit")
    before_conflict, after_conflict = _fill_and_wait_saved(other, raw_d, draft_key, conflict=True)
    ctx.check(
        "一次B源冲突仅新增一个等价分支",
        len(after_conflict["branches"]) == len(before_conflict["branches"]) + 1
        and sum(x["raw"] == raw_d for x in after_conflict["branches"]) == 1,
    )
    other.get_by_role("alert").filter(has_text="跨标签页冲突分支已保存").wait_for()
    draft = other.evaluate("(k)=>JSON.parse(localStorage.getItem(k))", draft_key)
    ctx.check(
        "同owner两真实tabs普通输入触发CAS双方保留",
        draft["raw"] == raw_c and any(x["raw"] == raw_d for x in draft["branches"]),
    )
    _snapshot(ctx, "after_tab_b_conflict")
    other.reload()
    other.get_by_role("region", name="本机冲突草稿").wait_for()
    ctx.check(
        "冲突分支刷新仍持久且不自动导入",
        other.get_by_label("JSON 内容", exact=True).input_value() == raw_c and len(requests) == 3,
    )
    branch = next(x for x in draft["branches"] if x["raw"] == raw_d)
    _snapshot(ctx, "before_branch_load")
    other.get_by_test_id("import-branch-" + branch["id"]).click()
    other.wait_for_function('x=>document.querySelector("textarea")?.value===x', arg=raw_d)
    _snapshot(ctx, "after_branch_load")
    ctx.check(
        "显式载入分支仅查看B",
        other.get_by_label("JSON 内容", exact=True).input_value() == raw_d and len(requests) == 3,
    )
    other.get_by_test_id("import-promote-branch").click()
    _snapshot(ctx, "after_promote_click")
    other.get_by_test_id("import-promote-branch").wait_for(state="hidden")
    merged = other.evaluate("(k)=>JSON.parse(localStorage.getItem(k))", draft_key)
    ctx.check(
        "显式采用B保留原主A备份且A标签输入不变",
        merged["raw"] == raw_d
        and any(x["raw"] == raw_c for x in merged["branches"])
        and page.get_by_label("JSON 内容", exact=True).input_value() == raw_c,
    )
    other.reload()
    other.wait_for_function('x=>document.querySelector("textarea")?.value===x', arg=raw_d)
    ctx.check("采用后的B再次刷新恢复且仍无额外POST", len(requests) == 3)
    evidence = {
        "requests": requests,
        "draft": merged,
        "journal": other.evaluate("(k)=>JSON.parse(localStorage.getItem(k))", command_key),
        "real_web_locks": True,
        "scope": "self_authored_public_example_only_no_auth_material",
    }
    (ctx.out_dir / "evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    ctx.shot(other, "cross_tab_branch_adopted_preserving_a")


def _snapshot(ctx: Context, name: str) -> None:
    entries = []
    for page in ctx.pages:
        if page.is_closed():
            continue
        entries.append(
            page.evaluate("""() => ({url: location.href, text:document.querySelector('textarea')?.value,
          draftStatus:document.querySelector('[data-testid=import-draft-state]')?.textContent,alerts:[...document.querySelectorAll('[role=alert]')].map(e=>e.textContent),inputEvents:window.__importInputEvents??[],
          safeJournals:Object.fromEntries(Object.keys(localStorage).filter(k=>k.startsWith('admin-import-draft/')||k.startsWith('admin-write/')).map(k=>[k,JSON.parse(localStorage.getItem(k))]))})""")
        )
    (ctx.out_dir / (name + ".json")).write_text(
        json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def run_flow(ctx: Context) -> None:
    try:
        _scenario(ctx)
    finally:
        _snapshot(ctx, "terminal_safe_state")


FLOW = Flow(
    "admin_write_recovery", "单题导入真实写命令与跨标签恢复", frozenset({"admin"}), run_flow
)
