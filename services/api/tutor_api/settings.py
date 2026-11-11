"""运行配置。全部来自环境变量（前缀 TUTOR_），不读取任何密钥文件。"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]
CONTRACTS_DIR = REPO_ROOT / "contracts"
EVENT_SCHEMA_PATH = CONTRACTS_DIR / "tutor_event.schema.json"
OPENAPI_PATH = CONTRACTS_DIR / "openapi.yaml"
VISUAL_REGISTRY_PATH = REPO_ROOT / "packages" / "visual_templates" / "registry.json"
SEED_DIR = REPO_ROOT / "services" / "api" / "seed"


class Settings(BaseSettings):
    # env_ignore_empty：.env.example 里留空的变量按"未设置"处理，而不是空字符串
    model_config = SettingsConfigDict(env_prefix="TUTOR_", extra="ignore", env_ignore_empty=True)

    env: Literal["local", "dev", "staging", "prod"] = "local"
    database_url: str = "sqlite:///var/tutor_dev.sqlite3"

    # 本地身份 Mock（Q-03）：必须显式开启，只允许 local 环境，开启后只接受回环地址的请求
    local_identity_mock: bool = False
    # 启动时把自编工程样题写入空库（Q-05）
    seed_sample_content: bool = False

    # 间隔复测的间隔（分钟），逗号分隔。默认 T+1 / T+3 / T+7 天，可配、非保证最佳
    review_intervals_minutes: str = "1440,4320,10080"
    # 学情统计的最小样本数，低于它显示"信息不足"
    progress_min_samples: int = Field(default=5, ge=1)
    # 草稿同步请求体上限（字节）
    max_draft_bytes: int = Field(default=2_000_000, ge=1024)

    # 学生去标识化用的 HMAC 密钥；非 local 环境必填
    pseudonym_secret: str | None = None

    model_routes_path: Path = REPO_ROOT / "config" / "model_routes.example.yaml"
    allow_external_model_calls: bool = False

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.local_identity_mock and self.env != "local":
            raise ValueError("本地身份 Mock 只允许在 TUTOR_ENV=local 时开启")
        if self.env != "local" and not self.pseudonym_secret:
            raise ValueError("非 local 环境必须设置 TUTOR_PSEUDONYM_SECRET")
        intervals = self.review_intervals
        if not intervals or any(i <= timedelta(0) for i in intervals):
            raise ValueError("TUTOR_REVIEW_INTERVALS_MINUTES 必须是逗号分隔的正整数")
        return self

    @property
    def review_intervals(self) -> list[timedelta]:
        try:
            return [
                timedelta(minutes=int(part))
                for part in self.review_intervals_minutes.split(",")
                if part.strip()
            ]
        except ValueError:
            return []
