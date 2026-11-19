"""Download real locally saved answers after an API-offline cold page load."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import zipfile

from e2e import data
from e2e.api_client import Api
from e2e.browser import all_text, onboard, open_flutter, reopen, stored, stored_all, tap, type_into
from e2e.flowbase import Flow
from e2e.flows.student_draft_recovery import _record, _wait
from e2e.flows.student_scan import image_fixture
from e2e.servers import API_URL


def run(ctx):
    key = "math-mono-quadratic"
    question_id = data.question_id(key)
    selected = data.question(key)["content"]["options"][0]["key"]
    page = ctx.new_page()
    open_flutter(page)
    onboard(page)
    tap(page, "练习", wait=2500)
    tap(page, data.title_of(key), wait=3500)
    tap(page, f"选项 {selected}")
    if not ctx.check(
        "实际页面作答已保存本机",
        _wait(
            page,
            lambda: (
                _record(page, "draft", question_id).get("answer", {}).get("selected") == [selected]
            ),
        ),
    ):
        return
    owner = stored(page, "auth.userId")
    token = stored(page, "auth.token")
    api = Api(token)
    parent_identity = Api("").post("/dev/local-identities?role=parent")
    parent = Api(parent_identity["access_token"])

    def invite(client):
        state = client.get("/me/parent-links")
        return client.post(
            "/me/parent-invites",
            {"expected_parent_invite_revision": state["parent_invite_revision"]},
        )

    used_invite = invite(api)
    parent.post("/parents/links", {"code": used_invite["code"]})
    granted = api.get("/me/parent-links")["links"][0]
    api.post(
        f"/me/parent-links/{granted['id']}/revoke",
        {"expected_authorization_revision": granted["authorization_revision"]},
    )
    pending_invite = invite(api)
    other_identity = Api("").post("/dev/local-identities?role=student")
    other_invite = invite(Api(other_identity["access_token"]))
    scan_stem = "自编拍题文字导出验证"
    foreign_stem = "另一学生的私有拍题文字"

    def saved_scan(client, stem):
        data = image_fixture()["buffer"]
        media = client.post(
            "/scans/uploads",
            dict(
                purpose="scan",
                mime="image/png",
                size_bytes=len(data),
                sha256=hashlib.sha256(data).hexdigest(),
            ),
        )
        client.request(
            "PUT",
            f"/scans/uploads/{media['media_id']}/content",
            {"content_base64": base64.b64encode(data).decode()},
        )
        candidate = client.post("/scans", {"media_id": media["media_id"]})
        client.post(
            f"/scans/{candidate['id']}/confirm",
            {
                "stem_text": stem,
                "expressions": [{"span_id": "s1", "latex": "2x+1", "confidence": None}],
            },
        )
        return media["media_id"], candidate["id"]

    scan_media, scan_id = saved_scan(api, scan_stem)
    foreign_media, foreign_scan = saved_scan(Api(other_identity["access_token"]), foreign_stem)
    if not ctx.check(
        "作答已实际同步服务端",
        _wait(
            page,
            lambda: any(
                method == "PUT" and path.endswith("/draft") and status == 200
                for method, path, status in page.responses
            ),
        ),
    ):
        return

    session_id = _record(page, "draft", question_id)["sessionId"]
    resource_key = f"u/{owner}/resource-journal/session/{session_id}"

    def local_resource():
        return json.loads(stored(page, resource_key) or "{}")

    tap(page, "给点提示", wait=1400)
    if not ctx.check(
        "实际辅导操作及回执已存本机",
        _wait(
            page,
            lambda: any(
                c.get("phase") == "acked" for c in local_resource().get("history", {}).values()
            ),
        ),
    ):
        return
    attempt_id = _record(page, "draft", question_id)["attemptId"]
    solve_path = (
        f"#/questions/{question_id}/solve?origin=practice&session={session_id}&attempt={attempt_id}"
    )

    scan_key = f"u/{owner}/scan_workspace_bundle"

    def local_scans():
        return json.loads(stored(page, scan_key) or "{}")

    local_first = "本机第一份未同步拍题文字"
    local_second = "本机第二份未同步拍题文字"
    reopen(page, "#/scan")
    type_into(page, page.get_by_role("textbox", name="手工填写题干"), local_first)
    type_into(page, page.get_by_role("textbox", name="手工补充表达式（LaTeX，可选）"), "x+1")
    with page.expect_file_chooser() as chooser:
        page.get_by_role("button", name="选择图片", exact=True).click()
    chooser.value.set_files(image_fixture())

    def abort_upload(route):
        route.abort()

    page.context.route(API_URL + "/scans/uploads", abort_upload)
    page.get_by_role("button", name="上传临时图片", exact=True).click()
    if not ctx.check(
        "真实页面上传失败后保留本机拍题文字和原请求",
        _wait(
            page,
            lambda: any(
                w["stem"] == local_first and w["commands"]
                for w in local_scans().get("workspaces", [])
            ),
        ),
    ):
        return
    page.context.unroute(API_URL + "/scans/uploads", abort_upload)
    tap(page, "开始新图片并保留旧记录", exact=True)
    tap(page, "保留旧记录，开始新图片", exact=True)
    type_into(page, page.get_by_role("textbox", name="手工填写题干"), local_second)
    if not ctx.check(
        "新图片保留旧未知请求并保存第二份本机文字",
        _wait(
            page,
            lambda: (
                {w["stem"] for w in local_scans().get("workspaces", [])}
                == {local_first, local_second}
            ),
        ),
    ):
        return
    reopen(page, "#/profile")
    local_name = "本机未同步称呼"
    type_into(page, page.get_by_role("textbox", name="你的称呼"), local_name)
    if not ctx.check(
        "实际页面保留尚未同步的资料修改",
        _wait(
            page,
            lambda: (
                json.loads(stored(page, f"u/{owner}/profile_bundle") or "{}")
                .get("edit", {})
                .get("display_name")
                == local_name
            ),
        ),
    ):
        return
    server_button = page.get_by_role("button", name="导出服务端学习记录", exact=True)
    with page.expect_download() as pending:
        server_button.click()
    server_path = ctx.out_dir / "server-learning-records.json"
    pending.value.save_as(server_path)
    server_raw = server_path.read_text(encoding="utf-8")
    server_data = json.loads(server_raw)
    ctx.check(
        "服务端导出归属与范围正确",
        server_data["scope"] == "server_learning_records"
        and server_data["profile"]["user_id"] == owner,
    )
    ctx.check(
        "服务端文件包含实际同步作答",
        any(
            draft["answer"]["selected_options"] == [selected]
            for session in server_data["sessions"]
            for draft in session["drafts"]
        ),
    )
    ctx.check("服务端导出不含登录凭据", token not in server_raw)
    usage = server_data["model_usage"]
    ctx.check(
        "实际下载保留个人模型用量范围且不冒充账单",
        usage["history_complete"] is False
        and usage["costs_are_billing"] is False
        and usage["identity_scope"] == "current_server_pseudonym"
        and isinstance(usage["calls"], list)
        and isinstance(usage["budget_days"], list)
        and "student_pseudonym" not in json.dumps(usage)
        and "scope_key" not in json.dumps(usage),
    )
    stored_scans = server_data["stored_scan_records"]
    ctx.check(
        "实际下载保留本人拍题确认文字和表达式",
        len(stored_scans) == 1
        and stored_scans[0]["scan"]["id"] == scan_id
        and stored_scans[0]["scan"]["status"] == "confirmed"
        and stored_scans[0]["scan"]["stem_text"] == scan_stem
        and stored_scans[0]["scan"]["expressions"][0]["latex"] == "2x+1",
    )
    ctx.check(
        "拍题导出仅含原图引用和有效期",
        stored_scans[0]["media_id"] == scan_media
        and stored_scans[0]["expires_at"]
        and "content_base64" not in server_raw
        and "object_key" not in server_raw,
    )
    ctx.check(
        "拍题导出排除另一学生的私有文字和图片引用",
        all(secret not in server_raw for secret in (foreign_stem, foreign_scan, foreign_media)),
    )
    records = server_data["parent_access_records"]
    ctx.check(
        "导出包含实际撤销授权且标明历史不完整",
        records["history_complete"] is False
        and len(records["links"]) == 1
        and records["links"][0]["id"] == granted["id"]
        and records["links"][0]["revoked_at"] is not None,
    )
    ctx.check(
        "导出保留已兑换和待兑换邀请元数据",
        {row["id"] for row in records["invites"]} == {used_invite["id"], pending_invite["id"]},
    )
    ctx.check(
        "导出排除邀请码及家长身份资料",
        all(
            secret not in server_raw
            for secret in (
                used_invite["code"],
                pending_invite["code"],
                parent_identity["user_id"],
                parent_identity["access_token"],
                "code_hash",
                "redeemed_by",
            )
        ),
    )
    ctx.check(
        "导出排除另一学生的授权范围",
        other_identity["user_id"] not in server_raw and other_invite["id"] not in server_raw,
    )
    ctx.check(
        "服务端导出标明未同步内容等排除范围", "unsynced_device_data" in server_data["excluded"]
    )
    ctx.shot(page, "server-export-downloaded")
    media_before = stored_all(page)
    replies_before = len(page.responses)
    with (
        page.expect_response(
            lambda response: (
                response.request.method == "GET"
                and response.url.endswith("/api/v1/profile/media-export")
            )
        ) as media_response,
        page.expect_download() as pending,
    ):
        page.get_by_role("button", name="下载当前媒体ZIP", exact=True).click()
    media_path = ctx.out_dir / "current-student-media.zip"
    pending.value.save_as(media_path)
    archive_bytes = media_path.read_bytes()
    advertised = media_response.value.json()["data"]
    ctx.check(
        "真实下载媒体ZIP后缀大小摘要与接口一致",
        pending.value.suggested_filename.endswith(".zip")
        and len(archive_bytes) == advertised["size_bytes"]
        and hashlib.sha256(archive_bytes).hexdigest() == advertised["sha256"],
    )
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        files = {name: archive.read(name) for name in archive.namelist() if name != "manifest.json"}
    ctx.check(
        "媒体ZIP清单明确本人当前范围且不冒称完整历史快照",
        manifest["owner_id"] == owner
        and manifest["scope"] == "server_current_student_media"
        and manifest["history_complete"] is False
        and manifest["consistent_snapshot"] is False,
    )
    ctx.check(
        "媒体ZIP实际包含本人已上传原图及清单引用",
        files == {f"media/{scan_media}.png": image_fixture()["buffer"]}
        and manifest["files_count"] == 1
        and manifest["objects"][0]["file_name"] == f"media/{scan_media}.png",
    )
    manifest_raw = json.dumps(manifest)
    ctx.check(
        "媒体ZIP排除他人图片凭据及内部存储信息",
        all(
            secret not in manifest_raw
            for secret in (
                foreign_media,
                other_identity["user_id"],
                token,
                "object_key",
                "upload_url",
            )
        )
        and all(foreign_media not in name for name in files),
    )
    ctx.check(
        "媒体下载不改本机记录也不发起写操作",
        stored_all(page) == media_before
        and all(method == "GET" for method, _, _ in page.responses[replies_before:]),
    )
    page.context.route(API_URL + "/**", lambda route: route.abort())
    reopen(page, "#/profile")
    button = page.get_by_role("button", name="导出本机练习草稿", exact=True)
    if not ctx.check("API离线冷加载仍可导出", _wait(page, lambda: button.count() == 1)):
        ctx.shot(page, "offline-export-unavailable")
        return
    page.get_by_role("button", name="导出服务端学习记录", exact=True).click()
    ctx.check(
        "服务端导出离线失败后仍可本机导出",
        _wait(page, lambda: "导出失败，服务端和本机记录未改动" in all_text(page)),
    )
    page.get_by_role("button", name="下载当前媒体ZIP", exact=True).click()
    ctx.check(
        "离线媒体下载明确失败而不复用缓存图片",
        _wait(page, lambda: "导出失败，原媒体未改动" in all_text(page)),
    )
    before = stored_all(page)
    with page.expect_download() as pending:
        button.click()
    download = pending.value
    path = ctx.out_dir / "practice-drafts.json"
    download.save_as(path)
    raw = path.read_text(encoding="utf-8")
    artifact = json.loads(raw)
    ctx.check(
        "实际下载JSON限定本机练习范围",
        artifact["scope"] == "local_exercise_drafts" and artifact["format_version"] == 1,
    )
    ctx.check("导出归属为当前学生", artifact["owner_id"] == owner)
    ctx.check(
        "文件包含实际作答",
        any(
            d["questionId"] == question_id and d["answer"]["selected"] == [selected]
            for d in artifact["drafts"]
        ),
    )
    ctx.check(
        "文件不含登录凭据或命令日志",
        token not in raw and "idempotencyKey" not in raw and "writes" not in raw,
    )
    ctx.check("导出未改写任何本机数据", stored_all(page) == before)
    ctx.check("浏览器显示下载交付提示", _wait(page, lambda: "已发起下载" in all_text(page)))

    export_requests = []
    page.on(
        "request",
        lambda request: (
            export_requests.append(request.url) if request.url.startswith(API_URL) else None
        ),
    )
    with page.expect_download() as pending:
        page.get_by_role("button", name="导出本机拍题记录", exact=True).click()
    scan_path = ctx.out_dir / "local-scan-records.json"
    pending.value.save_as(scan_path)
    scan_raw = scan_path.read_text(encoding="utf-8")
    scan_export = json.loads(scan_raw)
    ctx.check(
        "离线实际下载拍题文件标明本人和本机范围",
        scan_export["scope"] == "local_scan_records"
        and scan_export["owner_id"] == owner
        and scan_export["format_version"] == 1,
    )
    workspaces = scan_export["workspaces"]
    ctx.check(
        "拍题文件包含新旧两份未同步文字与表达式",
        {w["stem_text"] for w in workspaces} == {local_first, local_second}
        and any(w["expression_text"] == "x+1" for w in workspaces),
    )
    original = next(w for w in local_scans()["workspaces"] if w["stem"] == local_first)
    exported = next(w for w in workspaces if w["stem_text"] == local_first)
    ctx.check(
        "拍题导出保留原未知请求的键状态和正文而不重试",
        len(exported["commands"]) == 1
        and exported["commands"][0]["key"] == original["commands"][0]["key"]
        and exported["commands"][0]["phase"] == original["commands"][0]["phase"]
        and exported["commands"][0]["body"] == original["commands"][0]["body"],
    )
    ctx.check(
        "本机拍题文件不含凭据原图上传地址或其他学生内容",
        all(
            secret not in scan_raw
            for secret in (
                token,
                foreign_stem,
                other_identity["user_id"],
                "content_base64",
                "upload_url",
                base64.b64encode(image_fixture()["buffer"]).decode(),
            )
        ),
    )
    ctx.check(
        "拍题导出不改写本机记录且无服务端请求",
        stored_all(page) == before and not export_requests,
    )
    with page.expect_download() as pending:
        page.get_by_role("button", name="导出本机恢复记录", exact=True).click()
    recovery_path = ctx.out_dir / "local-recovery-records.json"
    pending.value.save_as(recovery_path)
    recovery_raw = recovery_path.read_text(encoding="utf-8")
    recovery = json.loads(recovery_raw)
    cache_prefix = f"flutter.u/{owner}/question/"
    expected_cache = {
        key.removeprefix(cache_prefix): json.loads(json.loads(value))
        for key, value in stored_all(page).items()
        if key.startswith(cache_prefix)
    }
    exported_cache = {
        r["question_id"] + (f"/{r['workspace']}" if r["workspace"] else ""): r["question"]
        for r in recovery["question_cache"]
    }
    ctx.check(
        "恢复文件保留实际缓存题面和工作区且不重建版本",
        bool(expected_cache) and exported_cache == expected_cache,
    )
    ctx.check(
        "离线实际下载本人恢复记录且声明快照边界",
        recovery["owner_id"] == owner
        and recovery["format_version"] == 1
        and recovery["scope"] == "local_student_recovery_records"
        and recovery["history_complete"] is False
        and recovery["consistent_snapshot"] is False,
    )
    ctx.check(
        "恢复文件保留尚未同步的资料修改", recovery["profile"]["edit"]["display_name"] == local_name
    )
    resource = next(r for r in recovery["resources"] if r["id"] == session_id)
    original = local_resource()["history"][local_resource()["current"]]
    command = next(c for c in resource["commands"] if c["intent_id"] == original["intentId"])
    ctx.check(
        "恢复文件保留辅导原请求键正文及已知回执",
        command["key"] == original["idempotencyKey"]
        and command["body"] == original["body"]
        and command["phase"] == original["phase"]
        and len(resource["view"]["events"]) == len(local_resource()["view"]["events"]),
    )
    ctx.check(
        "恢复文件排除邀请码家长身份凭据和运行时私有字段",
        all(
            secret not in recovery_raw
            for secret in (
                token,
                parent_identity["user_id"],
                parent_identity["access_token"],
                other_identity["user_id"],
                used_invite["code"],
                pending_invite["code"],
                "activeEpoch",
                "checksum",
                "code_hash",
                "fingerprint",
            )
        ),
    )
    ctx.check(
        "恢复记录下载不改本机且无服务端请求", stored_all(page) == before and not export_requests
    )
    practice = next(p for p in recovery["practice"] if p["question_id"] == question_id)
    practice_bundle = json.loads(stored(page, f"u/{owner}/draft-bundle/{question_id}"))
    creations = [
        c
        for record in practice_bundle.get("creationIntents", {}).values()
        for c in record["history"].values()
    ]
    ctx.check(
        "恢复文件保留全部现存建会话建作答请求键与状态",
        bool(creations)
        and {
            (c["session_key"], c["attempt_key"], c["phase"]) for c in practice["creation_commands"]
        }
        == {(c["sessionKey"], c["attemptKey"], c["phase"]) for c in creations},
    )
    syncs = [c for c in practice["write_commands"] if c["lane"] == "draft_sync"]
    stored_syncs = [
        c
        for lanes in practice_bundle.get("writeJournal", {}).values()
        for c in lanes.get("draft_sync", {}).get("history", {}).values()
    ]
    ctx.check(
        "恢复文件保留真实同步命令和原正文",
        bool(syncs)
        and {c["key"] for c in syncs} == {c["idempotencyKey"] for c in stored_syncs}
        and all(
            next(c for c in syncs if c["key"] == raw["idempotencyKey"])["body"] == raw["body"]
            for raw in stored_syncs
        ),
    )
    ctx.check(
        "恢复文件保留已收到的固定版本题面但排除运行时代次",
        all(c["question_snapshot"]["id"] == question_id for c in practice["contexts"])
        and "activationEpoch" not in recovery_raw
        and "sourceHash" not in recovery_raw,
    )
    ctx.shot(page, "offline-export-downloaded")

    page.context.unroute(API_URL + "/**")
    reopen(page, solve_path)
    tap(page, "提交", exact=True, wait=1800)

    def submitted_command():
        bundle = json.loads(stored(page, f"u/{owner}/draft-bundle/{question_id}") or "{}")
        return next(
            (
                c
                for lanes in bundle.get("writeJournal", {}).values()
                for c in lanes.get("submit", {}).get("history", {}).values()
                if c.get("phase") == "acked"
            ),
            None,
        )

    if not ctx.check(
        "真实页面提交成功且原回执已在本机确认", _wait(page, lambda: submitted_command() is not None)
    ):
        return
    page.context.route(API_URL + "/**", lambda route: route.abort())
    reopen(page, "#/profile")
    export_button = page.get_by_role("button", name="导出本机恢复记录", exact=True)
    if not ctx.check(
        "提交后断网冷加载仍保留恢复导出", _wait(page, lambda: export_button.count() == 1)
    ):
        return
    after_submit_before = stored_all(page)
    export_requests.clear()
    with page.expect_download() as pending:
        export_button.click()
    submitted_path = ctx.out_dir / "local-recovery-after-submit.json"
    pending.value.save_as(submitted_path)
    exported = json.loads(submitted_path.read_text(encoding="utf-8"))
    expected = submitted_command()
    practice = next(p for p in exported["practice"] if p["question_id"] == question_id)
    submitted = next(
        c for c in practice["write_commands"] if c["intent_id"] == expected["intentId"]
    )
    ctx.check(
        "离线下载保留实际提交键正文与同会话回执",
        submitted["key"] == expected["idempotencyKey"]
        and submitted["body"] == expected["body"]
        and submitted["phase"] == "acked"
        and submitted["result"]["session"]["id"] == session_id
        and submitted["result"]["attempt"]["id"] == expected["attemptId"],
    )
    ctx.check(
        "提交档案下载不重放任何请求且不改本机",
        stored_all(page) == after_submit_before and not export_requests,
    )
    ctx.shot(page, "offline-submitted-recovery-downloaded")


FLOW = Flow("local_draft_export", "本机及服务端学习记录导出", frozenset({"flutter"}), run)
