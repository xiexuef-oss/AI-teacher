from __future__ import annotations

from datetime import datetime

from pydantic import TypeAdapter

_ADAPTER = TypeAdapter(datetime)


def iso(value: datetime) -> str:
    """UTC ISO-8601 字符串，写法与接口里其他时间字段完全一致（由同一个序列化器产生）。"""
    return _ADAPTER.dump_python(value, mode="json")
