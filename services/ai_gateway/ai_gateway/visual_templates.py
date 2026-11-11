"""图解模板白名单（packages/visual_templates/registry.json）的加载与参数校验。

只接受注册过的 template_id 和落在边界内的有限数值参数；任何多余的东西都拒绝。
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class VisualTemplateError(ValueError):
    """模板未注册，或参数不在注册的边界内。"""


@dataclass(frozen=True)
class ParamSpec:
    name: str
    label: str
    min: float
    max: float
    step: float
    default: float
    integer: bool
    adjustable: bool


@dataclass(frozen=True)
class TemplateSpec:
    template_id: str
    title: str
    summary: str
    static_fallback: str
    params: tuple[ParamSpec, ...]


class VisualRegistry:
    def __init__(self, templates: dict[str, TemplateSpec]) -> None:
        self._templates = templates

    @classmethod
    def load(cls, path: Path | str) -> VisualRegistry:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        templates = {
            template_id: TemplateSpec(
                template_id=template_id,
                title=spec["title"],
                summary=spec["summary"],
                static_fallback=spec["static_fallback"],
                params=tuple(ParamSpec(**param) for param in spec["params"]),
            )
            for template_id, spec in raw["templates"].items()
        }
        return cls(templates)

    def template_ids(self) -> set[str]:
        return set(self._templates)

    def get(self, template_id: str) -> TemplateSpec:
        try:
            return self._templates[template_id]
        except KeyError:
            raise VisualTemplateError(f"未注册的图解模板：{template_id!r}") from None

    def normalize(self, template_id: str, params: Mapping[str, Any]) -> dict[str, float | int]:
        """校验参数并用默认值补齐，按注册顺序返回。"""
        template = self.get(template_id)
        known = {spec.name for spec in template.params}
        unknown = set(params) - known
        if unknown:
            raise VisualTemplateError(f"{template_id} 不接受参数：{sorted(unknown)}")

        normalized: dict[str, float | int] = {}
        for spec in template.params:
            value = params.get(spec.name, spec.default)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise VisualTemplateError(f"{template_id}.{spec.name} 必须是数值")
            if not math.isfinite(value):
                raise VisualTemplateError(f"{template_id}.{spec.name} 必须是有限数值")
            if not spec.min <= value <= spec.max:
                raise VisualTemplateError(
                    f"{template_id}.{spec.name}={value} 超出范围 [{spec.min}, {spec.max}]"
                )
            if spec.integer:
                if float(value) != math.floor(value):
                    raise VisualTemplateError(f"{template_id}.{spec.name} 必须是整数")
                value = int(value)
            normalized[spec.name] = value
        return normalized
