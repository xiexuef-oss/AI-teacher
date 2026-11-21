"""变异检查：故意把关键的安全与教学规则改坏，确认测试会失败。

用途：有些测试是在实现写完之后才第一次运行的，没有亲眼见过它们失败。这里逐条把实现改坏
（去掉归属校验、放开泄题门控、把"判不出来"改成直接判错……），每改一处就跑对应的测试，
测试必须变红；如果某处改坏了测试仍然全绿，说明那条规则没有被测试守住。

    uv run python tools/mutation_check.py                # 全部，时长随目标与环境变化
    uv run python tools/mutation_check.py --only 归属     # 只跑名称里带"归属"的几条
    uv run python tools/mutation_check.py --output var/mutation-runs  # 指定证据根目录

每组先验证未修改实现的基线，再检查变异后的JUnit测试结果。收集/导入/执行错误、跳过、
无测试与缺少报告均不算抓到。真实基础设施目标需显式隔离凭据；缺配置为not_run且默认
退出非零。仅本机不完整检查可显式加--allow-not-run，汇总仍不把not_run计入覆盖。

每次CLI运行新建唯一证据目录：子运行的stdout/stderr、原始JUnit和分类元数据均保留，
summary.json关联每个目标的原始基线与变异结果。基线失败不再丢失原始诊断，也不计为抓到。

脚本会临时改动源码并在结束时（包括中途出错时）恢复原样。运行期间不要同时跑别的测试，也不要启动服务。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "var"
_EVIDENCE_ROOT: ContextVar[Path | None] = ContextVar("mutation_evidence_root", default=None)
API = REPO_ROOT / "services" / "api" / "tutor_api"
GATEWAY = REPO_ROOT / "services" / "ai_gateway" / "ai_gateway"


@dataclass(frozen=True)
class Mutation:
    name: str
    path: Path
    original: str
    mutated: str
    tests: tuple[str, ...]


MUTATIONS = [
    Mutation(
        "V14-R06 待回收错误标记无关知识点",
        API / "services" / "learning_pack_worker.py",
        "if node in waiting_nodes and (item is None or node not in item.knowledge_ids)",
        "if waiting_nodes",
        ("tests/unit/test_paper_review_schedule.py::test_paper_plan_only_marks_waiting_knowledge_points",),
    ),
    Mutation(
        "V14-R06 数值旧答案结构误计正确",
        API / "services" / "learning_pack_evidence.py",
        '    if not isinstance(values, dict):\n        return "unknown"',
        '    if not isinstance(values, dict):\n        return "correct"',
        ("tests/unit/test_learning_pack_evidence.py",),
    ),
    Mutation(
        "V14-R06 区间转写无法确认却计为错误",
        API / "services" / "learning_pack_evidence.py",
        '    return "incorrect" if outcome.status == "incorrect" else "unknown"',
        '    return "incorrect"',
        ("tests/unit/test_learning_pack_evidence.py",),
    ),
    Mutation(
        "V14-R06 已下载解析的校正仍推进独立复测",
        API / "services" / "paper_review_schedule.py",
        "item.transcript_revision != 0 and item.before_solution is not True",
        "item.transcript_revision != 0 and item.before_solution is None",
        ("tests/api/test_learning_pack_request.py::test_worker_publishes_both_sample_pdfs",),
    ),
    Mutation(
        "V14-R06 复测忽略变式优先",
        API / "services" / "learning_pack_worker.py",
        "key=lambda pair: pair[:2], default=None",
        "key=lambda pair: pair[0], default=None",
        (
            "tests/api/test_learning_pack_request.py::test_due_physics_review_takes_priority_over_fresh_chemistry",
            "tests/api/test_learning_pack_request.py::test_paper_math_inequality_review_switches_from_numeric_fill_to_choice",
            "tests/api/test_learning_pack_request.py::test_paper_chemistry_stoichiometry_cross_variant",
        ),
    ),
    Mutation(
        "CircleSpec A点绘图范围可绕过",
        REPO_ROOT / "packages" / "visual_templates" / "registry.json",
        '"name": "a_position", "label": "A点相对绘图位置", "min": 0.05, "max": 0.2',
        '"name": "a_position", "label": "A点相对绘图位置", "min": 0.05, "max": 2',
        ("tests/gateway/test_subject_visual_templates.py",),
    ),
    Mutation(
        "CircleSpec B点绘图范围可绕过",
        REPO_ROOT / "packages" / "visual_templates" / "registry.json",
        '"name": "b_position", "label": "B点相对绘图位置", "min": 0.3, "max": 0.45',
        '"name": "b_position", "label": "B点相对绘图位置", "min": 0.3, "max": 2',
        ("tests/gateway/test_subject_visual_templates.py",),
    ),
    Mutation(
        "CircleSpec 焦点允许分数",
        REPO_ROOT / "packages" / "visual_templates" / "registry.json",
        '"name": "focus", "label": "观察已知点", "min": 0, "max": 3, "step": 1, "default": 0, "integer": true',
        '"name": "focus", "label": "观察已知点", "min": 0, "max": 3, "step": 1, "default": 0, "integer": false',
        ("tests/gateway/test_subject_visual_templates.py",),
    ),
    Mutation(
        "CircleSpec 圆的关键变形未列泄题标记",
        REPO_ROOT / "services" / "api" / "seed" / "questions" / "proof.yaml",
        "'OA^2=1'",
        "'unused-circle-marker'",
        ("tests/content/test_proof_content.py",),
    ),
    Mutation(
        "SDKResume 忽略持久路由摘要",
        GATEWAY / "durable.py",
        'context["routing_digest"] != digest or ',
        "",
        ("tests/unit/test_sdk_resume.py",),
    ),
    Mutation(
        "SDKResume 忽略供应商身份摘要",
        GATEWAY / "durable.py",
        'context["provider_digest"] != binding("provider", provider)',
        "False",
        ("tests/unit/test_sdk_resume.py",),
    ),
    Mutation(
        "SDKResume 不恢复外部供应商历史",
        GATEWAY / "durable.py",
        'external_used.add(context["provider_digest"])',
        "pass",
        ("tests/unit/test_sdk_resume.py",),
    ),
    Mutation(
        "SDKResume 允许游标倒退",
        GATEWAY / "invocation_state.py",
        "if not (same_retry or fallback):",
        "if False:",
        ("tests/unit/test_sdk_resume.py",),
    ),
    Mutation(
        "SDKResume 未持久保存游标",
        GATEWAY / "invocation_state.py",
        'result["attempts"][-1]["sdk_context"] = deepcopy(sdk_context)',
        "pass",
        ("tests/unit/test_sdk_resume.py",),
    ),
    Mutation(
        "SDKResume 未保存已确认的后续动作",
        GATEWAY / "invocation_state.py",
        'context["continuation"] = retry_disposition',
        'context["continuation"] = "none"',
        ("tests/unit/test_sdk_resume.py",),
    ),
    Mutation(
        "SDKResume 仍重放原重试序号",
        GATEWAY / "durable.py",
        'context["retry_index"] + 1',
        'context["retry_index"] + 0',
        ("tests/unit/test_sdk_resume.py",),
    ),
    Mutation(
        "SDKResume 路由摘要不绑定模型",
        GATEWAY / "durable.py",
        '"model": c.model or gateway._env.get(c.model_env or ""),',
        '"model": None,',
        ("tests/unit/test_sdk_resume.py",),
    ),
    Mutation(
        "SDKChain 未确认失败也允许续尝试",
        GATEWAY / "invocation_state.py",
        'if not result["attempts"][-1].get("retryable_failure") or any(',
        "if False and any(",
        ("tests/unit/test_sdk_attempt_chain.py",),
    ),
    Mutation(
        "SDKChain 累计请求成本只看当前估算",
        API / "services" / "invocation_store.py",
        "if prior_cost + estimated_cost_micros > request_cost_cap:",
        "if False:",
        ("tests/unit/test_sdk_attempt_chain.py",),
    ),
    Mutation(
        "SDKChain 未知网络故障当作确认失败",
        GATEWAY / "gateway.py",
        'if error.outcome_known and error.kind != "timeout"',
        'if error.kind != "timeout"',
        ("tests/unit/test_sdk_attempt_chain.py",),
    ),
    Mutation(
        "SDKChain 跨供应商回退忽略授权",
        GATEWAY / "durable.py",
        "and not request.privacy_policy.allow_cross_provider_fallback",
        "and False",
        ("tests/unit/test_sdk_attempt_chain.py",),
    ),
    Mutation(
        "SDKChain 续尝试不推进fence",
        GATEWAY / "invocation_state.py",
        '            result["fence"] += 1\n        if any(a["attempt_id"]',
        '            result["fence"] += 0\n        if any(a["attempt_id"]',
        ("tests/unit/test_sdk_attempt_chain.py",),
    ),
    Mutation(
        "SDKChain 每次尝试重复收请求额度",
        API / "services" / "invocation_store.py",
        "bucket.request_count += 0 if continuation else 1",
        "bucket.request_count += 1",
        ("tests/unit/test_sdk_attempt_chain.py",),
    ),
    Mutation(
        "SDKChain 恢复期限读取首个尝试",
        API / "services" / "invocation_store.py",
        'deadline = record["attempts"][-1].get("recover_after")',
        'deadline = record["attempts"][0].get("recover_after")',
        ("tests/unit/test_sdk_attempt_chain.py",),
    ),
    Mutation(
        "SDKChain IO后允许供应商类型改变",
        GATEWAY / "gateway.py",
        "if self._config.providers[plan.provider].external != plan.external:",
        "if False:",
        ("tests/unit/test_sdk_attempt_chain.py",),
    ),
    Mutation(
        "SDKChain 回退仍选择首个候选",
        GATEWAY / "durable.py",
        "candidate_index=index",
        "candidate_index=0",
        ("tests/unit/test_sdk_attempt_chain.py",),
    ),
    Mutation(
        "SDKChain 跨日重收准入",
        API / "services" / "invocation_store.py",
        'if not continuation:\n                result["quota_day"]',
        'if True:\n                result["quota_day"]',
        ("tests/unit/test_sdk_attempt_chain.py",),
    ),
    Mutation(
        "DurableSDK 旧入口未接持久调用",
        GATEWAY / "gateway.py",
        "            return invoke(self, request, *self._durable_sdk)",
        "            pass",
        (
            "tests/unit/test_sdk_durable_invocations.py::test_sdk_sends_only_after_committed_attempt_and_settles_once",
        ),
    ),
    Mutation(
        "DurableSDK 应用绑定后仍进入SDK路径",
        GATEWAY / "gateway.py",
        '        if self._durable_sdk is not None and self._external_dispatch_mode == "legacy":\n            from ai_gateway.durable import invoke',
        "        if self._durable_sdk is not None:\n            from ai_gateway.durable import invoke",
        (
            "tests/unit/test_sdk_durable_invocations.py::test_sdk_mode_cannot_bypass_application_durable_or_disabled_policy",
        ),
    ),
    Mutation(
        "DurableSDK 结算前交付正文",
        GATEWAY / "durable.py",
        "                record = store.settle_metadata(",
        "                return response\n                record = store.settle_metadata(",
        (
            "tests/unit/test_sdk_durable_invocations.py::test_sdk_storage_failure_never_exposes_output_or_private_details[settle_metadata]",
        ),
    ),
    Mutation(
        "DurableSDK 遗漏共享暂停检查",
        GATEWAY / "gateway.py",
        "            guards.append(self._durable_sdk[0].cost_gate.can_send)",
        "            pass",
        (
            "tests/unit/test_sdk_durable_invocations.py::test_sdk_pause_committed_after_dispatch_blocks_the_adapter",
        ),
    ),
    Mutation(
        "DurableSDK 忽略发送前业务策略切换",
        GATEWAY / "gateway.py",
        '        if legacy_only and self._external_dispatch_mode != "legacy":',
        "        if False:",
        (
            "tests/unit/test_sdk_durable_invocations.py::test_sdk_revocation_after_dispatch_keeps_conservative_reservation[durable]",
        ),
    ),
    Mutation(
        "DurableSDK 共享检查IO后不复查供应商",
        GATEWAY / "gateway.py",
        "        if not self._candidate_available(plan.provider, plan.model, request):",
        "        if False:",
        (
            "tests/unit/test_sdk_durable_invocations.py::test_sdk_rechecks_authorization_and_price_after_guard_io[provider]",
        ),
    ),
    Mutation(
        "DurableSDK 共享检查IO后不复查价格与上限",
        GATEWAY / "gateway.py",
        "        if self._estimate(plan.provider, request) > min(",
        "        if False and self._estimate(plan.provider, request) > min(",
        (
            "tests/unit/test_sdk_durable_invocations.py::test_sdk_rechecks_authorization_and_price_after_guard_io",
        ),
    ),
    Mutation(
        "S3Readiness 探针跳过本机SDK配置校验",
        API / "s3_blob_store.py",
        "            validate_local_s3_client(self.client)",
        "            pass",
        (
            "tests/unit/test_s3_blob_store.py::test_local_readiness_rechecks_bounded_loopback_configuration_before_io",
        ),
    ),
    Mutation(
        "S3Readiness 等待时间失去上限",
        API / "s3_blob_store.py",
        "or not 0 < wait <= 15",
        "or not 0 < wait",
        (
            "tests/unit/test_s3_blob_store.py::test_local_readiness_rechecks_bounded_loopback_configuration_before_io",
        ),
    ),
    Mutation(
        "S3Readiness 接受命名空间外返回键",
        API / "s3_blob_store.py",
        'or not item["Key"].startswith(self.prefix)',
        "or False",
        (
            "tests/unit/test_s3_blob_store.py::test_local_readiness_rejects_malformed_or_unscoped_page",
        ),
    ),
    Mutation(
        "S3Readiness 重定向忽略协议变化",
        API / "s3_blob_store.py",
        "if (destination.scheme, destination.netloc.lower()) != (\n                address.scheme,\n                address.netloc.lower(),\n            ):",
        "if destination.netloc.lower() != address.netloc.lower():",
        (
            "tests/unit/test_s3_blob_store.py::test_local_readiness_only_lists_one_scoped_key_without_probing_writes",
        ),
    ),
    Mutation(
        "S3Readiness 接线跳过外部端点拦截",
        API / "runtime_dependencies.py",
        "        validate_local_s3_client(media.client)",
        "        pass",
        (
            "tests/unit/test_runtime_dependencies.py::test_managed_accepts_explicit_bounded_loopback_s3_without_io",
        ),
    ),
    Mutation(
        "S3Readiness 启动跳过对象存储探针",
        API / "runtime_dependencies.py",
        "            if media.ping() is not True:",
        "            if False:",
        (
            "tests/integration/test_managed_runtime.py::test_managed_mysql_redis_s3_startup_lists_without_writes_or_client_ownership",
        ),
    ),
    Mutation(
        "MediaArchive 受控环境读取本地媒体",
        API / "services" / "media_service.py",
        '    if ctx.settings.env != "local" or value is None:',
        "    if value is None:",
        (
            "tests/integration/test_managed_runtime.py::test_managed_media_export_is_explicitly_unavailable_without_touching_store",
        ),
    ),
    Mutation(
        "MediaArchive 忽略筛选参数",
        API / "services" / "student_media_export.py",
        "    if ctx.request.query_params:",
        "    if False:",
        ("tests/api/test_scans.py::test_media_export_role_precedes_query_and_storage_checks",),
    ),
    Mutation(
        "MediaArchive 放行审核用途",
        API / "services" / "student_media_export.py",
        '                if blob.purpose not in {"ocr_source", "handwriting"}:',
        "                if False:",
        (
            "tests/api/test_scans.py::test_media_export_downloads_only_owned_student_files_and_preserves_unuploaded_states",
        ),
    ),
    Mutation(
        "MediaArchive 由记录自己指定归属",
        API / "services" / "student_media_export.py",
        "                    blob, state, ctx.student_id, ctx.now(), ctx.settings.media_max_bytes",
        "                    blob, state, blob.owner, ctx.now(), ctx.settings.media_max_bytes",
        (
            "tests/api/test_scans.py::test_media_export_rejects_invalid_listing_before_creating_archive[owner]",
        ),
    ),
    Mutation(
        "MediaArchive 跳过原图完整性",
        API / "services" / "student_media_export.py",
        "                    if (\n                        len(data) != blob.size_bytes\n                        or hashlib.sha256(data).hexdigest() != blob.sha256\n                    ):",
        "                    if False:",
        (
            "tests/api/test_scans.py::test_media_export_read_failure_is_whole_file_failure_without_private_error[bytes]",
        ),
    ),
    Mutation(
        "MediaArchive 允许重名文件",
        API / "services" / "student_media_export.py",
        "                if media_id in seen_ids:",
        "                if False:",
        (
            "tests/api/test_scans.py::test_media_export_rejects_invalid_listing_before_creating_archive[duplicate]",
        ),
    ),
    Mutation(
        "MediaArchive 写入前不检查大小",
        API / "services" / "student_media_export.py",
        "                    if output.tell() + len(data) > MAX_ARCHIVE_BYTES:",
        "                    if False:",
        ("tests/api/test_scans.py::test_media_export_rejects_file_bytes_before_zip_write",),
    ),
    Mutation(
        "MediaArchive 清单大小不计上限",
        API / "services" / "student_media_export.py",
        "        if len(content) > MAX_ARCHIVE_BYTES:",
        "        if False:",
        ("tests/api/test_scans.py::test_media_export_manifest_bytes_count_toward_archive_limit",),
    ),
    Mutation(
        "MediaArchive 拍题临时字节不可读",
        API / "services" / "student_media_export.py",
        '                        temporary=blob.purpose == "ocr_source",',
        "                        temporary=False,",
        (
            "tests/api/test_scans.py::test_media_export_downloads_only_owned_student_files_and_preserves_unuploaded_states",
        ),
    ),
    Mutation(
        "MediaArchive 未确认手写被读取",
        API / "services" / "student_media_export.py",
        '                if state == "ready" or (state == "pending" and blob.purpose == "ocr_source"):',
        '                if state in {"ready", "pending"}:',
        (
            "tests/api/test_scans.py::test_media_export_downloads_only_owned_student_files_and_preserves_unuploaded_states",
        ),
    ),
    Mutation(
        "MediaArchive 不传源对象限额",
        API / "services" / "student_media_export.py",
        "        rows = store.list_owned(owner=ctx.student_id, now=ctx.now(), limit=MAX_OBJECTS)",
        "        rows = store.list_owned(owner=ctx.student_id, now=ctx.now(), limit=10_000)",
        (
            "tests/api/test_scans.py::test_media_export_limits_never_return_partial_archive[objects]",
        ),
    ),
    Mutation(
        "MediaArchive 底层错误泄露",
        API / "services" / "student_media_export.py",
        '    except (BlobNotFound, BlobStorageUnavailable, OSError, ValueError, TypeError):\n        raise ApiError(\n            503, "export_unavailable", "媒体暂时无法完整验证，未生成不完整档案，请稍后重试"\n        ) from None',
        '    except (BlobNotFound, BlobStorageUnavailable, OSError, ValueError, TypeError) as error:\n        raise ApiError(503, "export_unavailable", str(error)) from None',
        (
            "tests/api/test_scans.py::test_media_export_read_failure_is_whole_file_failure_without_private_error[storage]",
        ),
    ),
    Mutation(
        "BlobListing 缺少归属过滤",
        API / "blob_store.py",
        'return blob.owner == owner and blob.expires_at > now and state != "deleted"',
        'return blob.expires_at > now and state != "deleted"',
        (
            "tests/unit/test_blob_listing.py::test_listing_is_complete_owned_read_only_and_preserves_saved_states",
        ),
    ),
    Mutation(
        "BlobListing 过期记录仍可用",
        API / "blob_store.py",
        'return blob.owner == owner and blob.expires_at > now and state != "deleted"',
        'return blob.owner == owner and state != "deleted"',
        (
            "tests/unit/test_blob_listing.py::test_listing_is_complete_owned_read_only_and_preserves_saved_states",
        ),
    ),
    Mutation(
        "BlobListing 删除记录仍可用",
        API / "blob_store.py",
        'return blob.owner == owner and blob.expires_at > now and state != "deleted"',
        "return blob.owner == owner and blob.expires_at > now",
        (
            "tests/unit/test_blob_listing.py::test_listing_is_complete_owned_read_only_and_preserves_saved_states",
        ),
    ),
    Mutation(
        "BlobListing 内存忽略全局扫描上限",
        API / "blob_store.py",
        "            for scanned, (blob, _, state) in enumerate(self._entries.values(), 1):\n                if scanned > limit:",
        "            for scanned, (blob, _, state) in enumerate(self._entries.values(), 1):\n                if False:",
        (
            "tests/unit/test_blob_listing.py::test_listing_limit_counts_foreign_entries_instead_of_returning_false_empty[memory]",
        ),
    ),
    Mutation(
        "BlobListing 本机忽略全局扫描上限",
        API / "blob_store.py",
        '                for scanned, manifest in enumerate(self.root.glob("*.json"), 1):\n                    if scanned > limit:',
        '                for scanned, manifest in enumerate(self.root.glob("*.json"), 1):\n                    if False:',
        (
            "tests/unit/test_blob_listing.py::test_listing_limit_counts_foreign_entries_instead_of_returning_false_empty[filesystem]",
        ),
    ),
    Mutation(
        "BlobListing S3忽略全局扫描上限",
        API / "s3_blob_store.py",
        "                    if scanned > limit:",
        "                    if False:",
        (
            "tests/unit/test_blob_listing.py::test_listing_limit_counts_foreign_entries_instead_of_returning_false_empty[s3]",
        ),
    ),
    Mutation(
        "BlobListing S3只遍历第一页",
        API / "s3_blob_store.py",
        '                if not page["IsTruncated"]:',
        "                if True:",
        (
            "tests/unit/test_blob_listing.py::test_listing_is_complete_owned_read_only_and_preserves_saved_states[s3]",
        ),
    ),
    Mutation(
        "BlobListing 错用清理游标",
        API / "s3_blob_store.py",
        "        token, tokens, keys = None, set(), set()",
        "        token, tokens, keys = self._cleanup_cursor, set(), set()",
        (
            "tests/unit/test_blob_listing.py::test_listing_is_complete_owned_read_only_and_preserves_saved_states[s3]",
        ),
    ),
    Mutation(
        "BlobListing S3跳过读取前字节上限",
        API / "s3_blob_store.py",
        "                if max_bytes is not None and length > max_bytes:",
        "                if False:",
        (
            "tests/unit/test_blob_listing.py::test_s3_listing_bounds_bytes_before_reading_body_and_closes_stream",
        ),
    ),
    Mutation(
        "BlobListing 坏文件被当作空清单",
        API / "blob_store.py",
        '        except Exception:\n            raise BlobStorageUnavailable("Media listing unavailable") from None',
        "        except Exception:\n            return []",
        (
            "tests/unit/test_blob_listing.py::test_filesystem_bad_manifest_fails_whole_listing_without_leaking_or_deleting",
        ),
    ),
    Mutation(
        "ScanExport 置信度范围不校验",
        API / "schemas.py",
        '    status: Literal["processing", "needs_confirmation", "confirmed", "failed"]\n    confidence: float | None = Field(strict=True, ge=0, le=1)',
        '    status: Literal["processing", "needs_confirmation", "confirmed", "failed"]\n    confidence: float | None = Field(strict=True)',
        (
            "tests/api/test_scans.py::test_corrupt_scan_fails_whole_export_without_leaking_or_deleting[confidence]",
        ),
    ),
    Mutation(
        "ModelUsageExport 读取其他学生调用",
        API / "services" / "student_learning_export.py",
        ".where(ModelCallAudit.student_pseudonym == key)",
        ".where(True)",
        ("tests/api/test_student_model_usage_export.py",),
    ),
    Mutation(
        "ModelUsageExport 读取平台预算",
        API / "services" / "student_learning_export.py",
        ".where(ModelBudgetUsage.scope == STUDENT_SCOPE, ModelBudgetUsage.scope_key == key)",
        ".where(ModelBudgetUsage.scope_key == key)",
        ("tests/api/test_student_model_usage_export.py",),
    ),
    Mutation(
        "ModelUsageExport 读取其他学生预算",
        API / "services" / "student_learning_export.py",
        ".where(ModelBudgetUsage.scope == STUDENT_SCOPE, ModelBudgetUsage.scope_key == key)",
        ".where(ModelBudgetUsage.scope == STUDENT_SCOPE)",
        ("tests/api/test_student_model_usage_export.py",),
    ),
    Mutation(
        "ModelUsageExport 调用绕过总数限制",
        API / "services" / "student_learning_export.py",
        "for row in rows(\n                select(ModelCallAudit)",
        "for row in ctx.db.scalars(\n                select(ModelCallAudit)",
        ("tests/api/test_student_model_usage_export.py",),
    ),
    Mutation(
        "ModelUsageExport 预算绕过总数限制",
        API / "services" / "student_learning_export.py",
        "for row in rows(\n                select(ModelBudgetUsage)",
        "for row in ctx.db.scalars(\n                select(ModelBudgetUsage)",
        ("tests/api/test_student_model_usage_export.py",),
    ),
    Mutation(
        "ScanExport 受控环境访问proto表",
        API / "services" / "student_learning_export.py",
        '    if ctx.settings.env != "local":',
        "    if False:",
        (
            "tests/integration/test_managed_runtime.py::test_managed_export_marks_local_scan_scope_unprovided_without_querying_proto",
        ),
    ),
    Mutation(
        "ScanExport 导出他人拍题记录",
        API / "services" / "student_learning_export.py",
        "        .where(ScanRecord.owner_id == ctx.student_id)",
        "        .where(True)",
        (
            "tests/api/test_scans.py::test_stored_scan_export_is_owned_whitelisted_and_independent_of_expired_images",
        ),
    ),
    Mutation(
        "ScanExport 拍题记录不计上限",
        API / "services" / "student_learning_export.py",
        "    for row in rows(\n        select(ScanRecord)",
        "    for row in ctx.db.scalars(\n        select(ScanRecord)",
        ("tests/api/test_scans.py::test_stored_scans_count_toward_export_limit",),
    ),
    Mutation(
        "ScanExport 跳过保存记录身份核对",
        API / "services" / "student_learning_export.py",
        "            if value.id != UUID(row.id):",
        "            if False:",
        (
            "tests/api/test_scans.py::test_corrupt_scan_fails_whole_export_without_leaking_or_deleting[id]",
        ),
    ),
    Mutation(
        "ScanExport 导出未知保存状态",
        API / "schemas.py",
        '    status: Literal["processing", "needs_confirmation", "confirmed", "failed"]',
        "    status: str",
        (
            "tests/api/test_scans.py::test_corrupt_scan_fails_whole_export_without_leaking_or_deleting[status]",
        ),
    ),
    Mutation(
        "ScanExport 错误标记被猜成布尔值",
        API / "schemas.py",
        "    low_confidence: StrictBool",
        "    low_confidence: bool",
        (
            "tests/api/test_scans.py::test_corrupt_scan_fails_whole_export_without_leaking_or_deleting[flag]",
        ),
    ),
    Mutation(
        "ScanExport 私有payload未过滤",
        API / "services" / "student_learning_export.py",
        "                    scan=value.model_dump(",
        "                    scan=dict(row.payload) or value.model_dump(",
        (
            "tests/api/test_scans.py::test_stored_scan_export_is_owned_whitelisted_and_independent_of_expired_images",
        ),
    ),
    Mutation(
        "ScanExport 过期文字被静默跳过",
        API / "services" / "student_learning_export.py",
        "        try:\n            value = ExportScanPayloadOut.model_validate(row.payload)",
        "        if row.expires_at <= ctx.now():\n            continue\n        try:\n            value = ExportScanPayloadOut.model_validate(row.payload)",
        (
            "tests/api/test_scans.py::test_stored_scan_export_is_owned_whitelisted_and_independent_of_expired_images",
        ),
    ),
    Mutation(
        "ScanExport 错误信息泄露原记录",
        API / "services" / "student_learning_export.py",
        '                503, "export_unavailable", "部分学习记录暂时无法验证，未生成不完整导出，请稍后重试"',
        '                503, "export_unavailable", str(row.payload)',
        (
            "tests/api/test_scans.py::test_corrupt_scan_fails_whole_export_without_leaking_or_deleting[status]",
        ),
    ),
    Mutation(
        "ParentExport 导出其他学生授权",
        API / "services" / "student_learning_export.py",
        "                    .where(ParentStudentLink.student_id == ctx.student_id)",
        "                    .where(True)",
        ("tests/api/test_student_learning_export.py",),
    ),
    Mutation(
        "ParentExport 导出其他学生邀请",
        API / "services" / "student_learning_export.py",
        "                    .where(ParentInvite.student_id == ctx.student_id)",
        "                    .where(True)",
        ("tests/api/test_student_learning_export.py",),
    ),
    Mutation(
        "ParentExport 授权不计入总量",
        API / "services" / "student_learning_export.py",
        "                for row in rows(\n                    select(ParentStudentLink)",
        "                for row in ctx.db.scalars(\n                    select(ParentStudentLink)",
        ("tests/api/test_student_learning_export.py",),
    ),
    Mutation(
        "ParentExport 邀请不计入总量",
        API / "services" / "student_learning_export.py",
        "                for row in rows(\n                    select(ParentInvite)",
        "                for row in ctx.db.scalars(\n                    select(ParentInvite)",
        ("tests/api/test_student_learning_export.py",),
    ),
    Mutation(
        "ParentExport 错称完整历史",
        API / "schemas.py",
        "class ExportParentAccessRecordsOut(BaseModel):\n    history_complete: Literal[False] = False",
        "class ExportParentAccessRecordsOut(BaseModel):\n    history_complete: Literal[False] = True",
        ("tests/api/test_student_learning_export.py",),
    ),
    Mutation(
        "ManagedExternal 接受网络供应商非外部标记",
        GATEWAY / "config.py",
        '            raise ValueError("openai_compatible 供应商必须标记为 external")',
        "            pass",
        ("tests/gateway/test_routing.py",),
    ),
    Mutation(
        "ManagedExternal 缓存配置跳过供应商类型一致性",
        GATEWAY / "gateway.py",
        '            return None, "provider_kind_mismatch"',
        "            pass",
        ("tests/gateway/test_routing.py",),
    ),
    Mutation(
        "ManagedExternal 忽略外调配置意图",
        API / "runtime_dependencies.py",
        '        not bool(getattr(gateway, "_allow_external_calls", False)),',
        "        True,",
        (
            "tests/unit/test_runtime_dependencies.py",
            "tests/unit/test_external_invocation_wiring.py",
        ),
    ),
    Mutation(
        "ManagedExternal 未绑定禁止外调策略",
        API / "services" / "invocation_runtime.py",
        "                gateway.disable_external_calls()",
        "                pass",
        (
            "tests/unit/test_runtime_dependencies.py",
            "tests/unit/test_external_invocation_wiring.py",
        ),
    ),
    Mutation(
        "ManagedExternal 发送前忽略禁止策略",
        GATEWAY / "gateway.py",
        '            if not self._allow_external_calls or self._external_dispatch_mode == "disabled":',
        "            if not self._allow_external_calls:",
        (
            "tests/unit/test_runtime_dependencies.py",
            "tests/unit/test_external_invocation_wiring.py",
        ),
    ),
    Mutation(
        "ManagedExternal 再绑定持久策略削弱禁止策略",
        GATEWAY / "gateway.py",
        '        if self._external_dispatch_mode == "legacy":',
        "        if True:",
        (
            "tests/unit/test_runtime_dependencies.py",
            "tests/unit/test_external_invocation_wiring.py",
        ),
    ),
    Mutation(
        "InvocationReport 忽略分页边界",
        API / "services" / "invocation_maintenance.py",
        "        query = query.where(intents.c.id > after)",
        "        pass",
        ("tests/unit/test_invocation_report.py",),
    ),
    Mutation(
        "InvocationReport 跳过Schema与状态验证",
        API / "services" / "invocation_maintenance.py",
        '        value = store.transitions._checked(row["metadata_json"], row["fence"], row["state"])',
        '        value = row["metadata_json"]',
        ("tests/unit/test_invocation_report.py",),
    ),
    Mutation(
        "InvocationReport 只读清单允许组合恢复",
        REPO_ROOT / "tools" / "model_cost_report.py",
        "    if (args.after_invocation and not args.invocations) or (args.invocations and any(review)):",
        "    if False:",
        ("tests/unit/test_invocation_report.py",),
    ),
    Mutation(
        "ExternalDurable 启动允许无持久外调",
        API / "services" / "invocation_runtime.py",
        '        raise ValueError("外部模型业务调用需要启用持久模型调用")',
        "        pass",
        ("tests/unit/test_external_invocation_wiring.py",),
    ),
    Mutation(
        "ExternalDurable 启动未绑定旧入口保护",
        API / "services" / "invocation_runtime.py",
        "            gateway.require_durable_external_calls()",
        "            pass",
        ("tests/unit/test_external_invocation_wiring.py",),
    ),
    Mutation(
        "ExternalDurable IO后允许旧入口外调",
        GATEWAY / "gateway.py",
        '            and self._external_dispatch_mode != "legacy"',
        "            and False",
        ("tests/unit/test_external_invocation_wiring.py",),
    ),
    Mutation(
        "DiagnosticHistory 历史列表移除本人过滤",
        API / "services" / "diagnostic_service.py",
        "    query = select(DiagnosticRun).where(DiagnosticRun.student_id == student_id)",
        "    query = select(DiagnosticRun)",
        ("tests/api/test_diagnostics.py", "tests/api/test_student_learning_export.py"),
    ),
    Mutation(
        "DiagnosticHistory 相同时间游标忽略ID边界",
        API / "services" / "diagnostic_service.py",
        "and_(DiagnosticRun.created_at == anchor.created_at, DiagnosticRun.id < anchor.id)",
        "and_(DiagnosticRun.created_at == anchor.created_at, True)",
        ("tests/api/test_diagnostics.py", "tests/api/test_student_learning_export.py"),
    ),
    Mutation(
        "DiagnosticHistory 导出其他学生计划",
        API / "services" / "student_learning_export.py",
        "        .where(DiagnosticRun.student_id == ctx.student_id)",
        "        .where(True)",
        ("tests/api/test_diagnostics.py", "tests/api/test_student_learning_export.py"),
    ),
    Mutation(
        "DiagnosticHistory 导出条目不计上限",
        API / "services" / "student_learning_export.py",
        "    rows(\n        select(DiagnosticItem).join(DiagnosticRun).where(DiagnosticRun.student_id == ctx.student_id)\n    )",
        "    # Mutation: omit plan items from the record limit.",
        ("tests/api/test_diagnostics.py", "tests/api/test_student_learning_export.py"),
    ),
    Mutation(
        "DiagnosticHistory 导出取消SQLite读取快照",
        API / "services" / "student_learning_export.py",
        '        connection.exec_driver_sql("BEGIN")',
        "        pass",
        (
            "tests/api/test_scans.py::test_scan_export_uses_original_snapshot_during_concurrent_confirmation",
            "tests/api/test_diagnostics.py::test_sqlite_export_keeps_one_read_snapshot_during_concurrent_plan_creation",
            "tests/api/test_student_learning_export.py::test_export_parent_records_keep_one_snapshot_during_concurrent_revoke",
        ),
    ),
    Mutation(
        "Diagnostic 轮次跨账号可读",
        API / "services" / "diagnostic_service.py",
        "DiagnosticRun.id == run_id, DiagnosticRun.student_id == student_id",
        "DiagnosticRun.id == run_id",
        ("tests/api/test_diagnostics.py",),
    ),
    Mutation(
        "Diagnostic 旧进度命令覆盖新轮次",
        API / "services" / "diagnostic_service.py",
        "    if state.revision != expected_revision:",
        "    if False:",
        ("tests/api/test_diagnostics.py",),
    ),
    Mutation(
        "Diagnostic 将主观题混入客观摸底",
        API / "services" / "diagnostic_service.py",
        "if question.answer_mode not in grading.SUBJECTIVE_MODES",
        "if True",
        ("tests/api/test_diagnostics.py",),
    ),
    Mutation(
        "Diagnostic 后续提交覆盖首份结果",
        API / "services" / "diagnostic_service.py",
        "        Attempt.submission_no == 1,",
        "        Attempt.submission_no >= 1,",
        ("tests/api/test_diagnostics.py",),
    ),
    Mutation(
        "Diagnostic 未确认作答被计入对错",
        API / "services" / "diagnostic_service.py",
        'attempt.evaluation_state == "verified" and attempt.is_correct is not None',
        "attempt.is_correct is not None",
        ("tests/api/test_diagnostics.py",),
    ),
    Mutation(
        "Diagnostic 开题丢失固定版本保护",
        API / "services" / "diagnostic_service.py",
        "            expected_question_version=item.question_version,",
        "            expected_question_version=None,",
        ("tests/api/test_diagnostics.py",),
    ),
    Mutation(
        "CostPrecharge 丢失发送前估算记账",
        GATEWAY / "gateway.py",
        "            if estimate:\n                try:",
        "            if False:\n                try:",
        (
            "tests/gateway/test_predispatch_cost.py",
            "tests/unit/test_predispatch_cost_persistence.py",
        ),
    ),
    Mutation(
        "CostPrecharge 结束重复收取已记估算",
        GATEWAY / "gateway.py",
        "extra = max(0, (usage.estimated_cost_micros or 0) - state.reserved_estimate)",
        "extra = max(0, usage.estimated_cost_micros or 0)",
        (
            "tests/gateway/test_predispatch_cost.py",
            "tests/unit/test_predispatch_cost_persistence.py",
        ),
    ),
    Mutation(
        "CostPrecharge 提交后跳过共享暂停",
        GATEWAY / "gateway.py",
        "            # may have changed. Committed estimates are not automatically refunded.\n            if error := self._dispatch_error():",
        "            # may have changed. Committed estimates are not automatically refunded.\n            if False:",
        (
            "tests/gateway/test_predispatch_cost.py",
            "tests/unit/test_predispatch_cost_persistence.py",
        ),
    ),
    Mutation(
        "CostPrecharge 提交后跳过当前授权",
        GATEWAY / "gateway.py",
        "            if not self._candidate_available(name, model, request, legacy=True):\n                state.other_failures += 1\n                return None\n            if self._estimate",
        "            if False:\n                state.other_failures += 1\n                return None\n            if self._estimate",
        (
            "tests/gateway/test_predispatch_cost.py",
            "tests/unit/test_predispatch_cost_persistence.py",
        ),
    ),
    Mutation(
        "CostPrecharge 提交后绕过每日金额保护",
        GATEWAY / "gateway.py",
        "            if self._config.budgets.has_daily_cost_limits:",
        "            if False:",
        (
            "tests/gateway/test_predispatch_cost.py",
            "tests/unit/test_predispatch_cost_persistence.py",
        ),
    ),
    Mutation(
        "CostPrecharge 提交后绕过报价及请求上限",
        GATEWAY / "gateway.py",
        "            if self._estimate(name, request) > estimate or state.reserved_estimate > min(\n                cost_cap, self._config.budgets.per_request_max_cost_micros\n            ):",
        "            if False:",
        (
            "tests/gateway/test_predispatch_cost.py",
            "tests/unit/test_predispatch_cost_persistence.py",
        ),
    ),
    Mutation(
        "ContentCoverage 多专题重复累计独立题数",
        REPO_ROOT / "tools" / "check_sample_content_coverage.py",
        '"valid_samples": valid_samples,',
        '"valid_samples": sum(counts.values()),',
        ("tests/unit/test_sample_content_coverage.py",),
    ),
    Mutation(
        "ContentCoverage 工程样题改标后计入覆盖",
        REPO_ROOT / "tools" / "check_sample_content_coverage.py",
        'or row["source_license"] == ENGINEERING_SAMPLE_LICENSE',
        "or False",
        ("tests/unit/test_sample_content_coverage.py",),
    ),
    Mutation(
        "ContentCoverage 重复版本计成多道题",
        REPO_ROOT / "tools" / "check_sample_content_coverage.py",
        "and identifiers[parent] == 1",
        "and True",
        ("tests/unit/test_sample_content_coverage.py",),
    ),
    Mutation(
        "ContentCoverage 作者自审计入覆盖",
        REPO_ROOT / "tools" / "check_sample_content_coverage.py",
        'and row["author_id"] != row["reviewer_id"]',
        "and True",
        ("tests/unit/test_sample_content_coverage.py",),
    ),
    Mutation(
        "ContentCoverage 单专题充当全专题完成",
        REPO_ROOT / "tools" / "check_sample_content_coverage.py",
        'all(topic["missing_samples"] == 0 for topic in topics)',
        'any(topic["missing_samples"] == 0 for topic in topics)',
        ("tests/unit/test_sample_content_coverage.py",),
    ),
    Mutation(
        "LinuxDoc 未为显式DOC启用最小运行时",
        API / "services" / "document_parser_process.py",
        'doc_conversion=kind == "doc" and settings.import_doc_converter is not None',
        "doc_conversion=False",
        ("tests/unit/test_document_parser_process.py",),
    ),
    Mutation(
        "LinuxDoc 私有网络被取消",
        API / "services" / "document_sandbox.py",
        '        "--unshare-net",\n',
        "",
        (
            "tests/integration/test_linux_parser_sandbox.py::test_host_files_environment_and_network_are_not_available",
        ),
    ),
    Mutation(
        "LinuxDoc 注册表不再只读挂载",
        API / "services" / "document_sandbox.py",
        '*(["--ro-bind", "/etc/libreoffice", "/etc/libreoffice"] if doc_conversion else [])',
        '*(["--bind", "/etc/libreoffice", "/etc/libreoffice"] if doc_conversion else [])',
        (
            "tests/integration/test_linux_parser_sandbox.py::test_host_files_environment_and_network_are_not_available",
        ),
    ),
    Mutation(
        "S3Media 忽略媒体归属",
        API / "s3_blob_store.py",
        "or (owner is not None and blob.owner != owner)",
        "or False",
        ("tests/unit/test_s3_blob_store.py",),
    ),
    Mutation(
        "S3Media 空owner绕过公开访问",
        API / "s3_blob_store.py",
        "if owner is None and not (deleted and expired):",
        "if False:",
        ("tests/unit/test_s3_blob_store.py",),
    ),
    Mutation(
        "S3Media 覆盖写丢失ETag条件",
        API / "s3_blob_store.py",
        'else {"IfMatch": tag}',
        "else {}",
        ("tests/unit/test_s3_blob_store.py",),
    ),
    Mutation(
        "S3Media 忽略远端响应大小上限",
        API / "s3_blob_store.py",
        "not 0 <= length <= self._body_limit",
        "False",
        ("tests/unit/test_s3_blob_store.py",),
    ),
    Mutation(
        "S3Media 冲突被当成输入错误",
        API / "blob_store.py",
        "class BlobWriteConflict(RuntimeError):",
        "class BlobWriteConflict(ValueError):",
        ("tests/api/test_media_storage_failures.py",),
    ),
    Mutation(
        "S3Media 不可用返回未契约化500",
        API / "errors.py",
        'else (503, "storage_unavailable",',
        'else (500, "storage_unavailable",',
        ("tests/api/test_media_storage_failures.py",),
    ),
    Mutation(
        "LearnTopics 目录绕过可见题筛选",
        API / "services" / "question_service.py",
        "    visible = deliverable_questions(\n        db, scope, subject=subject, answer_mode=answer_mode, scope_filter=scope_filter\n    )",
        '    visible = [(q, "general") for q in db.scalars(select(Question))]',
        ("tests/api/test_question_topics.py",),
    ),
    Mutation(
        "LearnTopics 忽略选中知识点",
        API / "services" / "question_service.py",
        "    if knowledge_id is not None:",
        "    if False:",
        ("tests/api/test_question_topics.py",),
    ),
    Mutation(
        "LearnTopics 首次学习入口永远隐藏",
        API / "services" / "task_planner.py",
        "cold_start=not attempted",
        "cold_start=False",
        ("tests/api/test_question_topics.py",),
    ),
    Mutation(
        "StudentExport 丢失本人归属过滤",
        API / "services" / "student_learning_export.py",
        "    owned = StudySession.student_id == ctx.student_id",
        "    owned = True",
        ("tests/api/test_student_learning_export.py",),
    ),
    Mutation(
        "StudentExport 忽略记录上限",
        API / "services" / "student_learning_export.py",
        "        if remaining < 0:",
        "        if False:",
        ("tests/api/test_student_learning_export.py",),
    ),
    Mutation(
        "StudentExport 忽略文件上限",
        API / "services" / "student_learning_export.py",
        '    if len(result.model_dump_json().encode("utf-8")) > MAX_BYTES:',
        "    if False:",
        ("tests/api/test_student_learning_export.py",),
    ),
    Mutation(
        "ImageQuote 未核验图像单价仍发送",
        GATEWAY / "gateway.py",
        "            or pricing.image_unit_micros is not None",
        "            or True",
        ("tests/gateway/test_image_pricing_gate.py",),
    ),
    # Both pre/post-commit checks share this helper; one removed check is no
    # longer a bypass. Mutate the common image context instead of duplicating it.
    Mutation(
        "ImageQuote 共享候选检查丢失图像上下文",
        GATEWAY / "gateway.py",
        "self._resolve(c, request) == (model, None)",
        "self._resolve(c) == (model, None)",
        ("tests/gateway/test_image_pricing_gate.py",),
    ),
    Mutation(
        "RetryAdmission 忽略当前候选授权",
        GATEWAY / "gateway.py",
        "self._resolve(c, request) == (model, None)",
        "True",
        ("tests/gateway/test_retry_admission.py",),
    ),
    Mutation(
        "RetryAdmission 忽略收紧的请求限额",
        GATEWAY / "gateway.py",
        "            if state.reserved_estimate + estimate > min(\n                cost_cap, self._config.budgets.per_request_max_cost_micros\n            ):",
        "            if state.reserved_estimate + estimate > min(\n                cost_cap, cost_cap\n            ):",
        ("tests/gateway/test_retry_admission.py",),
    ),
    Mutation(
        "DailyCost 忽略累计金额",
        API / "services" / "invocation_store.py",
        "                    cost_limit is not None\n                    and bucket.estimated_cost_micros + estimated_cost_micros > cost_limit",
        "                    False\n                    and bucket.estimated_cost_micros + estimated_cost_micros > cost_limit",
        ("tests/unit/test_daily_cost_admission.py",),
    ),
    Mutation(
        "DailyCost 旧入口绕过限额",
        GATEWAY / "gateway.py",
        "        if budgets.has_daily_cost_limits:",
        "        if False:",
        ("tests/gateway/test_daily_cost_limits.py",),
    ),
    Mutation(
        "DailyCost 文档OCR遗漏平台金额",
        API / "services" / "document_durable_ocr.py",
        "                platform_cost_limit=limits.platform_daily_max_cost_micros,",
        "                platform_cost_limit=None,",
        ("tests/api/test_document_durable_ocr.py",),
    ),
    Mutation(
        "DailyCost 换讲遗漏学生金额",
        API / "services" / "durable_rephrase.py",
        "            student_cost_limit=limits.student_daily_max_cost_micros,",
        "            student_cost_limit=None,",
        ("tests/api/test_durable_rephrase.py",),
    ),
    Mutation(
        "SharedPause 单次计划跳过暂停",
        GATEWAY / "gateway.py",
        "        if error := self._dispatch_error():\n            return response(error=error)",
        "        if False:\n            return response(error=error)",
        ("tests/gateway/test_dispatch_pause_guard.py",),
    ),
    Mutation(
        "SharedPause 重试回退跳过暂停",
        GATEWAY / "gateway.py",
        "            if guard is None:",
        "            if True:",
        ("tests/gateway/test_dispatch_pause_guard.py",),
    ),
    Mutation(
        "SharedPause 关闭开关绕过既有暂停",
        API / "services" / "invocation_runtime.py",
        "    if enabled or {dispatch_gate.name, incidents.name} & tables:",
        "    if enabled:",
        ("tests/unit/test_gateway_pause_wiring.py",),
    ),
    Mutation(
        "SharedPause 检查故障放行",
        GATEWAY / "gateway.py",
        '                logger.warning("shared model dispatch guard unavailable")\n                return "BUDGET_UNAVAILABLE"',
        '                logger.warning("shared model dispatch guard unavailable")\n                return None',
        ("tests/gateway/test_dispatch_pause_guard.py",),
    ),
    Mutation(
        "CostPause 绕过共享暂停",
        API / "services" / "invocation_store.py",
        '            if gate["paused"]:',
        "            if False:",
        ("tests/unit/test_model_cost_gate.py",),
    ),
    Mutation(
        "CostPause 超预占不暂停",
        API / "services" / "model_cost_gate.py",
        '        if self.policy == "pause_platform" or gate["paused"]:',
        "        if False:",
        ("tests/unit/test_model_cost_gate.py",),
    ),
    Mutation(
        "CostPause 恢复忽略最新事件",
        API / "services" / "model_cost_gate.py",
        '            if gate["incident_id"] != incident_id:',
        "            if False:",
        ("tests/unit/test_model_cost_gate.py",),
    ),
    Mutation(
        "DurableOCR 恢复沿用旧状态快照",
        API / "services" / "document_durable_ocr.py",
        '            record = row["metadata_json"]\n            stale = record["context_digest"]',
        '            record = record\n            stale = record["context_digest"]',
        ("tests/api/test_document_durable_ocr.py",),
    ),
    Mutation(
        "DurableOCR 发送退回旧网关重试入口",
        API / "services" / "document_durable_ocr.py",
        "        response = self.gateway.invoke_single_attempt(self.plan)",
        "        response = self.gateway.invoke(request)",
        ("tests/api/test_document_durable_ocr.py",),
    ),
    Mutation(
        "DurableOCR 页面先于调用完成状态提交",
        API / "services" / "document_durable_ocr.py",
        "            self._save(db, page)\n            self.store.applied_in_transaction(",
        "            self._save(db, page)\n            db.commit()\n            self.store.applied_in_transaction(",
        ("tests/api/test_document_durable_ocr.py",),
    ),
    Mutation(
        "OCRRecovery 发送标记未提交",
        API / "services" / "document_ocr_progress.py",
        "            db.commit()  # No open transaction is held during the gateway call.",
        "            db.rollback()  # Fault: dispatch marker is lost before network call.",
        ("tests/api/test_document_ocr_recovery.py",),
    ),
    Mutation(
        "OCRRecovery 输入改变仍回用结果",
        API / "services" / "document_ocr_progress.py",
        'prior.state == "completed" and prior.request_digest == digest and cached',
        'prior.state == "completed" and cached',
        ("tests/api/test_document_ocr_recovery.py",),
    ),
    Mutation(
        "OCRRecovery 迟到结果绕过租约",
        API / "services" / "document_ocr_progress.py",
        "        job = self.active(db, self.job_id, self.lease, self.clock())",
        "        job = db.get(DocumentImportJob, self.job_id)",
        ("tests/api/test_document_ocr_recovery.py",),
    ),
    Mutation(
        "PROD302B 单次计划被重复发送",
        GATEWAY / "gateway.py",
        "            available = plan.owner is self and not plan.consumed",
        "            available = plan.owner is self",
        ("tests/gateway/test_single_attempt.py",),
    ),
    Mutation(
        "PROD302B 旧上下文仍能应用",
        API / "services" / "invocation_context.py",
        "    if current.digest != expected_digest:",
        "    if False:",
        ("tests/api/test_invocation_context.py",),
    ),
    Mutation(
        "PROD302B 重试突破累计估算",
        GATEWAY / "gateway.py",
        "            if state.reserved_estimate + estimate > min(\n                cost_cap, self._config.budgets.per_request_max_cost_micros\n            ):",
        "            if False:",
        ("tests/gateway/test_budget_admission.py",),
    ),
    Mutation(
        "DRAFT303CParent 旧生成命令擅用当前版本",
        API / "services" / "parent_service.py",
        "    if profile.parent_invite_revision != expected_parent_invite_revision:",
        "    expected_parent_invite_revision = profile.parent_invite_revision\n    if profile.parent_invite_revision != expected_parent_invite_revision:",
        ("tests/api/test_parent_recovery.py",),
    ),
    Mutation(
        "DRAFT303CParent 旧撤销命令越过授权代际",
        API / "services" / "parent_service.py",
        "    if link.authorization_revision != expected_authorization_revision:",
        "    if False:",
        ("tests/api/test_parent_recovery.py",),
    ),
    Mutation(
        "DRAFT303CParent 撤销读取旧RR授权",
        API / "services" / "parent_service.py",
        "        .where(ParentStudentLink.id == link_id, ParentStudentLink.student_id == student_id)\n        .with_for_update()",
        "        .where(ParentStudentLink.id == link_id, ParentStudentLink.student_id == student_id)",
        ("tests/integration/test_parent_revision_mysql.py",),
    ),
    Mutation(
        "DRAFT303CParent 生成先提交后写回执",
        API / "services" / "parent_service.py",
        "    db.flush()\n    return invite, code",
        "    db.commit()\n    return invite, code",
        ("tests/api/test_parent_recovery.py",),
    ),
    Mutation(
        "DRAFT303CParent 撤销绕过历史成功回执",
        API / "routers" / "parents.py",
        "    return run_idempotent(ctx, body, 200, action)",
        '    with ctx.transaction():\n        payload = action("")\n    return ok(payload)',
        ("tests/api/test_parent_recovery.py",),
    ),
    Mutation(
        "DRAFT303C 资料跳过版本前置检查",
        API / "services" / "profile_service.py",
        "    if profile.revision != body.expected_revision:",
        "    if False:",
        ("tests/api/test_profile_revision.py",),
    ),
    Mutation(
        "DRAFT303C 资料绕过持久成功回执",
        API / "routers" / "profile.py",
        "    return run_idempotent(ctx, body, 200, action)",
        '    with ctx.transaction():\n        payload = action("")\n    return ok(payload)',
        ("tests/api/test_profile_revision.py",),
    ),
    Mutation(
        "DRAFT303C 资料读取旧RR快照",
        API / "services" / "profile_service.py",
        "        select(StudentProfile)\n        .where(StudentProfile.user_id == student_id)\n        .with_for_update()",
        "        select(StudentProfile)\n        .where(StudentProfile.user_id == student_id)",
        ("tests/integration/test_profile_revision_mysql.py",),
    ),
    Mutation(
        "DRAFT303C 资料先提交后写成功回执",
        API / "services" / "profile_service.py",
        "        user.updated_at = now\n    return profile",
        "        user.updated_at = now\n    db.commit()\n    return profile",
        ("tests/api/test_profile_revision.py",),
    ),
    Mutation(
        "DRAFT303B 首次提交指针误用当前草稿",
        API / "services" / "session_service.py",
        "        first_submitted_attempt_id=next(\n            (identifier for identifier, number in submitted if number == 1), None\n        ),",
        "        first_submitted_attempt_id=active.id if active else None,",
        ("tests/api/test_first_submitted_attempt.py",),
    ),
    Mutation(
        "DRAFT303B 首次提交指针读取旧RR快照",
        API / "services" / "session_service.py",
        "    if _locked(db, session_id):\n        statement = statement.with_for_update()\n    return [(identifier, number) for identifier, number in db.execute(statement)]",
        "    if False:\n        statement = statement.with_for_update()\n    return [(identifier, number) for identifier, number in db.execute(statement)]",
        ("tests/integration/test_first_submitted_attempt_mysql.py",),
    ),
    Mutation(
        "DRAFT303B 旧轮次首次提交可再次推进复测",
        API / "services" / "review_scheduler.py",
        "    if not inserted:\n        history = db.scalar(",
        "    if False:\n        history = db.scalar(",
        ("tests/api/test_reviews.py",),
    ),
    Mutation(
        "DRAFT303B 把未知旧完成历史当作已知",
        API / "services" / "review_scheduler.py",
        '        if history.state != "completed" or history.result != values["result"]:',
        "        if False:",
        ("tests/api/test_reviews.py",),
    ),
    Mutation(
        "DRAFT303 提交忽略已确认笔迹版本",
        API / "services" / "session_service.py",
        "    if body.expected_draft_revision is not None and body.expected_draft_revision != draft.revision:",
        "    if False:",
        ("tests/api/test_submit_revision_guard.py",),
    ),
    Mutation(
        "DRAFT303 修订号接受布尔字符串与小数",
        API / "schemas.py",
        "    expected_draft_revision: int | None = Field(default=None, strict=True, ge=0)",
        "    expected_draft_revision: int | None = Field(default=None, strict=False, ge=0)",
        ("tests/api/test_submit_revision_guard.py",),
    ),
    Mutation(
        "DRAFT303 新字段破坏旧提交回执指纹",
        API / "schemas.py",
        '        if "expected_draft_revision" not in self.model_fields_set:',
        "        if False:",
        ("tests/api/test_submit_revision_guard.py",),
    ),
    Mutation(
        "DRAFT303 提交读取旧RR笔迹快照",
        API / "services" / "session_service.py",
        "        statement = statement.with_for_update().execution_options(populate_existing=True)\n    draft = db.scalar(statement)",
        "        statement = statement\n    draft = db.scalar(statement)",
        ("tests/integration/test_submit_revision_guard_mysql.py",),
    ),
    Mutation(
        "DRAFT302 副本独占题目锁重现三方死锁",
        API / "services" / "session_service.py",
        '        .where(Question.id == session.question_id, Question.status == "published")\n        .with_for_update(read=True)',
        '        .where(Question.id == session.question_id, Question.status == "published")\n        .with_for_update()',
        ("tests/integration/test_session_create_copy_review_locks_mysql.py",),
    ),
    Mutation(
        "DRAFT302 忽略离线题面期望版本",
        API / "services" / "session_service.py",
        "        and body.expected_question_version != question.version",
        "        and False",
        ("tests/api/test_session_version_guard.py",),
    ),
    Mutation(
        "DRAFT302 版本读取退回RR旧快照",
        API / "services" / "session_service.py",
        "        .where(Question.id == question_id)\n        .with_for_update(read=True)",
        "        .where(Question.id == question_id)",
        ("tests/integration/test_session_version_guard_mysql.py",),
    ),
    Mutation(
        "DRAFT302 创建响应重读不可见的新版本",
        API / "services" / "session_service.py",
        "        if created is not None and created[0] is db.get_transaction()",
        "        if False",
        ("tests/integration/test_session_version_guard_mysql.py",),
    ),
    Mutation(
        "DRAFT302 新缺省字段破坏旧回执指纹",
        API / "schemas.py",
        '        if "expected_question_version" not in self.model_fields_set:',
        "        if False:",
        ("tests/api/test_session_version_guard.py",),
    ),
    Mutation(
        "DRAFT302 期望版本宽松转换布尔与字符串",
        API / "schemas.py",
        "    expected_question_version: int | None = Field(default=None, strict=True, ge=1)",
        "    expected_question_version: int | None = Field(default=None, strict=False, ge=1)",
        ("tests/api/test_session_version_guard.py",),
    ),
    Mutation(
        "DRAFT301B 用创建号冒充提交号",
        API / "services" / "session_service.py",
        "    submission_no = submitted_count(db, session.id) + 1",
        "    submission_no = attempt.attempt_no",
        ("tests/api/test_submission_order.py",),
    ),
    Mutation(
        "DRAFT301B 复制忽略源版本",
        API / "services" / "session_service.py",
        "    if draft.revision != body.source_revision:",
        "    if False:",
        ("tests/api/test_draft_copies.py",),
    ),
    Mutation(
        "DRAFT301B 创建副本覆盖源稿",
        API / "services" / "session_service.py",
        "    new = _append_attempt(",
        "    source.answer_json = body.answer.model_dump(exclude_none=True) if body.answer else None\n    new = _append_attempt(",
        ("tests/api/test_draft_copies.py",),
    ),
    Mutation(
        "DRAFT301B 新草稿提前提交事务",
        API / "services" / "session_service.py",
        "    session.updated_at = now\n    db.flush()\n    return attempt",
        "    session.updated_at = now\n    db.commit()\n    return attempt",
        ("tests/api/test_draft_copies.py",),
    ),
    Mutation(
        "DRAFT301B 学情仍取创建序号",
        API / "services" / "progress_service.py",
        "            submission_no=attempt.submission_no,",
        "            submission_no=attempt.attempt_no,",
        ("tests/api/test_submission_statistics.py",),
    ),
    Mutation(
        "DRAFT301B 薄弱点仍取创建首稿",
        API / "services" / "task_planner.py",
        "            Attempt.submission_no == 1,",
        "            Attempt.attempt_no == 1,",
        ("tests/api/test_submission_statistics.py",),
    ),
    Mutation(
        "DRAFT301B 复测仍取创建首稿",
        API / "services" / "review_scheduler.py",
        "            if row.session_id == attempt.session_id and row.submission_no == 1",
        "            if row.session_id == attempt.session_id and row.attempt_no == 1",
        ("tests/api/test_submission_statistics.py",),
    ),
    Mutation(
        "DRAFT301B 多会话跳过复测间隔",
        API / "services" / "review_scheduler.py",
        '    if item.status != "scheduled" or item.due_at > now:',
        "    if False:",
        ("tests/api/test_submission_statistics.py",),
    ),
    Mutation(
        "DRAFT301B 复测忽略会话锁序",
        API / "services" / "review_scheduler.py",
        "            .order_by(StudySession.id)\n            .with_for_update()",
        "            .order_by(StudySession.id)",
        ("tests/integration/test_submission_statistics_mysql.py",),
    ),
    Mutation(
        "DRAFT301B 理解后关闭未提交副本",
        API / "services" / "orchestrator.py",
        "    if session_service.open_attempt(turn.tc.db, session.id) is not None:",
        "    if False:",
        ("tests/api/test_draft_copies.py",),
    ),
    Mutation(
        "DRAFT301B 旧会话读取新版题面",
        API / "routers" / "draft_copies.py",
        "            version_no=session.question_version,",
        "            version_no=question.version,",
        ("tests/api/test_draft_copies.py",),
    ),
    Mutation(
        "PHOTO301 忽略未验证的额外公式",
        API / "services" / "scan_service.py",
        "    match = candidates[0] if len(candidates) == 1 and not body.expressions else None",
        "    match = candidates[0] if len(candidates) == 1 else None",
        ("tests/api/test_scans.py",),
    ),
    Mutation(
        "PHOTO301 迟到确认覆盖首次确认",
        API / "services" / "scan_service.py",
        '            ScanRecord.payload["status"].as_string() == "needs_confirmation",',
        '            ScanRecord.payload["status"].as_string() != "failed",',
        ("tests/api/test_scans.py",),
    ),
    Mutation(
        "PHOTO301 创建扫描延长原始期限",
        API / "services" / "scan_service.py",
        "            expires_at=item.expires_at,",
        "            expires_at=ctx.now() + timedelta(days=1),",
        ("tests/api/test_scans.py",),
    ),
    Mutation(
        "PHOTO301 上传期间到期变成内部错误",
        API / "services" / "scan_service.py",
        "    except BlobNotFound:\n        raise not_found() from None\n    except (",
        "    except NotImplementedError:\n        raise not_found() from None\n    except (",
        ("tests/api/test_scans.py",),
    ),
    Mutation(
        "OPS301 MySQL读等待可被URL置零",
        API / "db.py",
        '                    "read_timeout": settings.database_read_timeout_seconds,',
        '                    "read_timeout": 0,',
        ("tests/unit/test_database_engines.py",),
    ),
    Mutation(
        "OPS301 借出连接配置失败仍复用",
        API / "db.py",
        "                _record.invalidate()",
        "                pass",
        ("tests/unit/test_database_engines.py",),
    ),
    Mutation(
        "SEC303-DISTRIBUTED 账号额度退回进程内",
        API / "services" / "http_limits.py",
        '        self.actors = RedisInviteRedeemLimiter(client, namespace=namespace + "actor:")',
        "        self.actors = InMemoryInviteRedeemLimiter()",
        (
            "tests/integration/test_http_limit_redis.py::"
            "test_authenticated_limits_shared_between_two_instances[actor]",
        ),
    ),
    Mutation(
        "SEC303-DISTRIBUTED 路由额度退回进程内",
        API / "services" / "http_limits.py",
        '        self.routes = RedisInviteRedeemLimiter(client, namespace=namespace + "route:")',
        "        self.routes = InMemoryInviteRedeemLimiter()",
        (
            "tests/integration/test_http_limit_redis.py::"
            "test_authenticated_limits_shared_between_two_instances[route]",
        ),
    ),
    Mutation(
        "SEC303 跳过peer门控",
        API / "services" / "http_limits.py",
        "        self._check(self.peers, peer, settings, now, settings.http_limit_per_peer)",
        "        return None",
        ("tests/api/test_http_limits.py",),
    ),
    Mutation(
        "SEC303 跳过认证账号门控",
        API / "services" / "http_limits.py",
        "        self._check(self.actors, actor, settings, now, settings.http_limit_per_actor)",
        "        return None",
        ("tests/api/test_http_limits.py",),
    ),
    Mutation(
        "SEC303 跳过路由模板额度",
        API / "services" / "http_limits.py",
        "        limit = settings.http_route_requests.get(key)",
        "        limit = None",
        ("tests/api/test_http_limits.py",),
    ),
    Mutation(
        "SEC303 忽略实际流式体积",
        API / "services" / "http_limits.py",
        "                if total > self.settings.http_max_body_bytes:",
        "                if False:",
        ("tests/unit/test_http_admission_asgi.py",),
    ),
    Mutation(
        "SEC303 尾帧越过body期限",
        API / "services" / "http_limits.py",
        "                if time.monotonic() >= deadline:",
        "                if False:",
        (
            "tests/unit/test_http_admission_asgi.py::test_final_body_frame_cannot_start_business_after_deadline",
        ),
    ),
    Mutation(
        "SEC303 超时不返回标准错误",
        API / "services" / "http_limits.py",
        "                except TimeoutError:",
        "                except NotImplementedError:",
        (
            "tests/unit/test_http_admission_asgi.py::test_slow_body_times_out_without_starting_business",
        ),
    ),
    Mutation(
        "SEC303 超出在途上限仍准入",
        API / "services" / "http_limits.py",
        "            admitted = self._active < self.settings.http_max_inflight",
        "            admitted = True",
        (
            "tests/unit/test_http_admission_asgi.py::test_inflight_rejection_and_slot_release_after_completion",
        ),
    ),
    Mutation(
        "SEC303 接受无界Redis客户端",
        API / "services" / "http_limits.py",
        "        if not bounded:",
        "        if False:",
        (
            "tests/unit/test_http_admission_asgi.py::test_unbounded_or_retrying_redis_clients_are_refused",
        ),
    ),
    Mutation(
        "SEC303 本机入口信任伪造代理头",
        REPO_ROOT / "tools" / "run_dev_api.py",
        "proxy_headers=False",
        "proxy_headers=True",
        ("tests/api/test_http_limits.py",),
    ),
    Mutation(
        "SEC303 依赖失败静默放行",
        API / "services" / "http_limits.py",
        "        except Exception:\n            raise denied(settings) from None",
        "        except Exception:\n            return None",
        ("tests/api/test_http_limits.py",),
    ),
    Mutation(
        "SUBJECT302 整数参数可用小数",
        GATEWAY / "visual_templates.py",
        "            if spec.integer:",
        "            if False:",
        ("tests/gateway/test_subject_visual_templates.py",),
    ),
    Mutation(
        "SUBJECT302 参数范围可绕过",
        GATEWAY / "visual_templates.py",
        "            if not spec.min <= value <= spec.max:",
        "            if False:",
        ("tests/gateway/test_subject_visual_templates.py",),
    ),
    Mutation(
        "SUBJECT302 可夹带动态标签",
        GATEWAY / "visual_templates.py",
        "        unknown = set(params) - known",
        "        unknown = set()",
        ("tests/gateway/test_subject_visual_templates.py",),
    ),
    Mutation(
        "CONFIG-PRIVACY 数据库密码进入repr",
        API / "settings.py",
        'database_url: str = Field(default="sqlite:///var/tutor_dev.sqlite3", repr=False)',
        'database_url: str = Field(default="sqlite:///var/tutor_dev.sqlite3", repr=True)',
        ("tests/unit/test_settings_privacy.py",),
    ),
    Mutation(
        "CONFIG-PRIVACY 密钥进入repr",
        API / "settings.py",
        "pseudonym_secret: str | None = Field(default=None, repr=False)",
        "pseudonym_secret: str | None = Field(default=None, repr=True)",
        ("tests/unit/test_settings_privacy.py",),
    ),
    Mutation(
        "CONFIG-PRIVACY 校验错误回显原输入",
        API / "settings.py",
        "hide_input_in_errors=True",
        "hide_input_in_errors=False",
        ("tests/unit/test_settings_privacy.py",),
    ),
    Mutation(
        "COST301A0 网关绕过原子准入拒绝",
        GATEWAY / "gateway.py",
        "                if not admitted:",
        "                if False:",
        ("tests/gateway/test_budget_admission.py",),
    ),
    Mutation(
        "COST301A0 内存平台额度不生效",
        GATEWAY / "budget.py",
        "                or self._requests.get(platform, 0) >= platform_limit",
        "                or False",
        ("tests/unit/test_budget_admission_store.py",),
    ),
    Mutation(
        "COST301A0 数据库额度不生效",
        API / "gateway_io.py",
        "                if row.request_count >= limit:",
        "                if False:",
        ("tests/integration/test_mysql_budget_admission.py",),
    ),
    Mutation(
        "COST301A0 显式预算存储静默回退",
        GATEWAY / "gateway.py",
        "budget_store=budget_store if budget_store is not None else InMemoryBudgetStore(),",
        "budget_store=budget_store or InMemoryBudgetStore(),",
        (
            "tests/gateway/test_budget_admission.py::test_explicit_falsey_budget_store_is_not_replaced_by_in_memory_default",
        ),
    ),
    Mutation(
        "PROD302A 会话事务锁丢失",
        API / "services" / "session_service.py",
        "    session = db.scalar(statement.with_for_update().execution_options(populate_existing=True))",
        "    session = db.scalar(statement.execution_options(populate_existing=True))",
        (
            "tests/integration/test_managed_tutor_transactions.py::test_rr_old_snapshot_waits_then_uses_current_session_and_tail",
        ),
    ),
    Mutation(
        "PROD302A 会话锁后未刷新身份映射",
        API / "services" / "session_service.py",
        "    session = db.scalar(statement.with_for_update().execution_options(populate_existing=True))",
        "    session = db.scalar(statement.with_for_update())",
        (
            "tests/integration/test_managed_tutor_transactions.py::test_rr_old_snapshot_waits_then_uses_current_session_and_tail",
        ),
    ),
    Mutation(
        "PROD302A 事件序号读取旧快照",
        API / "services" / "events.py",
        '"seq_no": last_seq(db, session.id, current_read=True) + 1,',
        '"seq_no": last_seq(db, session.id, current_read=False) + 1,',
        (
            "tests/integration/test_managed_tutor_transactions.py::test_rr_old_snapshot_waits_then_uses_current_session_and_tail",
        ),
    ),
    Mutation(
        "PROD302A 提交计数读取旧快照",
        API / "services" / "session_service.py",
        "        statement = statement.with_for_update()\n",
        "        pass\n",
        (
            "tests/integration/test_managed_tutor_transactions.py::test_rr_old_snapshot_waits_then_uses_current_session_and_tail[submit]",
        ),
    ),
    Mutation(
        "PROD302A 受控辅导越过模型事务限制",
        API / "services" / "orchestrator.py",
        "    if not tc.allow_gateway:",
        "    if False:",
        (
            "tests/integration/test_managed_tutor_transactions.py::test_managed_reviewed_rephrase_and_unavailable_model_are_honest",
        ),
    ),
    Mutation(
        "SEC304 独立作答提前下发答案图解",
        API / "services" / "orchestrator.py",
        "    if turn.submitted == 0 and not turn.session.used_solution:",
        "    if False:",
        ("tests/api/test_visual_security.py",),
    ),
    Mutation(
        "SUBJECT301 允许动画或多帧图片",
        API / "services" / "media_service.py",
        '        if getattr(image, "is_animated", False) or getattr(image, "n_frames", 1) != 1:',
        "        if False:",
        ("tests/api/test_subject_media.py",),
    ),
    Mutation(
        "SUBJECT301 未发布图片也向学生开放",
        API / "services" / "media_service.py",
        '    if question is None or (published and question.status != "published"):',
        "    if question is None:",
        ("tests/api/test_subject_media.py",),
    ),
    Mutation(
        "SUBJECT301 旧版本审校声明继续有效",
        API / "services" / "media_service.py",
        '            AuditLog.detail_json["version"].as_integer() == question.version,',
        "",
        ("tests/api/test_subject_media.py",),
    ),
    Mutation(
        "SUBJECT301 摘要变化不失效审校声明",
        API / "services" / "media_service.py",
        '            AuditLog.detail_json["sha256"].as_string() == asset.sha256,',
        "",
        ("tests/api/test_subject_media.py",),
    ),
    Mutation(
        "SUBJECT301 发布者声明取代实际二审者记录",
        API / "services" / "media_service.py",
        "            AuditLog.actor_id == actor_id,",
        "            AuditLog.actor_id != question.created_by,",
        ("tests/api/test_subject_media.py",),
    ),
    Mutation(
        "MEDIA301 跨owner直接读取媒体",
        API / "services" / "media_service.py",
        "    if asset is None or asset.owner_id != ctx.actor_id or asset.deleted_at is not None:",
        "    if asset is None or asset.deleted_at is not None:",
        ("tests/api/test_media.py",),
    ),
    Mutation(
        "MEDIA301 伪造别人UUID解锁附件引用",
        API / "services" / "media_service.py",
        "            or (asset.owner_id != actor_id and id not in allowed)",
        "            or False",
        ("tests/api/test_media.py",),
    ),
    Mutation(
        "MEDIA301 未引用题目也能读取媒体",
        API / "services" / "media_service.py",
        "    if version is None or id not in {",
        "    if version is None or False and id not in {",
        ("tests/api/test_media.py",),
    ),
    Mutation(
        "MEDIA301 数据库提交前就删除媒体字节",
        API / "services" / "media_service.py",
        "        asset.deleted_at = ctx.now()",
        "        asset.deleted_at = ctx.now()\n        value.delete(asset.object_key, owner=asset.owner_id, now=ctx.now())",
        ("tests/api/test_media.py",),
    ),
    Mutation(
        "ADMIN301 批次业务提前提交脱离幂等回执",
        API / "services" / "review_service.py",
        '    return {"items": results}',
        '    ctx.db.commit()\n    return {"items": results}',
        ("tests/api/test_admin_review_batch.py",),
    ),
    Mutation(
        "ADMIN301 未明确布尔确认也可审核",
        API / "schemas.py",
        "        if value is not True:",
        "        if False:",
        ("tests/api/test_admin_review_batch.py",),
    ),
    Mutation(
        "ADMIN301 不再检查重复题目ID",
        API / "schemas.py",
        "        if len({item.question_id.lower() for item in items}) != len(items):",
        "        if False:",
        ("tests/api/test_admin_review_batch.py",),
    ),
    Mutation(
        "会话不再校验归属",
        API / "services" / "session_service.py",
        "    if session is None or session.student_id != student_id:\n        raise not_found()\n    return session",
        "    if session is None:\n        raise not_found()\n    return session",
        ("tests/api/test_security.py",),
    ),
    Mutation(
        "作答不再校验归属",
        API / "services" / "session_service.py",
        "    if attempt is None or session is None or session.student_id != student_id:\n        raise not_found()\n    return attempt, session",
        "    if attempt is None or session is None:\n        raise not_found()\n    return attempt, session",
        ("tests/api/test_security.py",),
    ),
    Mutation(
        "复测项不再校验归属",
        API / "services" / "review_scheduler.py",
        "    if item is None or item.student_id != student_id:",
        "    if item is None:",
        ("tests/api/test_security.py", "tests/api/test_reviews.py"),
    ),
    Mutation(
        "未发布的题也能取到",
        API / "services" / "question_service.py",
        '    if question is None or question.status != "published":',
        "    if question is None:",
        ("tests/api/test_questions.py", "tests/api/test_attempt_flow.py"),
    ),
    Mutation(
        "地区标签不再检查考试年份",
        API / "services" / "question_service.py",
        "    return lower_ok and upper_ok",
        "    return True",
        ("tests/api/test_questions.py",),
    ),
    Mutation(
        "未审核的地区标签也参与推荐",
        API / "services" / "question_service.py",
        '            QuestionRegionApplicability.review_status == "approved",',
        "",
        ("tests/api/test_questions.py",),
    ),
    Mutation(
        "提交前看解析不再需要确认",
        API / "services" / "orchestrator.py",
        "    if not turn.body.confirm_end_independent:",
        "    if False:",
        ("tests/api/test_tutor_flow.py",),
    ),
    Mutation(
        "复测会话提交前也给辅助",
        API / "services" / "orchestrator.py",
        '    if turn.session.origin == "review" and turn.submitted == 0:',
        "    if False:",
        ("tests/api/test_tutor_flow.py",),
    ),
    Mutation(
        "没懂之后无限重复生成",
        API / "services" / "orchestrator.py",
        "    if session.needs_human_help:\n        return []",
        "    if False:\n        return []",
        ("tests/api/test_tutor_flow.py",),
    ),
    Mutation(
        "看过提示仍算独立作答",
        API / "services" / "session_service.py",
        "        submission_no == 1\n        and not session.assisted",
        "        submission_no == 1\n        and True",
        ("tests/api/test_tutor_flow.py",),
    ),
    Mutation(
        "同一会话的重试也算独立作答",
        API / "services" / "session_service.py",
        "        submission_no == 1\n        and not session.assisted",
        "        True\n        and not session.assisted",
        ("tests/api/test_attempt_flow.py",),
    ),
    Mutation(
        "认不出的单位直接按数值判对错",
        API / "services" / "grading.py",
        '    if unit_status == "unknown":',
        "    if False:",
        ("tests/unit/test_grading.py", "tests/api/test_attempt_flow.py"),
    ),
    Mutation(
        "判不出来的作答也安排复测",
        API / "services" / "session_service.py",
        '    needs_review = result.state == "verified" and (not result.is_correct or not independent)',
        "    needs_review = not result.is_correct or not independent",
        ("tests/api/test_attempt_flow.py",),
    ),
    Mutation(
        "判不出来的作答进了正确率分母",
        API / "services" / "progress_service.py",
        '        if attempt.evaluation_state == "verified"\n    ]',
        "        if True\n    ]",
        ("tests/api/test_progress.py",),
    ),
    Mutation(
        "幂等键不再去重",
        API / "idempotency.py",
        "    return _store(ctx).lookup(ctx, key, key_digest(ctx.actor_id, key))",
        "    return None",
        ("tests/api/test_idempotency.py", "tests/api/test_attempt_flow.py"),
    ),
    Mutation(
        "草稿版本冲突时静默覆盖",
        API / "services" / "session_service.py",
        "    if body.base_revision != draft.revision:",
        "    if False:",
        ("tests/api/test_attempt_flow.py",),
    ),
    Mutation(
        "复测结果不看是否独立",
        API / "services" / "review_scheduler.py",
        "    passed = bool(first.is_correct) and bool(first.independent)",
        "    passed = True",
        ("tests/api/test_reviews.py",),
    ),
    Mutation(
        "回环限制失效",
        API / "middleware.py",
        '        if self.loopback_only and not is_loopback(scope.get("client")):',
        "        if False:",
        ("tests/api/test_foundation.py",),
    ),
    Mutation(
        "网关不再校验模型输出的结构",
        GATEWAY / "validation.py",
        "        if error is not None:\n            location",
        "        if False:\n            location",
        ("tests/gateway/test_validation.py",),
    ),
    Mutation(
        "网关不再拦截泄题输出",
        GATEWAY / "validation.py",
        "            if any(item in folded for item in forbidden):",
        "            if False:",
        ("tests/gateway/test_validation.py", "tests/api/test_tutor_flow.py"),
    ),
    Mutation(
        "未过合规核验的外部供应商也可用",
        GATEWAY / "gateway.py",
        '            if not provider.compliance_approved:\n                return None, "not_compliance_approved"',
        '            if False:\n                return None, "not_compliance_approved"',
        ("tests/gateway/test_routing.py",),
    ),
    # ---- 内容审核（P0 第 9 条）
    Mutation(
        "学生也能调用审核接口",
        API / "deps.py",
        "    if principal.role not in REVIEW_ROLES:\n        raise ApiError(403",
        "    if False:\n        raise ApiError(403",
        (
            "tests/api/test_admin_review.py",
            "tests/api/test_security.py",
            "tests/api/test_admin_imports.py",
        ),
    ),
    Mutation(
        "提交者可以审核自己的题",
        API / "services" / "review_service.py",
        "    if question.created_by is not None and question.created_by == actor_id:",
        "    if question.created_by is not None and False:",
        ("tests/api/test_admin_review.py",),
    ),
    Mutation(
        "草稿不经二审也能直接上线",
        API / "services" / "review_service.py",
        '    "publish": (frozenset({"reviewed"}), "published"),',
        '    "publish": (frozenset({"draft", "reviewed"}), "published"),',
        ("tests/api/test_admin_review.py",),
    ),
    Mutation(
        "程序校验有问题也能通过审核",
        API / "services" / "review_service.py",
        "        problems = check_problems(db, question)\n        if problems:\n",
        "        problems = check_problems(db, question)\n        if False:\n",
        ("tests/api/test_admin_review.py",),
    ),
    Mutation(
        "标准解法没审核也能上线",
        API / "services" / "review_service.py",
        "        if standard is None or not standard.reviewed:\n",
        "        if standard is None:\n",
        ("tests/api/test_admin_review.py",),
    ),
    # ---- 修改题目、产生新版本
    Mutation(
        "导入时自编题也可冒充授权真题",
        API / "services" / "review_service.py",
        '    if source.source_category == "gaokao_real" and source.source_type != "gaokao_licensed":',
        "    if False:",
        ("tests/api/test_admin_imports.py",),
    ),
    Mutation(
        "已上线的题也能直接修改",
        API / "services" / "review_service.py",
        'EDITABLE_FROM = frozenset({"draft", "reviewed", "withdrawn"})',
        'EDITABLE_FROM = frozenset({"draft", "reviewed", "withdrawn", "published"})',
        ("tests/api/test_admin_versions.py",),
    ),
    Mutation(
        "修改之后解法的审核标记还留着",
        API / "services" / "review_service.py",
        "                reviewed=False,  # 新版本的解法一律重新审核\n",
        "                reviewed=True,\n",
        ("tests/api/test_admin_versions.py",),
    ),
    Mutation(
        "改的人可以自己二审自己的修改",
        API / "services" / "review_service.py",
        "    question.created_by = actor_id  # 改的人成为新版本的提交者，不能自己二审\n",
        "    pass\n",
        ("tests/api/test_admin_versions.py",),
    ),
    Mutation(
        "没有任何改动也产生新版本",
        API / "services" / "review_service.py",
        "    if not changes:\n",
        "    if False:\n",
        ("tests/api/test_admin_versions.py",),
    ),
    Mutation(
        "复测列表里还列着已下线的题",
        API / "services" / "review_scheduler.py",
        '            Question.status == "published",\n',
        "",
        ("tests/api/test_admin_versions.py",),
    ),
    # ---- 回看与对比旧版本
    Mutation(
        "修改时没有把旧版本的难度、年级、知识点记下来",
        API / "services" / "review_service.py",
        "    previous.content_json = {**snapshot_keys, **previous.content_json}\n",
        "    pass\n",
        ("tests/api/test_admin_version_snapshots.py",),
    ),
    Mutation(
        "取某一版时总是返回当前版本",
        API / "services" / "review_service.py",
        "            QuestionVersion.question_id == question.id, QuestionVersion.version == version_no\n",
        "            QuestionVersion.question_id == question.id, QuestionVersion.version == question.version\n",
        ("tests/api/test_admin_version_snapshots.py",),
    ),
    # ---- 解答题（主观题）：不自动评分、提交后对照要点自查
    Mutation(
        "解答题被系统判成了正确",
        API / "services" / "grading.py",
        '    return GradeResult(\n        "pending",\n        "undetermined",\n        None,\n        (),\n        "解答题不自动评分，作答已保存。',
        '    return GradeResult(\n        "verified",\n        "correct",\n        True,\n        (),\n        "解答题不自动评分，作答已保存。',
        ("tests/unit/test_grading.py", "tests/api/test_subjective.py"),
    ),
    Mutation(
        "解答题什么都没写也能提交",
        API / "services" / "grading.py",
        '    if not any(part["text"].strip() for part in submitted) and not has_ink:',
        "    if False:",
        ("tests/unit/test_grading.py", "tests/api/test_subjective.py"),
    ),
    Mutation(
        "解答题提交时不看草稿里的笔迹",
        API / "services" / "session_service.py",
        "            has_ink=_has_ink(draft),",
        "            has_ink=False,",
        ("tests/api/test_subjective.py", "tests/api/test_experiment.py", "tests/api/test_proof.py"),
    ),
    Mutation(
        "只有空白页也算写过笔迹",
        API / "services" / "session_service.py",
        '    return any(page.get("strokes") for page in pages)',
        "    return bool(pages)",
        ("tests/api/test_subjective.py",),
    ),
    Mutation(
        "选择题接受解答题的分小问作答",
        API / "services" / "grading.py",
        '        or answer.get("text") is not None\n        or answer.get("parts") is not None\n        or answer.get("cells") is not None\n        or answer.get("steps") is not None\n    ):\n        raise AnswerShapeError("answer", "选择题只需要提交 selected_options")',
        '        or answer.get("text") is not None\n        or answer.get("cells") is not None\n        or answer.get("steps") is not None\n    ):\n        raise AnswerShapeError("answer", "选择题只需要提交 selected_options")',
        ("tests/unit/test_grading.py", "tests/api/test_subjective.py"),
    ),
    Mutation(
        "提交之前就能拿到自查要点",
        API / "services" / "self_check_service.py",
        '    if attempt.status != "submitted":\n        raise conflict("attempt_not_submitted", "提交之后才能对照要点自查")',
        '    if False:\n        raise conflict("attempt_not_submitted", "提交之后才能对照要点自查")',
        ("tests/api/test_subjective.py", "tests/api/test_proof.py"),
    ),
    Mutation(
        "自查要点取的是题目当前版本而不是学生做题时的版本",
        API / "services" / "self_check_service.py",
        "    rubric = question_service.get_rubric(db, question.id, session.question_version)",
        "    rubric = question_service.get_rubric(db, question.id, question.version)",
        ("tests/api/test_subjective.py",),
    ),
    Mutation(
        "自查接口不再校验作答归属",
        API / "services" / "session_service.py",
        "    if attempt is None or session is None or session.student_id != student_id:\n        raise not_found()\n    return attempt, session",
        "    if attempt is None or session is None:\n        raise not_found()\n    return attempt, session",
        ("tests/api/test_subjective.py",),
    ),
    Mutation(
        "自查可以漏评要点",
        API / "services" / "self_check_service.py",
        '    if set(keys) - set(given):\n        raise unprocessable("marks", "每个要点都要评一次，还有要点没有评")',
        '    if False:\n        raise unprocessable("marks", "每个要点都要评一次，还有要点没有评")',
        ("tests/api/test_subjective.py",),
    ),
    Mutation(
        "自查可以把同一个要点评两次",
        API / "services" / "self_check_service.py",
        '    if len(set(given)) != len(given):\n        raise unprocessable("marks", "同一个要点只能评一次")',
        '    if False:\n        raise unprocessable("marks", "同一个要点只能评一次")',
        ("tests/api/test_subjective.py",),
    ),
    Mutation(
        "自查可以评不存在的要点",
        API / "services" / "self_check_service.py",
        '    if not set(given) <= set(keys):\n        raise unprocessable("marks", "包含不存在的要点")',
        '    if False:\n        raise unprocessable("marks", "包含不存在的要点")',
        ("tests/api/test_subjective.py",),
    ),
    Mutation(
        "解答题和实验题被算进了没能判定的次数",
        API / "services" / "progress_service.py",
        '        if mode not in grading.SUBJECTIVE_MODES and attempt.evaluation_state != "verified"',
        '        if attempt.evaluation_state != "verified"',
        ("tests/api/test_subjective.py", "tests/api/test_experiment.py", "tests/api/test_proof.py"),
    ),
    Mutation(
        "第一道新题可能就是解答题或实验题",
        API / "services" / "task_planner.py",
        "    return [q for q in questions if q.answer_mode not in grading.SUBJECTIVE_MODES] + [\n        q for q in questions if q.answer_mode in grading.SUBJECTIVE_MODES\n    ]",
        "    return questions",
        (
            "tests/api/test_subjective.py",
            "tests/api/test_experiment.py",
            "tests/api/test_proof.py",
            "tests/api/test_tasks.py",
        ),
    ),
    Mutation(
        "自查要点带分值也能通过校验",
        API / "services" / "content_seed.py",
        "        if not isinstance(point, dict) or set(point) != _POINT_FIELDS:",
        "        if not isinstance(point, dict):",
        ("tests/content/test_seed_content.py", "tests/api/test_admin_written.py"),
    ),
    Mutation(
        "解答题有小问没有自查要点也能通过校验",
        API / "services" / "content_seed.py",
        '    problems += [\n        f"{key}: rubric.points 没有覆盖{where_name} {part}"\n        for part in required_parts\n        if part not in covered\n    ]',
        "    problems += []",
        (
            "tests/content/test_seed_content.py",
            "tests/api/test_admin_written.py",
            "tests/content/test_experiment_content.py",
            "tests/content/test_proof_content.py",
            "tests/api/test_admin_proof.py",
        ),
    ),
    Mutation(
        "解答题可以没有泄题标记",
        API / "services" / "content_seed.py",
        '        or not markers\n        or not all(_nonempty_text(marker, _MAX_SHORT) for marker in markers)\n    ):\n        problems.append(\n            f"{key}: teaching.leak_markers 不能为空（解答题',
        '        or not all(_nonempty_text(marker, _MAX_SHORT) for marker in markers)\n    ):\n        problems.append(\n            f"{key}: teaching.leak_markers 不能为空（解答题',
        ("tests/content/test_seed_content.py",),
    ),
    # ---- 实验题：数据表 + 安全提示；不自动评分，提交后对照参考数据和要点自查
    Mutation(
        "实验题被系统判成了正确",
        API / "services" / "grading.py",
        '    return GradeResult(\n        "pending",\n        "undetermined",\n        None,\n        (),\n        "实验题不自动评分，作答已保存。',
        '    return GradeResult(\n        "verified",\n        "correct",\n        True,\n        (),\n        "实验题不自动评分，作答已保存。',
        ("tests/unit/test_grading.py", "tests/api/test_experiment.py"),
    ),
    Mutation(
        "实验题什么都没填也能提交",
        API / "services" / "grading.py",
        "    if not filled and not written and not has_ink:",
        "    if False:",
        ("tests/unit/test_grading.py", "tests/api/test_experiment.py"),
    ),
    Mutation(
        "实验题可以填题目已经给定的格子",
        API / "services" / "grading.py",
        "    if not set(seen) <= set(blank_cell_keys(content)):",
        "    if False:",
        ("tests/unit/test_grading.py", "tests/api/test_experiment.py"),
    ),
    Mutation(
        "实验题同一个格子可以填两次",
        API / "services" / "grading.py",
        '    if len(set(seen)) != len(seen):\n        raise AnswerShapeError("answer.cells", "同一个格子只能填一次")',
        '    if False:\n        raise AnswerShapeError("answer.cells", "同一个格子只能填一次")',
        ("tests/unit/test_grading.py", "tests/api/test_experiment.py"),
    ),
    Mutation(
        "实验题把题目没有留空的格子也当成要学生填的",
        API / "services" / "grading.py",
        '        for cell in row["cells"]\n        if cell["text"] is None\n    ]',
        '        for cell in row["cells"]\n    ]',
        ("tests/unit/test_grading.py", "tests/api/test_experiment.py"),
    ),
    Mutation(
        "实验题接受填空题的作答形状",
        API / "services" / "grading.py",
        '        or answer.get("blanks") is not None\n        or answer.get("text") is not None\n        or answer.get("steps") is not None\n    ):\n        raise AnswerShapeError("answer", "实验题只需要提交 cells',
        '        or answer.get("text") is not None\n        or answer.get("steps") is not None\n    ):\n        raise AnswerShapeError("answer", "实验题只需要提交 cells',
        ("tests/unit/test_grading.py", "tests/api/test_experiment.py"),
    ),
    Mutation(
        "选择题接受实验题的格子作答",
        API / "services" / "grading.py",
        '        or answer.get("parts") is not None\n        or answer.get("cells") is not None\n        or answer.get("steps") is not None\n    ):\n        raise AnswerShapeError("answer", "选择题只需要提交 selected_options")',
        '        or answer.get("parts") is not None\n        or answer.get("steps") is not None\n    ):\n        raise AnswerShapeError("answer", "选择题只需要提交 selected_options")',
        ("tests/unit/test_grading.py", "tests/api/test_experiment.py"),
    ),
    Mutation(
        "解答题接受实验题的格子作答",
        API / "services" / "grading.py",
        '        or answer.get("text") is not None\n        or answer.get("cells") is not None\n        or answer.get("steps") is not None\n    ):\n        raise AnswerShapeError("answer", "解答题只需要按小问提交 parts")',
        '        or answer.get("text") is not None\n        or answer.get("steps") is not None\n    ):\n        raise AnswerShapeError("answer", "解答题只需要按小问提交 parts")',
        ("tests/unit/test_grading.py", "tests/api/test_experiment.py"),
    ),
    Mutation(
        "客观题也能对照要点自查",
        API / "services" / "self_check_service.py",
        '    if question.answer_mode not in grading.SUBJECTIVE_MODES:\n        raise conflict("self_check_not_applicable", "这道题不需要对照要点自查")',
        '    if False:\n        raise conflict("self_check_not_applicable", "这道题不需要对照要点自查")',
        ("tests/api/test_subjective.py", "tests/api/test_experiment.py", "tests/api/test_proof.py"),
    ),
    Mutation(
        "参考数据取的是题目当前版本而不是学生做题时的版本",
        API / "services" / "self_check_service.py",
        '    if question.answer_mode != "experiment":\n        return []\n    version = question_service.get_version(db, question.id, session.question_version)',
        '    if question.answer_mode != "experiment":\n        return []\n    version = question_service.get_version(db, question.id, question.version)',
        ("tests/api/test_admin_experiment.py", "tests/api/test_experiment.py"),
    ),
    Mutation(
        "数值型的参考数据没有自动加进泄题标记",
        API / "services" / "content_seed.py",
        '            if cell_key.count(".") == 2 and len(text) >= 3 and _NUMBER_LIKE.match(text):\n                markers.append(text)',
        "            if False:\n                markers.append(text)",
        ("tests/content/test_experiment_content.py", "tests/api/test_experiment.py"),
    ),
    Mutation(
        "高风险实验也能通过校验",
        API / "services" / "content_seed.py",
        '    if level == "high":\n        problems.append(\n            f"{key}: content.safety.level 是 high：高风险实验现在不收录，还没有专项审核流程"\n        )\n    elif level not in _SAFETY_LEVELS:\n',
        '    if level not in (*_SAFETY_LEVELS, "high"):\n',
        (
            "tests/content/test_experiment_content.py",
            "tests/api/test_admin_experiment.py",
        ),
    ),
    Mutation(
        "实验题可以没有安全提示",
        API / "services" / "content_seed.py",
        '    if not isinstance(safety, dict) or set(safety) != {"level", "notes"}:\n        return [\n',
        '    if not isinstance(safety, dict):\n        return []\n    if set(safety) != {"level", "notes"}:\n        return [\n',
        (
            "tests/content/test_experiment_content.py",
            "tests/api/test_admin_experiment.py",
        ),
    ),
    Mutation(
        "实验题有留空格子的数据表没有自查要点也能通过校验",
        API / "services" / "content_seed.py",
        '        key, question, [*part_keys, *table_keys], [*part_keys, *tables_with_blanks], "小问或数据表"',
        '        key, question, [*part_keys, *table_keys], part_keys, "小问或数据表"',
        (
            "tests/content/test_experiment_content.py",
            "tests/api/test_admin_experiment.py",
        ),
    ),
    Mutation(
        "实验题的留空格子没有参考值也能通过校验",
        API / "services" / "content_seed.py",
        "        or set(values) != set(expected)\n",
        "",
        (
            "tests/content/test_experiment_content.py",
            "tests/api/test_admin_experiment.py",
        ),
    ),
    Mutation(
        "选择题、填空题、解答题也能带数据表和安全提示",
        API / "services" / "content_seed.py",
        '    if content.get("data_tables") or content.get("safety"):\n        return [f"{key}: 只有实验题才能有 content.data_tables 和 content.safety"]',
        '    if False:\n        return [f"{key}: 只有实验题才能有 content.data_tables 和 content.safety"]',
        ("tests/content/test_experiment_content.py",),
    ),
    Mutation(
        "修改实验题之后新版本丢了数据表",
        API / "services" / "review_service.py",
        '                "data_tables": [item.model_dump() for item in content.data_tables],',
        '                "data_tables": [],',
        ("tests/api/test_admin_experiment.py",),
    ),
    Mutation(
        "修改实验题之后新版本丢了安全提示",
        API / "services" / "review_service.py",
        '                "safety": content.safety.model_dump() if content.safety else None,',
        '                "safety": None,',
        ("tests/api/test_admin_experiment.py",),
    ),
    Mutation(
        "审核后台看到的当前版本没有数据表",
        API / "services" / "review_service.py",
        '            "data_tables": content.get("data_tables") or [],\n            "safety": content.get("safety"),\n            "proof": content.get("proof"),\n        },\n        "answer": {',
        '            "data_tables": [],\n            "safety": content.get("safety"),\n            "proof": content.get("proof"),\n        },\n        "answer": {',
        ("tests/api/test_admin_experiment.py",),
    ),
    Mutation(
        "题面里没有安全提示",
        API / "services" / "question_service.py",
        '        safety=content.get("safety"),',
        "        safety=None,",
        ("tests/api/test_experiment.py",),
    ),
    Mutation(
        "题面里没有数据表",
        API / "services" / "question_service.py",
        '        data_tables=content.get("data_tables") or [],',
        "        data_tables=[],",
        ("tests/api/test_experiment.py",),
    ),
    Mutation(
        "实验题的预计用时和解答题一样",
        API / "services" / "task_planner.py",
        "        return 10 + 2 * question.difficulty",
        "        return 8 + 2 * question.difficulty",
        ("tests/api/test_experiment.py",),
    ),
    Mutation(
        "学情页不统计实验题的提交",
        API / "services" / "progress_service.py",
        "    written = [attempt for attempt, _, _, mode, _ in records if mode in grading.SUBJECTIVE_MODES]",
        '    written = [attempt for attempt, _, _, mode, _ in records if mode == "written"]',
        ("tests/api/test_experiment.py",),
    ),
    Mutation(
        "家长周报不统计实验题的提交",
        API / "services" / "weekly_service.py",
        "        written_attempts=sum(1 for _, _, _, mode, _ in records if mode in grading.SUBJECTIVE_MODES),",
        '        written_attempts=sum(1 for _, _, _, mode, _ in records if mode == "written"),',
        ("tests/api/test_experiment.py",),
    ),
    # ---- 证明题：已知与求证 + 一步一步的证明；不自动评分，提交后对照参考证明和要点自查
    Mutation(
        "证明题被系统判成了正确",
        API / "services" / "grading.py",
        '    return GradeResult(\n        "pending",\n        "undetermined",\n        None,\n        (),\n        "证明题不自动评分，作答已保存。',
        '    return GradeResult(\n        "verified",\n        "correct",\n        True,\n        (),\n        "证明题不自动评分，作答已保存。',
        ("tests/unit/test_grading.py", "tests/api/test_proof.py"),
    ),
    Mutation(
        "证明题什么都没写也能提交",
        API / "services" / "grading.py",
        '    if not any(step["text"].strip() for step in submitted) and not has_ink:',
        "    if False:",
        ("tests/unit/test_grading.py", "tests/api/test_proof.py"),
    ),
    Mutation(
        "证明题只写了依据、没写这一步的内容也算有内容",
        API / "services" / "grading.py",
        '    if not any(step["text"].strip() for step in submitted) and not has_ink:',
        '    if not any(step["text"].strip() or step["reason"].strip() for step in submitted) and not has_ink:',
        ("tests/unit/test_grading.py", "tests/api/test_proof.py"),
    ),
    Mutation(
        "证明题接受解答题的分小问作答",
        API / "services" / "grading.py",
        '        or answer.get("text") is not None\n        or answer.get("parts") is not None\n        or answer.get("cells") is not None\n    ):\n        raise AnswerShapeError("answer", "证明题只需要提交 steps',
        '        or answer.get("text") is not None\n        or answer.get("cells") is not None\n    ):\n        raise AnswerShapeError("answer", "证明题只需要提交 steps',
        ("tests/unit/test_grading.py", "tests/api/test_proof.py"),
    ),
    Mutation(
        "证明题接受实验题的格子作答",
        API / "services" / "grading.py",
        '        or answer.get("parts") is not None\n        or answer.get("cells") is not None\n    ):\n        raise AnswerShapeError("answer", "证明题只需要提交 steps',
        '        or answer.get("parts") is not None\n    ):\n        raise AnswerShapeError("answer", "证明题只需要提交 steps',
        ("tests/unit/test_grading.py", "tests/api/test_proof.py"),
    ),
    Mutation(
        "选择题接受证明题的步骤作答",
        API / "services" / "grading.py",
        '        or answer.get("cells") is not None\n        or answer.get("steps") is not None\n    ):\n        raise AnswerShapeError("answer", "选择题只需要提交 selected_options")',
        '        or answer.get("cells") is not None\n    ):\n        raise AnswerShapeError("answer", "选择题只需要提交 selected_options")',
        ("tests/unit/test_grading.py", "tests/api/test_proof.py"),
    ),
    Mutation(
        "填空题接受证明题的步骤作答",
        API / "services" / "grading.py",
        '        or answer.get("cells") is not None\n        or answer.get("steps") is not None\n    ):\n        raise AnswerShapeError("answer", "填空题只需要提交 blanks")',
        '        or answer.get("cells") is not None\n    ):\n        raise AnswerShapeError("answer", "填空题只需要提交 blanks")',
        ("tests/unit/test_grading.py", "tests/api/test_proof.py"),
    ),
    Mutation(
        "解答题接受证明题的步骤作答",
        API / "services" / "grading.py",
        '        or answer.get("cells") is not None\n        or answer.get("steps") is not None\n    ):\n        raise AnswerShapeError("answer", "解答题只需要按小问提交 parts")',
        '        or answer.get("cells") is not None\n    ):\n        raise AnswerShapeError("answer", "解答题只需要按小问提交 parts")',
        ("tests/unit/test_grading.py", "tests/api/test_proof.py"),
    ),
    Mutation(
        "实验题接受证明题的步骤作答",
        API / "services" / "grading.py",
        '        or answer.get("text") is not None\n        or answer.get("steps") is not None\n    ):\n        raise AnswerShapeError("answer", "实验题只需要提交 cells',
        '        or answer.get("text") is not None\n    ):\n        raise AnswerShapeError("answer", "实验题只需要提交 cells',
        ("tests/unit/test_grading.py", "tests/api/test_proof.py"),
    ),
    Mutation(
        "证明题不在不自动评分的作答方式里",
        API / "services" / "grading.py",
        'SUBJECTIVE_MODES = ("written", "experiment", "proof")',
        'SUBJECTIVE_MODES = ("written", "experiment")',
        ("tests/unit/test_grading.py", "tests/api/test_proof.py"),
    ),
    Mutation(
        "证明的步骤数量没有上限",
        API / "schemas.py",
        "    steps: list[AnswerStep] | None = Field(default=None, max_length=30)",
        "    steps: list[AnswerStep] | None = Field(default=None, max_length=3000)",
        ("tests/api/test_proof.py",),
    ),
    Mutation(
        "证明的一步没有字数上限",
        API / "schemas.py",
        "    text: str = Field(max_length=1000)\n    reason: str = Field(max_length=400)",
        "    text: str = Field(max_length=100000)\n    reason: str = Field(max_length=100000)",
        ("tests/api/test_proof.py",),
    ),
    Mutation(
        "证明的一步里多出字段也不拒绝",
        API / "schemas.py",
        'class AnswerStep(_In):\n    """证明题作答里的一步。',
        'class AnswerStep(BaseModel):\n    """证明题作答里的一步。',
        ("tests/api/test_proof.py",),
    ),
    Mutation(
        "参考证明取的是题目当前版本而不是学生做题时的版本",
        API / "services" / "self_check_service.py",
        '    if question.answer_mode != "proof":\n        return []\n    version = question_service.get_version(db, question.id, session.question_version)',
        '    if question.answer_mode != "proof":\n        return []\n    version = question_service.get_version(db, question.id, question.version)',
        ("tests/api/test_admin_proof.py", "tests/api/test_proof.py"),
    ),
    Mutation(
        "自查里没有参考证明",
        API / "services" / "self_check_service.py",
        "        reference_steps=reference_steps,\n        marks=marks,",
        "        reference_steps=[],\n        marks=marks,",
        ("tests/api/test_proof.py",),
    ),
    Mutation(
        "题面里没有已知和求证",
        API / "services" / "question_service.py",
        '        proof=content.get("proof"),',
        "        proof=None,",
        ("tests/api/test_proof.py",),
    ),
    Mutation(
        "证明题可以没有已知和求证也能通过校验",
        API / "services" / "content_seed.py",
        '    if not isinstance(proof, dict) or set(proof) != {"givens", "claim"}:',
        '    if proof is None:\n        return []\n    if not isinstance(proof, dict) or set(proof) != {"givens", "claim"}:',
        ("tests/content/test_proof_content.py", "tests/api/test_admin_proof.py"),
    ),
    Mutation(
        "参考证明可以不以结论收尾",
        API / "services" / "content_seed.py",
        '    if isinstance(last, dict) and last.get("stage") != "conclusion":',
        "    if False:",
        ("tests/content/test_proof_content.py", "tests/api/test_admin_proof.py"),
    ),
    Mutation(
        "参考证明的步骤可以没有依据",
        API / "services" / "content_seed.py",
        '        if not _nonempty_text(step["reason"], _MAX_STEP_REASON):',
        "        if False:",
        ("tests/content/test_proof_content.py", "tests/api/test_admin_proof.py"),
    ),
    Mutation(
        "参考证明的阶段可以随便写",
        API / "services" / "content_seed.py",
        '        if step["stage"] not in _STAGES:',
        "        if False:",
        ("tests/content/test_proof_content.py",),
    ),
    Mutation(
        "证明题可以没有泄题标记",
        API / "services" / "content_seed.py",
        '        or not markers\n        or not all(_nonempty_text(marker, _MAX_SHORT) for marker in markers)\n    ):\n        problems.append(\n            f"{key}: teaching.leak_markers 不能为空（证明题',
        '        or not all(_nonempty_text(marker, _MAX_SHORT) for marker in markers)\n    ):\n        problems.append(\n            f"{key}: teaching.leak_markers 不能为空（证明题',
        ("tests/content/test_proof_content.py",),
    ),
    Mutation(
        "证明题可以带小问",
        API / "services" / "content_seed.py",
        '    if content.get("subquestions"):\n        problems.append(f"{key}: 证明题不分小问',
        '    if False:\n        problems.append(f"{key}: 证明题不分小问',
        ("tests/content/test_proof_content.py",),
    ),
    Mutation(
        "其他题型也能带已知和求证",
        API / "services" / "content_seed.py",
        '    if question["content"].get("proof"):\n        return [f"{key}: 只有证明题才能有 content.proof"]',
        '    if False:\n        return [f"{key}: 只有证明题才能有 content.proof"]',
        ("tests/content/test_proof_content.py",),
    ),
    Mutation(
        "自查要点可以指向不存在的小问、数据表或证明阶段",
        API / "services" / "content_seed.py",
        "        if part in valid_parts:\n            covered.add(part)\n        else:",
        "        if True:\n            covered.add(part)\n        else:",
        ("tests/content/test_proof_content.py", "tests/content/test_experiment_content.py"),
    ),
    Mutation(
        "修改证明题之后新版本丢了已知和求证",
        API / "services" / "review_service.py",
        '                "proof": content.proof.model_dump() if content.proof else None,',
        '                "proof": None,',
        ("tests/api/test_admin_proof.py",),
    ),
    Mutation(
        "审核后台看到的当前版本没有已知和求证",
        API / "services" / "review_service.py",
        '            "safety": content.get("safety"),\n            "proof": content.get("proof"),\n        },\n        "answer": {',
        '            "safety": content.get("safety"),\n            "proof": None,\n        },\n        "answer": {',
        ("tests/api/test_admin_proof.py",),
    ),
    Mutation(
        "证明题的预计用时和实验题一样",
        API / "services" / "task_planner.py",
        "        return 9 + 3 * question.difficulty",
        "        return 10 + 2 * question.difficulty",
        ("tests/api/test_proof.py",),
    ),
    Mutation(
        "学情页只统计解答题和实验题的提交",
        API / "services" / "progress_service.py",
        "    written = [attempt for attempt, _, _, mode, _ in records if mode in grading.SUBJECTIVE_MODES]",
        '    written = [attempt for attempt, _, _, mode, _ in records if mode in ("written", "experiment")]',
        ("tests/api/test_proof.py",),
    ),
    Mutation(
        "家长周报只统计解答题和实验题的提交",
        API / "services" / "weekly_service.py",
        "        written_attempts=sum(1 for _, _, _, mode, _ in records if mode in grading.SUBJECTIVE_MODES),",
        '        written_attempts=sum(1 for _, _, _, mode, _ in records if mode in ("written", "experiment")),',
        ("tests/api/test_proof.py",),
    ),
    # ---- 家长周报：学生明确授权、可撤销；家长只看汇总
    Mutation(
        "家长不检查角色就能进家长接口",
        API / "deps.py",
        '    if principal.role != "parent":\n        raise ApiError(403, "forbidden", "当前角色无权访问")',
        '    if False:\n        raise ApiError(403, "forbidden", "当前角色无权访问")',
        ("tests/api/test_parent_consent.py", "tests/api/test_security.py"),
    ),
    Mutation(
        "授权撤销之后家长仍然能看周报",
        API / "services" / "parent_service.py",
        '            ParentStudentLink.student_id == student_id,\n            ParentStudentLink.revoked_at.is_(None),\n            User.status == "active",\n        )\n    ).first()',
        '            ParentStudentLink.student_id == student_id,\n            User.status == "active",\n        )\n    ).first()',
        ("tests/api/test_parent_consent.py", "tests/api/test_parent_weekly.py"),
    ),
    Mutation(
        "家长能看别的家长绑定的学生",
        API / "services" / "parent_service.py",
        "            ParentStudentLink.parent_id == parent_id,\n            ParentStudentLink.student_id == student_id,",
        "            ParentStudentLink.student_id == student_id,",
        ("tests/api/test_parent_weekly.py",),
    ),
    Mutation(
        "家长的学生列表里还有已经撤销授权的",
        API / "services" / "parent_service.py",
        "            ParentStudentLink.parent_id == parent_id,\n            ParentStudentLink.revoked_at.is_(None),\n",
        "            ParentStudentLink.parent_id == parent_id,\n",
        ("tests/api/test_parent_consent.py",),
    ),
    Mutation(
        "学生的授权列表里还有已经撤销的",
        API / "services" / "parent_service.py",
        ".where(ParentStudentLink.student_id == student_id, ParentStudentLink.revoked_at.is_(None))",
        ".where(ParentStudentLink.student_id == student_id)",
        ("tests/api/test_parent_consent.py",),
    ),
    Mutation(
        "别的学生也能撤销这个授权",
        API / "services" / "parent_service.py",
        "        .where(ParentStudentLink.id == link_id, ParentStudentLink.student_id == student_id)",
        "        .where(ParentStudentLink.id == link_id)",
        ("tests/api/test_parent_consent.py",),
    ),
    Mutation(
        "邀请码可以重复使用",
        API / "services" / "parent_service.py",
        "            ParentInvite.id == invite.id,\n            ParentInvite.redeemed_at.is_(None),\n",
        "            ParentInvite.id == invite.id,\n",
        ("tests/api/test_parent_consent.py",),
    ),
    Mutation(
        "过期的邀请码仍然能用",
        API / "services" / "parent_service.py",
        "            ParentInvite.expires_at > now,\n        )\n        .values(redeemed_at=now, redeemed_by=parent_id)",
        "            True,\n        )\n        .values(redeemed_at=now, redeemed_by=parent_id)",
        ("tests/api/test_parent_consent.py",),
    ),
    Mutation(
        "新的邀请码不作废学生之前没用掉的",
        API / "services" / "parent_service.py",
        "        old.revoked_at = now  # 再生成一个，旧的立刻作废",
        "        pass",
        ("tests/api/test_parent_consent.py",),
    ),
    Mutation(
        "邀请码明文落了库",
        API / "services" / "parent_service.py",
        "        code_hash=_hash(code),",
        "        code_hash=code,",
        ("tests/api/test_parent_consent.py",),
    ),
    Mutation(
        "授权时间记成了家长输入的时间",
        API / "services" / "parent_service.py",
        "            consent_at=invite.created_at,",
        "            consent_at=now,",
        ("tests/api/test_parent_consent.py",),
    ),
    Mutation(
        "已经绑定着还能再兑换一次",
        API / "services" / "parent_service.py",
        '        raise conflict("already_linked", "已经绑定着这位学生了")',
        "        pass",
        ("tests/api/test_parent_consent.py",),
    ),
    Mutation(
        "没授权的家长也能问日期合不合法",
        API / "services" / "weekly_service.py",
        "    _, student = parent_service.require_link(db, parent_id, student_id)\n    start_date, start, end, offset = _window(settings, week_start, now)",
        "    start_date, start, end, offset = _window(settings, week_start, now)\n    _, student = parent_service.require_link(db, parent_id, student_id)",
        ("tests/api/test_parent_weekly.py",),
    ),
    Mutation(
        "一周的末尾把下周一零点也算进来",
        API / "services" / "progress_service.py",
        "        query = query.where(Attempt.submitted_at < until)",
        "        query = query.where(Attempt.submitted_at <= until)",
        ("tests/api/test_parent_weekly.py",),
    ),
    Mutation(
        "周按 UTC 划分而不是配置的时区",
        API / "services" / "weekly_service.py",
        "    offset = timezone(timedelta(minutes=settings.report_utc_offset_minutes))",
        "    offset = UTC",
        ("tests/api/test_parent_weekly.py",),
    ),
    Mutation(
        "趋势的临界值不算变了",
        API / "services" / "weekly_service.py",
        "    if delta >= TREND_THRESHOLD:",
        "    if delta > TREND_THRESHOLD:",
        ("tests/api/test_parent_weekly.py",),
    ),
    Mutation(
        "有一周样本不足也硬比趋势",
        API / "services" / "weekly_service.py",
        '    if previous is None or current is None:\n        return "unknown"',
        "    if previous is None:\n        previous = 0.0\n    if current is None:\n        current = 0.0",
        ("tests/api/test_parent_weekly.py",),
    ),
    Mutation(
        "SEC301 关闭兑换限流",
        API / "services" / "parent_invite_rate_limit.py",
        "            if any(",
        "            if False and any(",
        ("tests/api/test_parent_security.py",),
    ),
    Mutation(
        "SEC301 幂等存储保留明文",
        API / "idempotency.py",
        "                stored_response(payload)\n",
        "                payload\n",
        ("tests/api/test_parent_security.py",),
    ),
    Mutation(
        "SEC301 允许到期邀请码重放",
        API / "services" / "parent_invite_security.py",
        "        or invite.expires_at <= ctx.now()",
        "        or False",
        ("tests/api/test_parent_security.py",),
    ),
    Mutation(
        "SEC301 并发兑换跳过原子领取",
        API / "services" / "parent_service.py",
        "    if claimed.rowcount != 1:",
        "    if False:",
        ("tests/api/test_parent_security.py",),
    ),
    Mutation(
        "DATA302 正式回执丢失唯一占位",
        API / "receipts.py",
        "        ctx.db.add(record)\n        ctx.db.flush()",
        "        pass  # no durable receipt\n        ctx.db.flush()",
        ("tests/api/test_receipt_store.py",),
    ),
    Mutation(
        "DATA302 请求指纹不再冲突",
        API / "idempotency.py",
        "    if record.fingerprint != fingerprint:",
        "    if False:",
        ("tests/api/test_receipt_store.py",),
    ),
    Mutation(
        "DATA302 允许业务提前提交",
        API / "receipts.py",
        '            if not session.in_nested_transaction() and not session.info.get(\n                "receipt_commit_allowed"\n            ):',
        "            if False:",
        ("tests/integration/test_durable_receipts.py",),
    ),
    Mutation(
        "DATA302 旧Redis所有者删除新租约",
        API / "receipt_coordination.py",
        "if redis.call('GET',KEYS[1]) == ARGV[1] then return redis.call('DEL',KEYS[1]) else return 0 end",
        "return redis.call('DEL',KEYS[1])",
        ("tests/integration/test_durable_receipts.py",),
    ),
    Mutation(
        "REDIS-LIMIT 绕过全局上限",
        API / "services" / "parent_invite_rate_limit.py",
        "  if count > 0 and count-1 >= tonumber(ARGV[i+2]) then return 0 end",
        "  if i == 1 and count > 0 and count-1 >= tonumber(ARGV[i+2]) then return 0 end",
        ("tests/integration/test_redis_invite_limits.py",),
    ),
    Mutation(
        "REDIS-LIMIT 绕过actor上限",
        API / "services" / "parent_invite_rate_limit.py",
        "  if count > 0 and count-1 >= tonumber(ARGV[i+2]) then return 0 end",
        "  if i == 2 and count > 0 and count-1 >= tonumber(ARGV[i+2]) then return 0 end",
        ("tests/integration/test_redis_invite_limits.py",),
    ),
    Mutation(
        "REDIS-LIMIT 配置切换重置额度",
        API / "services" / "parent_invite_rate_limit.py",
        "    if first[1] ~= marker then return 0 end",
        "    if false then return 0 end",
        ("tests/integration/test_redis_invite_limits.py",),
    ),
    Mutation(
        "REDIS-LIMIT 移除桶TTL",
        API / "services" / "parent_invite_rate_limit.py",
        "  if fresh or mode == 'sliding' then redis.call('PEXPIRE',KEYS[i],window) end",
        "  -- no expiry",
        ("tests/integration/test_redis_invite_limits.py",),
    ),
    Mutation(
        "REDIS-LIMIT 故障静默放行",
        API / "services" / "parent_invite_rate_limit.py",
        "        except Exception:\n            raise _denied() from None",
        "        except Exception:\n            return",
        (
            "tests/unit/test_parent_invite_rate_limit.py",
            "tests/integration/test_redis_invite_limits.py",
        ),
    ),
    Mutation(
        "RUNTIME301 managed误走原型DDL",
        API / "main.py",
        "            if managed:\n                validate_managed_startup(",
        "            if False:\n                validate_managed_startup(",
        (
            "tests/integration/test_managed_runtime.py::test_managed_startup_is_read_only_and_ping_does_not_charge",
        ),
    ),
    Mutation(
        "RUNTIME301 dirty迁移仍启动",
        API / "runtime_dependencies.py",
        '            if any(\n                row["state"] != "applied"',
        '            if False and any(\n                row["state"] != "applied"',
        (
            "tests/integration/test_managed_runtime.py::test_managed_incomplete_or_tampered_schema_refused_and_engine_disposed[running]",
        ),
    ),
    Mutation(
        "RUNTIME301 原型路由隔离丢失",
        API / "main.py",
        "            if managed and module is document_imports",
        "            if False and managed and module is document_imports",
        (
            "tests/integration/test_managed_runtime.py::test_managed_real_startup_role_owner_and_durable_invite_replay[staging]",
        ),
    ),
    Mutation(
        "RUNTIME301 忽略Redis健康故障",
        API / "runtime_dependencies.py",
        "            if client.ping() is not True:",
        "            if False:",
        (
            "tests/integration/test_managed_runtime.py::test_managed_health_failure_never_recreates_or_falls_back[redis_unavailable]",
        ),
    ),
]


