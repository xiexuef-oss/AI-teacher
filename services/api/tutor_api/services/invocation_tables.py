"""Shared internal invocation and cost-control metadata tables."""

from sqlalchemy import CHAR, JSON, Boolean, Column, Integer, MetaData, String, Table

from tutor_api.db import UTCDateTime

metadata = MetaData()


intents = Table(
    "model_invocation_intents",
    metadata,
    Column("id", CHAR(32), primary_key=True),
    Column("actor_digest", CHAR(64), nullable=False),
    Column("active_session_digest", CHAR(64), unique=True),
    Column("state", String(24), nullable=False),
    Column("fence", Integer, nullable=False),
    Column("metadata_json", JSON, nullable=False),
)

incidents = Table(
    "model_budget_incidents",
    metadata,
    Column("id", CHAR(32), primary_key=True),
    Column("metadata_json", JSON, nullable=False),
    Column("created_at", UTCDateTime(), nullable=False, index=True),
)

dispatch_gate = Table(
    "model_dispatch_gate",
    metadata,
    Column("id", String(16), primary_key=True),
    Column("paused", Boolean, nullable=False),
    Column("incident_id", CHAR(32)),
    Column("updated_at", UTCDateTime(), nullable=False),
)
