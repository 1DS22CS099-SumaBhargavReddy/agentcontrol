"""
AgentControl OpenTelemetry Instrumentation
Instruments agent trajectories and tool gates using GenAI semantic conventions.
"""

import time
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

try:
    from opentelemetry import trace
    from opentelemetry.trace import Status, StatusCode
    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False


class TelemetrySpan(BaseModel):
    span_id: str
    trace_id: str
    parent_span_id: str | None = None
    name: str
    operation_name: str
    start_time: str
    end_time: str | None = None
    duration_ms: float | None = None
    status: str = "ok"  # ok, error
    error_message: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    events: list[dict[str, Any]] = Field(default_factory=list)


class TelemetryManager:
    """
    Manages tracing for AgentControl with OpenTelemetry compatibility
    and in-memory buffer for real-time dashboard visualization.
    """

    SENSITIVE_KEYS = {"password", "token", "secret", "authorization", "api_key", "bearer"}

    def __init__(self, service_name: str = "agentcontrol"):
        self.service_name = service_name
        self._tracer = trace.get_tracer(service_name) if OTEL_AVAILABLE else None
        self._recent_traces: dict[str, list[TelemetrySpan]] = {}
        self._max_stored_traces = 500

    def sanitize_attributes(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Redacts sensitive values to prevent credential leakage in traces."""
        sanitized = {}
        for k, v in attrs.items():
            k_lower = k.lower()
            if any(s in k_lower for s in self.SENSITIVE_KEYS):
                sanitized[k] = "[REDACTED]"
            elif isinstance(v, dict):
                sanitized[k] = self.sanitize_attributes(v)
            elif isinstance(v, (str, int, float, bool)) or v is None:
                sanitized[k] = v
            else:
                sanitized[k] = str(v)
        return sanitized

    def record_span(self, span: TelemetrySpan) -> None:
        if span.trace_id not in self._recent_traces:
            if len(self._recent_traces) >= self._max_stored_traces:
                # Evict oldest trace
                oldest_key = next(iter(self._recent_traces))
                del self._recent_traces[oldest_key]
            self._recent_traces[span.trace_id] = []
        self._recent_traces[span.trace_id].append(span)

    def get_trace(self, trace_id: str) -> list[TelemetrySpan]:
        return self._recent_traces.get(trace_id, [])

    def list_recent_traces(self, limit: int = 50) -> list[dict[str, Any]]:
        traces_summary = []
        for tid, spans in reversed(list(self._recent_traces.items())):
            if not spans:
                continue
            root_span = next((s for s in spans if s.parent_span_id is None), spans[0])
            total_duration = sum(s.duration_ms or 0 for s in spans)
            traces_summary.append({
                "trace_id": tid,
                "root_operation": root_span.operation_name,
                "agent_id": root_span.attributes.get("gen_ai.agent.id", "unknown"),
                "status": "error" if any(s.status == "error" for s in spans) else "ok",
                "spans_count": len(spans),
                "duration_ms": round(total_duration, 2),
                "timestamp": root_span.start_time
            })
            if len(traces_summary) >= limit:
                break
        return traces_summary

    @contextmanager
    def start_span(
        self,
        name: str,
        operation_name: str,
        trace_id: str,
        span_id: str,
        parent_span_id: str | None = None,
        attributes: dict[str, Any] | None = None
    ) -> Generator[TelemetrySpan, None, None]:
        start_ts = datetime.now(timezone.utc).isoformat()
        t0 = time.perf_counter()
        clean_attrs = self.sanitize_attributes(attributes or {})
        clean_attrs["gen_ai.operation.name"] = operation_name

        span_record = TelemetrySpan(
            span_id=span_id,
            trace_id=trace_id,
            parent_span_id=parent_span_id,
            name=name,
            operation_name=operation_name,
            start_time=start_ts,
            attributes=clean_attrs
        )

        otel_span = None
        if self._tracer:
            otel_span = self._tracer.start_span(name)
            for k, v in clean_attrs.items():
                if isinstance(v, (str, bool, int, float)):
                    otel_span.set_attribute(k, v)

        try:
            yield span_record
            span_record.status = "ok"
            if otel_span:
                otel_span.set_status(Status(StatusCode.OK))
        except Exception as ex:
            span_record.status = "error"
            span_record.error_message = str(ex)
            if otel_span:
                otel_span.set_status(Status(StatusCode.ERROR, str(ex)))
                otel_span.record_exception(ex)
            raise
        finally:
            t1 = time.perf_counter()
            span_record.end_time = datetime.now(timezone.utc).isoformat()
            span_record.duration_ms = round((t1 - t0) * 1000, 2)
            self.record_span(span_record)
            if otel_span:
                otel_span.end()
