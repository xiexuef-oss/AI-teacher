from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from ai_gateway import GatewayConfig, InMemoryAuditSink, InMemoryBudgetStore, build_gateway
from support.gateway_fakes import (
    EVENT_SCHEMA_PATH,
    FULL_ENV,
    VISUAL_REGISTRY_PATH,
    FakeClock,
    Harness,
    config_dict,
)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def make_gateway(clock: FakeClock) -> Callable[..., Harness]:
    """按给定供应商配置、候选顺序和假适配器构造网关。"""

    def factory(
        providers: dict[str, dict],
        order: list[str],
        adapters: dict[str, Any],
        *,
        env: dict[str, str] | None = None,
        environment: str = "local",
        allow_external_calls: bool = True,
        **overrides: Any,
    ) -> Harness:
        audit = InMemoryAuditSink()
        budget = InMemoryBudgetStore()
        gateway = build_gateway(
            GatewayConfig.model_validate(config_dict(providers, order, **overrides)),
            env=FULL_ENV if env is None else env,
            environment=environment,
            allow_external_calls=allow_external_calls,
            event_schema_path=EVENT_SCHEMA_PATH,
            visual_registry_path=VISUAL_REGISTRY_PATH,
            audit=audit,
            budget_store=budget,
            adapter_overrides=adapters,
            now=clock.now,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )
        return Harness(gateway, clock, audit, budget)

    return factory
