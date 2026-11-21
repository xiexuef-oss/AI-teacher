"""运行配置。全部来自环境变量（前缀 TUTOR_），不读取任何密钥文件。"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]
CONTRACTS_DIR = REPO_ROOT / "contracts"
EVENT_SCHEMA_PATH = CONTRACTS_DIR / "tutor_event.schema.json"
OPENAPI_PATH = CONTRACTS_DIR / "openapi.yaml"
VISUAL_REGISTRY_PATH = REPO_ROOT / "packages" / "visual_templates" / "registry.json"
SEED_DIR = REPO_ROOT / "services" / "api" / "seed"


class Settings(BaseSettings):
    # env_ignore_empty：.env.example 里留空的变量按"未设置"处理，而不是空字符串
    model_config = SettingsConfigDict(
        env_prefix="TUTOR_", extra="ignore", env_ignore_empty=True, hide_input_in_errors=True
    )

    env: Literal["local", "dev", "staging", "prod"] = "local"
    database_url: str = Field(default="sqlite:///var/tutor_dev.sqlite3", repr=False)
    # 受控环境工程保护值，不是生产SLA；读写为驱动socket超时，不是SQL总时限。
    database_connect_timeout_seconds: int = Field(default=5, ge=1, le=120)
    database_read_timeout_seconds: int = Field(default=10, ge=1, le=120)
    database_write_timeout_seconds: int = Field(default=10, ge=1, le=120)
    database_pool_timeout_seconds: float = Field(default=10, gt=0, le=120)
    database_lock_timeout_seconds: int = Field(default=5, strict=True, ge=1, le=120)
    database_sqlite_busy_timeout_seconds: float = Field(default=10, ge=0.001, le=120)

    # 本地身份 Mock（Q-03）：必须显式开启，只允许 local 环境，开启后只接受回环地址的请求
    local_identity_mock: bool = False
    # 启动时把自编工程样题写入空库（Q-05）
    seed_sample_content: bool = False

    # 间隔复测的间隔（分钟），逗号分隔。默认 T+1 / T+3 / T+7 天，可配、非保证最佳
    review_intervals_minutes: str = "1440,4320,10080"
    # 学情统计的最小样本数，低于它显示"信息不足"
    progress_min_samples: int = Field(default=5, ge=1)
    # 家长邀请码的有效期（分钟）。邀请码是学生明确授权的第一步，用一次就作废
    parent_invite_redeem_window_mode: Literal["fixed", "sliding"] = "fixed"
    parent_invite_redeem_limit: int = Field(default=30, ge=1, le=10000)
    parent_invite_redeem_global_limit: int = Field(default=1000, ge=1, le=100000)
    parent_invite_redeem_window_seconds: int = Field(default=60, ge=1, le=3600)
    parent_invite_ttl_minutes: int = Field(default=1440, ge=1)
    # 周报按哪个时区划分"一周"（相对 UTC 的分钟数）。首发地区四川、重庆都是 UTC+8；不查时区数据库，Windows 上没有
    report_utc_offset_minutes: int = Field(default=480, ge=-720, le=840)
    # 草稿同步请求体上限（字节）
    max_draft_bytes: int = Field(default=2_000_000, ge=1024)

    # 通用HTTP资源保护；local默认关闭，受控环境启用时必须显式注入共享Redis适配器。
    http_limits_enabled: bool = False
    http_limit_window_mode: Literal["fixed", "sliding"] = "fixed"
    http_limit_window_seconds: int = Field(default=60, ge=1, le=3600)
    http_limit_per_peer: int = Field(default=120, ge=1, le=100000)
    http_limit_per_actor: int = Field(default=120, ge=1, le=100000)
    http_limit_global: int = Field(default=1000, ge=1, le=1000000)
    http_route_requests: dict[str, Annotated[int, Field(strict=True, ge=1, le=100000)]] = Field(
        default_factory=dict, max_length=64
    )
    http_max_inflight: int = Field(default=16, ge=1, le=128)
    http_max_body_bytes: int = Field(default=24 * 1024 * 1024, ge=1024, le=64 * 1024 * 1024)
    http_body_timeout_seconds: float = Field(default=30, gt=0, le=120)

    # 本地文档导入原型的资源上限和临时生命周期，不是生产留存政策（Q-07）。
    import_max_file_bytes: int = Field(default=10 * 1024 * 1024, ge=1024, le=16 * 1024 * 1024)
    import_max_job_bytes: int = Field(default=50 * 1024 * 1024, ge=1024)
    import_max_files: int = Field(default=10, ge=1, le=20)
    import_max_pages: int = Field(default=80, ge=1, le=200)
    import_max_candidates: int = Field(default=200, ge=1, le=200)
    import_temporary_ttl_minutes: int = Field(default=120, ge=5, le=1440)
    import_worker_enabled: bool = False
    learning_pack_worker_enabled: bool = False
    learning_pack_sample_font: Path | None = None
    learning_pack_pdf_s3_config: Path | None = None
    learning_pack_media_s3_config: Path | None = None
    import_ocr_mode: Literal["disabled", "mock", "configured"] = "disabled"
    import_doc_converter: Path | None = None
    import_parse_timeout_seconds: int = Field(default=30, ge=1, le=120)
    import_memory_limit_bytes: int | None = Field(
        default=None, ge=64 * 1024 * 1024, le=4 * 1024 * 1024 * 1024
    )
    import_cpu_limit_seconds: int | None = Field(default=None, ge=1, le=120)
    import_isolation_mode: Literal["process", "linux_bwrap"] = "process"
    import_linux_bwrap: Path | None = None
    import_linux_runtime: Path | None = None
    import_linux_cgroup: bool = False
    import_linux_task_limit: int = Field(default=16, ge=4, le=128)
    import_linux_cpu_percent: int = Field(default=100, ge=1, le=100)
    import_worker_lease_seconds: int = Field(default=180, ge=30, le=600)
    import_max_extracted_chars: int = Field(default=100_000, ge=4000, le=400_000)
    import_max_unpacked_bytes: int = Field(default=48 * 1024 * 1024, ge=1024)
    import_max_image_pixels: int = Field(default=20_000_000, ge=1024, le=40_000_000)

    # 仅本地媒体原型；默认关闭，不定义生产对象存储或留存策略。
    scan_mock_enabled: bool = False
    media_local_enabled: bool = False
    media_root: Path = REPO_ROOT / "var" / "media"
    media_temporary_ttl_seconds: int = Field(default=7200, ge=60, le=86400)
    media_max_bytes: int = Field(default=10 * 1024 * 1024, ge=1024, le=16 * 1024 * 1024)
    media_max_pixels: int = Field(default=20_000_000, ge=1024, le=40_000_000)

    # 学生去标识化用的 HMAC 密钥；非 local 环境必填
    pseudonym_secret: str | None = Field(default=None, repr=False)

    model_routes_path: Path = REPO_ROOT / "config" / "model_routes.example.yaml"
    allow_external_model_calls: bool = False
    durable_model_invocations_enabled: bool = False
    model_cost_overrun_policy: Literal["record_only", "pause_platform"] = "record_only"

    @field_validator("database_lock_timeout_seconds", mode="before")
    @classmethod
    def _lock_timeout_integer(cls, value: object) -> object:
        # Environment values are text; only integer text may enter the strict SQL setting.
        if isinstance(value, str) and value.strip().isdecimal():
            return int(value)
        return value

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.scan_mock_enabled and (self.env != "local" or not self.media_local_enabled):
            raise ValueError("拍题Mock仅允许local且需开启本地媒体")
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