@dataclass(frozen=True)
class TestRun:
    status: str
    detail: str = ""
    artifact: str | None = None


def _directory(parent: Path, prefix: str) -> Path:
    parent.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=prefix, dir=parent)).resolve()


def _classify(report, returncode):
    try:
        root = ET.parse(report).getroot()
    except (OSError, ET.ParseError):
        return TestRun("invalid", "missing or malformed JUnit report")
    cases = list(root.iter("testcase"))
    errors = list(root.iter("error"))
    failures = list(root.iter("failure"))
    skipped = list(root.iter("skipped"))
    if errors or returncode not in (0, 1) or not cases:
        return TestRun("invalid", "pytest collection/setup/runner error")
    if any(
        f.get("type", "").rsplit(".", 1)[-1] in {"ImportError", "ModuleNotFoundError"}
        for f in failures
    ):
        return TestRun("invalid", "test import failure")
    if skipped:
        return TestRun("not_run", "one or more guard tests skipped")
    if failures and returncode == 1:
        return TestRun("failed")
    if not failures and returncode == 0:
        return TestRun("passed")
    return TestRun("invalid", "inconsistent pytest report and exit code")


def _run(tests: tuple[str, ...]) -> TestRun:
    """Preserve original test output and JUnit; assertion evidence alone counts."""
    parent = _EVIDENCE_ROOT.get()
    if parent is None:
        parent = _directory(DEFAULT_OUTPUT_ROOT, "mutation-evidence-")
    directory = _directory(parent, "run-")
    report = directory / "junit.xml"
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "-x",
        "-p",
        "no:cacheprovider",
        "--junitxml",
        str(report),
        *tests,
    ]
    metadata = {"command": command, "tests": list(tests), "returncode": None}
    (directory / "stdout.log").write_text("", encoding="utf-8")
    (directory / "stderr.log").write_text("", encoding="utf-8")
    try:
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        (directory / "stdout.log").write_text(completed.stdout or "", encoding="utf-8")
        (directory / "stderr.log").write_text(completed.stderr or "", encoding="utf-8")
        metadata["returncode"] = completed.returncode
        classified = _classify(report, completed.returncode)
    except BaseException as error:
        # Preserve diagnostics even if subprocess launch itself fails; caller still
        # receives the original exception, retaining the source restoration path.
        metadata.update(
            status="invalid",
            detail="subprocess runner exception",
            exception_type=type(error).__name__,
        )
        (directory / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        raise
    metadata.update(
        status=classified.status, detail=classified.detail, junit_exists=report.is_file()
    )
    (directory / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return TestRun(classified.status, classified.detail, str(directory))


def _required_environment(tests: tuple[str, ...]) -> tuple[str, ...]:
    paths = " ".join(tests)
    required = []
    if any(
        name in paths
        for name in (
            "test_mysql_budget_admission.py",
            "test_durable_receipts.py",
            "test_managed_runtime.py",
            "test_managed_tutor_transactions.py",
            "test_submission_statistics_mysql.py",
            "test_draft_copies_mysql.py",
            "test_session_version_guard_mysql.py",
            "test_session_create_copy_review_locks_mysql.py",
            "test_submit_revision_guard_mysql.py",
            "test_first_submitted_attempt_mysql.py",
            "test_profile_revision_mysql.py",
            "test_parent_revision_mysql.py",
        )
    ):
        required.append("TUTOR_MYSQL_MIGRATION_TEST_CREDENTIALS")
    if any(
        name in paths
        for name in (
            "test_durable_receipts.py",
            "test_managed_runtime.py",
            "test_managed_tutor_transactions.py",
            "test_redis_invite_limits.py",
            "test_http_limit_redis.py",
            "test_submission_statistics_mysql.py",
            "test_draft_copies_mysql.py",
            "test_session_version_guard_mysql.py",
            "test_session_create_copy_review_locks_mysql.py",
            "test_submit_revision_guard_mysql.py",
            "test_first_submitted_attempt_mysql.py",
        )
    ):
        required.append("TUTOR_REDIS_RECEIPT_TEST_CONFIG")
    if "test_linux_parser_sandbox.py" in paths:
        required.append("TUTOR_LINUX_SANDBOX_CONFIG")
    if any(
        "test_s3_blob_service.py" in target
        or target == "tests/integration/test_managed_runtime.py"
        or "::test_managed_mysql_redis_s3_" in target
        or "::test_managed_s3_" in target
        for target in tests
    ):
        required.append("TUTOR_S3_BLOB_TEST_CONFIG")
    return tuple(required)


def main() -> int:
    parser = argparse.ArgumentParser(description="变异检查（基线与JUnit证据校验）")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="持久证据根目录；每次运行创建唯一子目录",
    )
    parser.add_argument("--only", help="只跑名称里包含这段文字的变异，例如 --only 归属")
    parser.add_argument(
        "--allow-not-run",
        action="store_true",
        help="允许缺少显式基础设施配置的not_run；不计入抓到数量",
    )
    args = parser.parse_args()
    selected = [m for m in MUTATIONS if not args.only or args.only in m.name]
    if not selected:
        print(f"没有名称包含 {args.only!r} 的变异")
        return 1

    counts = dict.fromkeys(
        ("caught", "survived", "broken", "preflight_failed", "invalid", "not_run"), 0
    )
    baselines: dict[tuple[str, ...], TestRun] = {}
    evidence = _directory(args.output, "mutation-evidence-")
    token = _EVIDENCE_ROOT.set(evidence)
    targets = []
    try:
        for mutation in selected:
            entry = {
                "target": mutation.name,
                "tests": list(mutation.tests),
                "status": "running",
                "baseline": None,
                "result": None,
            }
            targets.append(entry)
            source_bytes = mutation.path.read_bytes()
            source = source_bytes.decode("utf-8").replace("\r\n", "\n")
            if source.count(mutation.original) != 1:
                entry["status"] = "broken"
                counts["broken"] += 1
                print(f"[broken] {mutation.name}：源码片段不唯一，未执行")
                continue
            if any(not os.environ.get(key) for key in _required_environment(mutation.tests)):
                entry["status"] = "not_run"
                counts["not_run"] += 1
                print(f"[not_run] {mutation.name}：缺少显式隔离基础设施配置")
                continue
            if mutation.tests not in baselines:
                baselines[mutation.tests] = _run(mutation.tests)
            baseline = baselines[mutation.tests]
            entry["baseline"] = asdict(baseline)
            if baseline.status != "passed":
                entry["status"] = "preflight_failed"
                counts["preflight_failed"] += 1
                print(
                    f"[preflight_failed] {mutation.name}：原始实现测试未完整通过 ({baseline.status}) 证据={baseline.artifact}"
                )
                continue
            try:
                mutation.path.write_bytes(
                    source.replace(mutation.original, mutation.mutated).encode("utf-8")
                )
                result = _run(mutation.tests)
            finally:
                mutation.path.write_bytes(source_bytes)
            status = {"failed": "caught", "passed": "survived"}.get(result.status, "invalid")
            entry.update(status=status, result=asdict(result))
            counts[status] += 1
            print(
                f"[{status}] {mutation.name}"
                + (f"：{result.detail}" if result.detail else "")
                + (f" 证据={result.artifact}" if status == "invalid" else "")
            )
    except BaseException as error:
        if targets and targets[-1]["status"] == "running":
            targets[-1].update(status="runner_exception", exception_type=type(error).__name__)
        raise
    finally:
        _EVIDENCE_ROOT.reset(token)
        summary = evidence / "summary.json"
        summary.write_text(
            json.dumps(
                {"counts": counts, "selected": len(selected), "targets": targets},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"证据汇总：{summary}")
    print(f"\n{counts['caught']}/{len(selected)} 处变异被测试抓到")
    print(" ".join(f"{key}={value}" for key, value in counts.items()))
    return int(
        any(counts[key] for key in ("survived", "broken", "preflight_failed", "invalid"))
        or (counts["not_run"] > 0 and not args.allow_not_run)
    )


if __name__ == "__main__":
    sys.exit(main())
