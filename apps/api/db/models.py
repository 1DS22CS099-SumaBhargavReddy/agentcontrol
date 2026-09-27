"""
AgentControl Relational Database Models
Production schemas for PostgreSQL / Supabase with comprehensive indexes.
"""

from datetime import datetime, timezone
import uuid
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON, TypeDecorator
from apps.api.db.session import Base


# Cross-dialect JSON type: uses JSONB on postgres, standard JSON on others
class CompatibleJSON(TypeDecorator):
    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(JSON())


def utc_now():
    return datetime.now(timezone.utc)


class Agent(Base):
    __tablename__ = "agents"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(100), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True)
    owner = Column(String(100), nullable=False, index=True)
    environment = Column(String(50), nullable=False, index=True)  # production, staging, development
    version = Column(String(50), default="1.0.0")
    status = Column(String(50), default="active", index=True)  # active, paused, archived
    capabilities = Column(CompatibleJSON, default=list)
    metadata_info = Column(CompatibleJSON, default=dict)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class Tool(Base):
    __tablename__ = "tools"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(100), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=False)
    version = Column(String(50), default="1.0.0")
    risk_level = Column(String(20), default="medium", index=True)  # low, medium, high, critical
    owner = Column(String(100), default="platform-team")
    is_mcp_discovered = Column(Boolean, default=False, index=True)
    parameters_schema = Column(CompatibleJSON, default=dict)
    tags = Column(CompatibleJSON, default=list)
    timeout_seconds = Column(Float, default=30.0)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class Permission(Base):
    __tablename__ = "permissions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    agent_id = Column(String(100), nullable=False, index=True)  # agent name/id or '*'
    environment = Column(String(50), nullable=False, index=True)  # production, staging, development, '*'
    service = Column(String(100), nullable=False, index=True)  # github, kubernetes, aws, database
    resource = Column(String(100), nullable=False)  # pods, ec2, pr, '*'
    action = Column(String(100), nullable=False)  # read, write, delete, restart, '*'
    effect = Column(String(20), default="allow", nullable=False)  # allow, deny
    conditions = Column(CompatibleJSON, default=dict)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)


class Policy(Base):
    __tablename__ = "policies"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    environment = Column(String(50), nullable=False, index=True)
    version = Column(String(50), default="1.0.0")
    raw_yaml = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    agent_id = Column(String(36), nullable=False, index=True)
    environment = Column(String(50), nullable=False, index=True)
    trace_id = Column(String(64), nullable=False, index=True)
    status = Column(String(50), default="running", index=True)  # running, completed, failed, paused
    total_duration_ms = Column(Float, default=0.0)
    total_tokens = Column(Integer, default=0)
    total_cost_usd = Column(Float, default=0.0)
    metadata_info = Column(CompatibleJSON, default=dict)
    started_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)


class ToolCall(Base):
    __tablename__ = "tool_calls"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id = Column(String(36), nullable=True, index=True)
    agent_id = Column(String(100), nullable=False, index=True)
    environment = Column(String(50), nullable=False, index=True)
    tool_name = Column(String(100), nullable=False, index=True)
    arguments = Column(CompatibleJSON, default=dict)
    status = Column(String(50), default="proposed", index=True)  # proposed, approved, rejected, executing, completed, failed
    risk_score = Column(Float, default=0.0, index=True)
    risk_level = Column(String(20), default="low", index=True)
    requires_approval = Column(Boolean, default=False, index=True)
    approval_id = Column(String(36), nullable=True)
    execution_id = Column(String(36), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tool_call_id = Column(String(36), nullable=False, index=True)
    agent_id = Column(String(100), nullable=False, index=True)
    environment = Column(String(50), nullable=False, index=True)
    tool_name = Column(String(100), nullable=False, index=True)
    parameters = Column(CompatibleJSON, default=dict)
    risk_score = Column(Float, nullable=False)
    risk_level = Column(String(20), nullable=False)
    reason_codes = Column(CompatibleJSON, default=list)
    status = Column(String(50), default="pending", index=True)  # pending, approved, rejected, expired
    requested_by = Column(String(100), nullable=False)
    approved_by = Column(String(100), nullable=True)
    decision_reason = Column(Text, nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class ExecutionRecord(Base):
    __tablename__ = "execution_records"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tool_call_id = Column(String(36), nullable=False, index=True)
    idempotency_key = Column(String(128), nullable=True, index=True)
    status = Column(String(50), nullable=False, index=True)  # success, failed, timed_out, rolled_back
    output = Column(CompatibleJSON, nullable=True)
    error = Column(Text, nullable=True)
    duration_ms = Column(Float, default=0.0)
    retry_attempts = Column(Integer, default=0)
    rollback_performed = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)


class EvaluationRecord(Base):
    __tablename__ = "evaluations"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id = Column(String(36), nullable=False, index=True)
    agent_id = Column(String(100), nullable=False, index=True)
    task_success = Column(Float, nullable=False)
    tool_selection = Column(Float, nullable=False)
    policy_compliance = Column(Float, nullable=False)
    safety = Column(Float, nullable=False)
    latency_ms = Column(Float, default=0.0)
    cost_usd = Column(Float, default=0.0)
    summary = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    timestamp = Column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)
    trace_id = Column(String(64), nullable=True, index=True)
    agent_id = Column(String(100), nullable=False, index=True)
    user_id = Column(String(100), nullable=True, index=True)
    action = Column(String(100), nullable=False, index=True)
    tool_name = Column(String(100), nullable=True, index=True)
    risk_level = Column(String(20), nullable=True)
    policy_decision = Column(String(50), nullable=True)
    approval_status = Column(String(50), nullable=True)
    execution_status = Column(String(50), nullable=True)
    signature_sha256 = Column(String(64), nullable=False)
    payload = Column(CompatibleJSON, default=dict)


class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    key_prefix = Column(String(16), nullable=False, index=True)
    hashed_secret = Column(String(64), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    owner = Column(String(100), nullable=False, index=True)
    role = Column(String(50), default="agent_executor")  # admin, agent_executor, auditor
    scopes = Column(CompatibleJSON, default=list)
    is_active = Column(Boolean, default=True, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)


# Multi-column performance indexes
Index("idx_tool_calls_agent_created", ToolCall.agent_id, ToolCall.created_at)
Index("idx_approvals_agent_status", ApprovalRequest.agent_id, ApprovalRequest.status)
Index("idx_audit_timestamp_agent", AuditEvent.timestamp, AuditEvent.agent_id)
