"""Structured, zero-dependency application logging with automatic sensitive data redaction,
context propagation, and latency tracking across the payment recovery lifecycle.
"""

from __future__ import annotations

import contextvars
import json
import logging
import re
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

# --- Context Propagation ---

_LOG_CONTEXT: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar(
    "log_context", default={}
)


@contextmanager
def log_context(**kwargs: Any) -> Iterator[None]:
    """Context manager to bind contextual fields (e.g. case_id, order_id) to all log records in this context."""
    current = _LOG_CONTEXT.get().copy()
    current.update({k: v for k, v in kwargs.items() if v is not None})
    token = _LOG_CONTEXT.set(current)
    try:
        yield
    finally:
        _LOG_CONTEXT.reset(token)


def get_current_context() -> dict[str, Any]:
    """Retrieve current context variables."""
    return _LOG_CONTEXT.get().copy()


# --- Sensitive Data & Secret Sanitization ---

# Sensitive field name stems (case-insensitive)
_SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "secret_key",
        "private_key",
        "access_token",
        "auth_token",
        "token",
        "secret",
        "password",
        "passwd",
        "pan",
        "card_number",
        "card_num",
        "cvv",
        "cvc",
        "authorization",
    }
)

# Regex patterns for sensitive values
_CARD_PAN_REGEX = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
_API_KEY_REGEX = re.compile(
    r"\b(?:sk-ant-[a-zA-Z0-9_\-]{10,}|gsk_[a-zA-Z0-9]{10,}|rzp_(?:test|live)_[a-zA-Z0-9]{10,}|Bearer\s+[a-zA-Z0-9_\-\.]{15,})\b",
    re.IGNORECASE,
)
_CVV_REGEX = re.compile(r"(?i)\b(?:cvv|cvc)\s*[:=]\s*['\"]?(\d{3,4})['\"]?")


def redact_string(text: str) -> str:
    """Scrub raw card numbers, API keys, and sensitive tokens from free-form text."""
    if not text or not isinstance(text, str):
        return text

    # Redact specific API keys / Bearer tokens
    text = _API_KEY_REGEX.sub("[REDACTED_SECRET]", text)

    # Redact CVV references
    text = _CVV_REGEX.sub("cvv: [REDACTED_CVV]", text)

    # Redact card PANs (preserve length indicator if clean)
    def _mask_pan(match: re.Match) -> str:
        s = match.group(0)
        digits = re.sub(r"\D", "", s)
        if 13 <= len(digits) <= 19:
            # Mask all but last 4 digits
            return f"****-****-****-{digits[-4:]}"
        return s

    text = _CARD_PAN_REGEX.sub(_mask_pan, text)
    return text


def sanitize_data(obj: Any, parent_key: str | None = None) -> Any:
    """Recursively scrub sensitive keys and values from data structures."""
    if obj is None:
        return None

    # If the key name itself indicates sensitive content, redact immediately
    if parent_key:
        key_lower = parent_key.lower()
        if (
            key_lower in _SENSITIVE_KEYS
            or any(sens in key_lower for sens in ("api_key", "secret_key", "password", "passwd", "access_token", "auth_token", "card_number", "cvv", "cvc"))
        ):
            if isinstance(obj, str) and len(obj) >= 4:
                return "[REDACTED]"
            return "[REDACTED]"

    if isinstance(obj, dict):
        return {k: sanitize_data(v, parent_key=str(k)) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple, set)):
        sanitized = [sanitize_data(item, parent_key=parent_key) for item in obj]
        return type(obj)(sanitized) if not isinstance(obj, set) else set(sanitized)
    elif isinstance(obj, str):
        return redact_string(obj)
    elif hasattr(obj, "model_dump") and callable(obj.model_dump):
        # Pydantic model
        return sanitize_data(obj.model_dump(mode="json"), parent_key=parent_key)
    elif hasattr(obj, "__dict__"):
        return sanitize_data(obj.__dict__, parent_key=parent_key)
    return obj


# --- Formatter & Handler ---

