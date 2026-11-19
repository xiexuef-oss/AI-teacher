"""Explicit startup wiring; managed environments never auto-create tables."""

from sqlalchemy import inspect

from ai_gateway import ModelGateway
from ai_gateway.invocation_state import InvocationTransitions
from tutor_api.receipts import SqlReceiptStore
from tutor_api.services.invocation_store import InvocationStore, intents, metadata
from tutor_api.services.invocation_tables import dispatch_gate, incidents
from tutor_api.services.model_cost_gate import ModelCostGate
from tutor_api.settings import CONTRACTS_DIR


def validate_configuration(settings, receipts, gateway=None):
    if not settings.durable_model_invocations_enabled and (
        settings.allow_external_model_calls
        or isinstance(gateway, ModelGateway)
        and gateway._allow_external_calls
    ):
        raise ValueError("外部模型业务调用需要启用持久模型调用")
    if (
        settings.model_cost_overrun_policy == "pause_platform"
        and not settings.durable_model_invocations_enabled
    ):
        raise ValueError("成本暂停策略需要启用持久模型调用")
    if settings.durable_model_invocations_enabled and (
        not settings.pseudonym_secret or not isinstance(receipts, SqlReceiptStore)
    ):
        raise ValueError("持久模型调用需要稳定去标识密钥和正式SQL回执")


def _check_cost_tables(inspector, tables):
    if not {dispatch_gate.name, incidents.name} <= tables:
        raise ValueError("模型成本保护迁移未就绪")
    for table in (dispatch_gate, incidents):
        if not set(table.c.keys()) <= {
            c["name"] for c in inspector.get_columns(table.name)
        } or inspector.get_pk_constraint(table.name)["constrained_columns"] != ["id"]:
            raise ValueError("模型成本保护表结构不完整")


def initialize(engine, factory, settings, receipts, clock, *, managed, gateway=None):
    validate_configuration(settings, receipts, gateway)
    enabled = settings.durable_model_invocations_enabled
    if (
        isinstance(gateway, ModelGateway)
        and gateway._config.budgets.has_daily_cost_limits
        and not enabled
    ):
        raise ValueError("每日金额额度需要启用持久模型调用")
    if enabled and not managed:
        metadata.create_all(engine)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if enabled and intents.name not in tables:
        raise ValueError("持久模型调用迁移未就绪")
    gate = None
    if enabled or {dispatch_gate.name, incidents.name} & tables:
        _check_cost_tables(inspector, tables)
        gate = ModelCostGate(factory, clock)
    if gateway is not None:
        if gate is not None and not isinstance(gateway, ModelGateway):
            raise ValueError("共享成本保护需要可验证的ModelGateway接线")
        if isinstance(gateway, ModelGateway):
            gateway.require_durable_external_calls()
            if managed:
                gateway.disable_external_calls()
            gateway.bind_dispatch_guard(gate.can_send if gate is not None else None)
    if not enabled:
        return None
    columns = {column["name"] for column in inspector.get_columns(intents.name)}
    unique = inspector.get_unique_constraints(intents.name)
    indexes = inspector.get_indexes(intents.name)
    if (
        not set(intents.c.keys()) <= columns
        or inspector.get_pk_constraint(intents.name)["constrained_columns"] != ["id"]
        or not any(
            row.get("column_names") == ["active_session_digest"]
            for row in unique + [index for index in indexes if index.get("unique")]
        )
    ):
        raise ValueError("持久模型调用表结构不完整")
    return InvocationStore(
        factory,
        InvocationTransitions(CONTRACTS_DIR / "model_invocation.schema.json"),
        now=clock,
        overrun_policy=settings.model_cost_overrun_policy,
    )
