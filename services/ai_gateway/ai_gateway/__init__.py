"""AI Model Gateway（GW-001）。

所有模型调用都从这里走：FastAPI → Teaching Orchestrator → ModelGateway → 供应商适配器。
客户端不持有任何供应商密钥。
"""

from ai_gateway.audit import AuditRecord, AuditSink, InMemoryAuditSink
from ai_gateway.budget import BudgetStore, InMemoryBudgetStore
from ai_gateway.config import GatewayConfig, load_config
from ai_gateway.dto import (
    Constraints,
    CostBudget,
    GatewayRequest,
    GatewayResponse,
    InputPart,
    PrivacyPolicy,
    TaskType,
    Usage,
)
from ai_gateway.errors import OutputRejected, ProviderError
from ai_gateway.gateway import CandidateStatus, ModelGateway, build_gateway
from ai_gateway.prompts import PROMPT_VERSION
from ai_gateway.providers.base import ProviderAdapter, ProviderResult
from ai_gateway.validation import OutputValidator
from ai_gateway.visual_templates import VisualRegistry, VisualTemplateError

__all__ = [
    "PROMPT_VERSION",
    "AuditRecord",
    "AuditSink",
    "BudgetStore",
    "CandidateStatus",
    "Constraints",
    "CostBudget",
    "GatewayConfig",
    "GatewayRequest",
    "GatewayResponse",
    "InMemoryAuditSink",
    "InMemoryBudgetStore",
    "InputPart",
    "ModelGateway",
    "OutputRejected",
    "OutputValidator",
    "PrivacyPolicy",
    "ProviderAdapter",
    "ProviderError",
    "ProviderResult",
    "TaskType",
    "Usage",
    "VisualRegistry",
    "VisualTemplateError",
    "build_gateway",
    "load_config",
]