class StructuredJsonFormatter(logging.Formatter):
    """Formats log records as structured JSON with standardized fields."""

    def format(self, record: logging.LogRecord) -> str:
        # Base metadata
        log_entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": getattr(record, "event", record.getMessage()),
        }

        # Latency tracking (in milliseconds)
        latency_ms = getattr(record, "latency_ms", None)
        if latency_ms is not None:
            log_entry["latency_ms"] = round(float(latency_ms), 2)

        # Context from contextvars + record attributes
        context = get_current_context()
        record_context = getattr(record, "context", {})
        if record_context and isinstance(record_context, dict):
            context.update(record_context)

        # Promote case_id and order_id to top-level if present in context
        for top_key in ("case_id", "order_id", "attempt_no"):
            if top_key in context:
                log_entry[top_key] = context[top_key]

        if context:
            log_entry["context"] = sanitize_data(context)

        # Structured payload data
        data = getattr(record, "data", None)
        if data is not None:
            log_entry["data"] = sanitize_data(data)

        # Exception / Error info
        if record.exc_info:
            log_entry["error"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else "UnknownError",
                "message": redact_string(str(record.exc_info[1])),
                "traceback": redact_string(self.formatException(record.exc_info)),
            }
        elif getattr(record, "error_detail", None):
            log_entry["error"] = sanitize_data(record.error_detail)

        return json.dumps(log_entry)


class StructuredLogger(logging.Logger):
    """Logger supporting structured event logging with extra data, latency, and context."""

    def log_event(
        self,
        event: str,
        level: int | str = logging.INFO,
        *,
        latency_ms: float | None = None,
        data: dict[str, Any] | None = None,
        error_detail: Any = None,
        exc_info: bool = False,
        **extra_kwargs: Any,
    ) -> None:
        """Emit a structured event record."""
        if isinstance(level, str):
            level = getattr(logging, level.upper(), logging.INFO)

        payload = data or {}
        if extra_kwargs:
            payload = {**payload, **extra_kwargs}

        extra = {
            "event": event,
            "latency_ms": latency_ms,
            "data": payload if payload else None,
            "error_detail": error_detail,
        }

        self.log(level, event, extra=extra, exc_info=exc_info)


logging.setLoggerClass(StructuredLogger)


def get_logger(name: str = "agent") -> StructuredLogger:
    """Obtain a structured logger instance."""
    logger = logging.getLogger(name)
    if not isinstance(logger, StructuredLogger):
        # In case logger class wasn't set when logger was created
        logger.__class__ = StructuredLogger
    return logger  # type: ignore[return-value]


def configure_logging(
    level: int | str = logging.INFO,
    stream: Any = sys.stdout,
    json_format: bool = True,
) -> None:
    """Configure root or package logging handler."""
    root = logging.getLogger("agent")
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)
    root.setLevel(level)

    # Avoid duplicate handlers
    root.handlers.clear()

    handler = logging.StreamHandler(stream)
    if json_format:
        handler.setFormatter(StructuredJsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("[%(asctime)s] %(levelname)s %(name)s: %(message)s")
        )
    root.addHandler(handler)


@contextmanager
def log_timer(
    logger: StructuredLogger | logging.Logger,
    event_prefix: str,
    level: int | str = logging.INFO,
    data: dict[str, Any] | None = None,
) -> Iterator[dict[str, Any]]:
    """Measure latency and log start and completion events.
    
    Yields a mutable dictionary that callers can populate with extra result data.
    """
    start_time = time.perf_counter()
    result_data: dict[str, Any] = dict(data or {})

    # Log start event
    if hasattr(logger, "log_event"):
        logger.log_event(f"{event_prefix}.started", level=level, data=result_data)
    else:
        logger.log(
            getattr(logging, level.upper()) if isinstance(level, str) else level,
            f"{event_prefix}.started",
            extra={"event": f"{event_prefix}.started", "data": result_data},
        )

    try:
        yield result_data
    except Exception as exc:
        latency_ms = (time.perf_counter() - start_time) * 1000
        if hasattr(logger, "log_event"):
            logger.log_event(
                f"{event_prefix}.failed",
                level=logging.ERROR,
                latency_ms=latency_ms,
                data=result_data,
                error_detail={"type": type(exc).__name__, "message": str(exc)},
                exc_info=True,
            )
        raise
    else:
        latency_ms = (time.perf_counter() - start_time) * 1000
        if hasattr(logger, "log_event"):
            logger.log_event(
                f"{event_prefix}.completed",
                level=level,
                latency_ms=latency_ms,
                data=result_data,
            )
        else:
            logger.log(
                getattr(logging, level.upper()) if isinstance(level, str) else level,
                f"{event_prefix}.completed",
                extra={
                    "event": f"{event_prefix}.completed",
                    "latency_ms": latency_ms,
                    "data": result_data,
                },
            )
