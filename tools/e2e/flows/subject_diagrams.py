"""Self-authored diagrams: complete textual givens and the existing SEC304 gate."""

import re

from e2e import data
from e2e.browser import all_text, onboard, open_flutter, reopen, type_into
from e2e.flowbase import Context, Flow

KEYS = ("chem-process-reading", "math-triangle-coordinate-proof", "math-circle-radius-proof")


def _proof_text_visible(proof, rendered):
    # MathText exposes the full source text without inline-math dollar delimiters.
    return all(given.replace("$", "") in rendered for given in proof["givens"]) and (
        proof["claim"].replace("$", "") in rendered
    )


def _post_click(page, button, suffix):
    with page.expect_response(
        lambda response: response.request.method == "POST" and response.url.endswith(suffix)
    ) as pending:
        button.click()
    response = pending.value
    if not response.ok:
        raise RuntimeError(f"{suffix}: {response.status} {response.text()}")
    return response.json()["data"]


def run(ctx: Context) -> None:
    from playwright.sync_api import expect

    for key in KEYS:
        sample = data.question(key)
        expected = sample["teaching"]["visual"]
        page = ctx.new_page()
        open_flutter(page)
        onboard(page)
        reopen(page, f"#/questions/{data.question_id(key)}/solve")
        text = all_text(page)
        if sample["answer_mode"] == "proof":
            ctx.check(
                "几何必要条件与求证在独立阶段文字完整给出",
                _proof_text_visible(sample["content"]["proof"], text),
            )
            ctx.shot(page, f"{expected['template_id']}-independent")
        else:
            ctx.check("工艺必要流程不依赖提交后图解", sample["content"]["stem"] in text)
        blocked = _post_click(
            page, page.get_by_role("button", name="看图理解", exact=True), "/next"
        )
        ctx.check(
            f"{expected['template_id']}独立阶段不下发图解或后备答案",
            bool(blocked["events"])
            and not blocked["session"]["used_solution"]
            and all(
                event["type"] == "notice"
                and not {"template_id", "params", "caption", "static_fallback"}.intersection(
                    event["payload"]
                )
                for event in blocked["events"]
            ),
        )
        if sample["answer_mode"] == "proof":
            # Authored attempt is deliberately not a verbatim reference proof.
            type_into(
                page,
                page.get_by_role("textbox", name=re.compile("第 1 步：这一步写什么")),
                "我使用题目给定的条件进行比较。",
            )
            result = _post_click(
                page, page.get_by_role("button", name="提交", exact=True), "/submit"
            )
            ctx.check(
                "新几何证明仍pending且不因文字判对错",
                result["evaluation"]["state"] == "pending"
                and result["evaluation"]["is_correct"] is None,
            )
        else:
            page.get_by_role("button", name="我想直接看解析…", exact=True).click()
            result = _post_click(
                page, page.get_by_role("button", name="看解析", exact=True), "/next"
            )
            ctx.check("工艺完整解析由明确动作记录", result["session"]["used_solution"])
        visual = _post_click(page, page.get_by_role("button", name="看图理解", exact=True), "/next")
        event = next(event for event in visual["events"] if event["type"] == "visual")
        ctx.check(
            f"{expected['template_id']}解析阶段使用审核数值规格",
            event["payload"]["template_id"] == expected["template_id"]
            and event["payload"]["params"] == expected["params"],
        )
        page.wait_for_function(
            "caption => Array.from(document.querySelectorAll('flt-semantics')).some("
            "node => ((node.getAttribute('aria-label') || '') + (node.textContent || '')).includes(caption))",
            arg=expected["caption"],
        )
        text = all_text(page)
        if sample["answer_mode"] == "proof":
            page.wait_for_function(
                "() => Array.from(document.querySelectorAll('flt-semantics')).some(node => "
                "((node.getAttribute('aria-label') || '') + (node.textContent || '')).includes('不能凭外观推断'))"
            )
            text = all_text(page)
            ctx.check("几何图示保留非比例与不能推断关系说明", "不能凭外观推断" in text)
        else:
            ctx.check(
                "通用工艺骨架文字展示既有支路与回流", "有分离到支路" in text and "回流" in text
            )
        slider = page.get_by_role("slider").first
        expect(slider).to_be_enabled()
        value = "node => ['aria-valuenow','aria-valuetext','aria-label'].map(key => node.getAttribute(key) || '').join('|')"
        before = slider.evaluate(value)
        writes = sum(method in {"POST", "PUT", "DELETE"} for method, _, _ in page.responses)
        slider.press("ArrowRight" if expected["params"].get("focus", 0) == 0 else "ArrowLeft")
        page.wait_for_function(
            "before => {const node = document.querySelector('[role=slider]'); return node && "
            "['aria-valuenow','aria-valuetext','aria-label'].map(key => node.getAttribute(key) || '').join('|') !== before}",
            arg=before,
        )
        ctx.check(f"{expected['template_id']}焦点可用键盘调整", slider.evaluate(value) != before)
        ctx.check(
            "调整图示焦点不写服务端或调用模型",
            sum(method in {"POST", "PUT", "DELETE"} for method, _, _ in page.responses) == writes,
        )
        ctx.shot(page, expected["template_id"])


FLOW = Flow(
    name="subject_diagrams",
    title="流程与几何工程图示、必要题设及解析阶段门控",
    needs=frozenset({"flutter"}),
    run=run,
)
