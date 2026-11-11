"""图解模板注册表的进程内缓存。"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from ai_gateway import VisualRegistry, VisualTemplateError
from tutor_api.settings import VISUAL_REGISTRY_PATH


@lru_cache(maxsize=1)
def visual_registry() -> VisualRegistry:
    return VisualRegistry.load(VISUAL_REGISTRY_PATH)


def normalized_visual(visual: dict[str, Any] | None) -> dict[str, Any] | None:
    """返回参数已按注册表补齐的图解配置；没有配置或通不过白名单时返回 None。"""
    if not visual:
        return None
    registry = visual_registry()
    try:
        params = registry.normalize(visual["template_id"], visual.get("params") or {})
    except (VisualTemplateError, KeyError):
        return None
    template = registry.get(visual["template_id"])
    return {
        "template_id": template.template_id,
        "params": params,
        "caption": visual.get("caption") or template.summary,
        "static_fallback": visual.get("static_fallback") or template.static_fallback,
    }
