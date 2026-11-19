"""本地 Mock 供应商（Q-04A）。

确定性地按输入拼出结构合法的输出，用来在没有真实模型的情况下跑通链路。它不做任何识别或推理：
识别、推理、核验类任务一律返回空结果并把置信度报为 0，交给上层走"请学生确认 / 暂不可判"的路径。
"""

from __future__ import annotations

from typing import Any

from ai_gateway.dto import GatewayRequest, TaskType
from ai_gateway.providers.base import ProviderResult


def _first_json(request: GatewayRequest) -> dict[str, Any]:
    for part in request.input_parts:
        if part.kind == "json" and part.data is not None:
            return part.data
    return {}


class MockProvider:
    def invoke(self, *, model: str, request: GatewayRequest, timeout_s: float) -> ProviderResult:
        data = _first_json(request)
        task = request.task_type

        if task is TaskType.TUTOR_HINT:
            level = int(data.get("level", 1))
            concept = data.get("concept")
            subject = f"“{concept}”" if concept else "题目考查的概念"
            return ProviderResult(
                output={
                    "event_type": "hint",
                    "payload": {
                        "level": level,
                        "total_levels": int(data.get("total_levels", level)),
                        "style": "layered",
                        "text": f"先回到{subject}的定义，想一想题目里哪个量对应它。",
                        "concept": concept,
                    },
                }
            )

        if task is TaskType.TUTOR_EXPLAIN:
            concept = data.get("concept")
            key_idea = data.get("key_idea")
            subject = f"“{concept}”" if concept else "这个知识点"
            if key_idea:
                text = f"换个说法：{key_idea}。先别急着算，用自己的话把{subject}说一遍，再回到题目里找对应的量。"
            else:
                text = f"换个角度想：先用自己的话说说{subject}讲的是什么，再回到题目里找对应的量。"
            return ProviderResult(
                output={
                    "event_type": "hint",
                    **(
                        {
                            "references": [
                                request.constraints.reference_catalog[0].model_dump(
                                    include={"block_id", "block_sha256", "start", "end"}
                                )
                            ]
                        }
                        if request.constraints.reference_catalog
                        else {}
                    ),
                    "payload": {
                        "level": 1,
                        "total_levels": 1,
                        "style": "rephrase",
                        "text": text,
                        "concept": concept,
                    },
                }
            )

        if task is TaskType.VISUAL_SPEC:
            return ProviderResult(
                output={
                    "event_type": "visual",
                    "payload": {
                        "template_id": data.get("template_id", "quadratic_graph"),
                        "params": data.get("params", {}),
                        "caption": data.get("caption") or "拖动滑块，观察图形怎样随参数变化。",
                        "static_fallback": data.get("static_fallback")
                        or "图解暂不可用时，请先阅读文字讲解。",
                    },
                }
            )

        if task is TaskType.OCR_EXTRACT:
            return ProviderResult(output={"stem_text": "", "expressions": []}, confidence=0.0)

        if task is TaskType.HANDWRITING_UNDERSTAND:
            return ProviderResult(output={"steps": []}, confidence=0.0)

        if task is TaskType.KNOWLEDGE_CLASSIFY:
            return ProviderResult(output={"knowledge_codes": []}, confidence=0.0)

        if task is TaskType.COMPLEX_REASONING:
            return ProviderResult(output={"steps": [], "final_answer": None}, confidence=0.0)

        if task is TaskType.SOLUTION_VERIFY:
            return ProviderResult(
                output={"verdict": "uncertain", "notes": "Mock 供应商不做真实核验。"},
                confidence=0.0,
            )

        return ProviderResult(
            output={"intervals_days": [1, 3, 7], "rationale": "默认间隔 T+1、T+3、T+7 天。"}
        )
