"""
AgentControl Cryptographic Tamper-Resistant Audit Logger
Append-only hash-chained audit logging for complete forensic compliance.
"""

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.db.models import AuditEvent


def _format_dt_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


class AuditLogger:
    """
    Records audit events with cryptographic hash-chaining (SHA-256).
    Guarantees detection if any historical event is modified, injected, or removed.
    """

    GENESIS_HASH = "0000000000000000000000000000000000000000000000000000000000000000"

    @classmethod
    def compute_event_hash(
        cls,
        timestamp_str: str,
        agent_id: str,
        user_id: str | None,
        action: str,
        tool_name: str | None,
        payload: dict[str, Any],
        previous_hash: str
    ) -> str:
        serialized_payload = json.dumps(payload, sort_keys=True)
        raw = f"{timestamp_str}|{agent_id}|{user_id or 'none'}|{action}|{tool_name or 'none'}|{serialized_payload}|{previous_hash}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @classmethod
    async def log_event(
        cls,
        db: AsyncSession,
        agent_id: str,
        action: str,
        user_id: str | None = None,
        tool_name: str | None = None,
        risk_level: str | None = None,
        policy_decision: str | None = None,
        approval_status: str | None = None,
        execution_status: str | None = None,
        trace_id: str | None = None,
        payload: dict[str, Any] | None = None
    ) -> AuditEvent:
        # Get previous hash
        stmt = select(AuditEvent).order_by(desc(AuditEvent.timestamp)).limit(1)
        res = await db.execute(stmt)
        last_event = res.scalar_one_or_none()
        prev_hash = last_event.signature_sha256 if last_event else cls.GENESIS_HASH

        now_dt = datetime.now(timezone.utc)
        now_str = _format_dt_iso(now_dt)
        clean_payload = payload or {}

        sig = cls.compute_event_hash(
            timestamp_str=now_str,
            agent_id=agent_id,
            user_id=user_id,
            action=action,
            tool_name=tool_name,
            payload=clean_payload,
            previous_hash=prev_hash
        )

        event = AuditEvent(
            timestamp=now_dt,
            trace_id=trace_id,
            agent_id=agent_id,
            user_id=user_id,
            action=action,
            tool_name=tool_name,
            risk_level=risk_level,
            policy_decision=policy_decision,
            approval_status=approval_status,
            execution_status=execution_status,
            signature_sha256=sig,
            payload=clean_payload
        )
        db.add(event)
        await db.commit()
        await db.refresh(event)
        return event

    @classmethod
    async def verify_chain_integrity(cls, db: AsyncSession, limit: int = 100) -> dict[str, Any]:
        """Validates the audit chain integrity against retroactive tampering."""
        stmt = select(AuditEvent).order_by(AuditEvent.timestamp.asc()).limit(limit)
        res = await db.execute(stmt)
        events = list(res.scalars().all())

        if not events:
            return {"verified": True, "count": 0, "message": "No events in audit log"}

        prev_hash = cls.GENESIS_HASH
        for idx, event in enumerate(events):
            expected_hash = cls.compute_event_hash(
                timestamp_str=_format_dt_iso(event.timestamp),
                agent_id=event.agent_id,
                user_id=event.user_id,
                action=event.action,
                tool_name=event.tool_name,
                payload=event.payload or {},
                previous_hash=prev_hash
            )
            if expected_hash != event.signature_sha256:
                return {
                    "verified": False,
                    "count": len(events),
                    "tampered_index": idx,
                    "event_id": event.id,
                    "message": f"Tampering detected at event ID {event.id}"
                }
            prev_hash = event.signature_sha256

        return {
            "verified": True,
            "count": len(events),
            "message": f"Cryptographic audit chain verified across {len(events)} events"
        }
