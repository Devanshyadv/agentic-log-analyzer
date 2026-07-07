import re
from typing import Optional


_IP_RE = re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b')
_LATENCY_LABEL_RE = re.compile(
    r'(?:latency|duration|took|elapsed|response_time)[^\d]*(\d+\.?\d*)\s*'
    r'(?P<unit>ms|milliseconds?|s|seconds?)?',
    re.IGNORECASE,
)
_LATENCY_MS_RE = re.compile(r'(\d+\.?\d*)\s*ms', re.IGNORECASE)
_ERROR_TYPE_RE = re.compile(
    r'\b([A-Z][a-zA-Z]*(?:Error|Exception|Fault|Failure|Timeout|Warning))\b'
)
_POD_RE = re.compile(r'pod["\s:/]+([a-zA-Z0-9][-a-zA-Z0-9.]*)')

_STACK_TRACE_MARKERS = (
    "Traceback (most recent call last)",
    "  File ",
    "Exception in thread",
    "java.lang.",
    "at com.",
    "at org.",
    "at net.",
)


def extract(parsed_fields: dict) -> dict:
    message = parsed_fields.get("message", "")
    return {
        "ips": extract_ip(message),
        "status_code": parsed_fields.get("status_code") or extract_status_code(message),
        "latency_ms": parsed_fields.get("latency_ms") or extract_latency(message),
        "is_stack_trace": extract_stack_trace(message),
        "error_type": extract_error_type(message),
        "pod_name": parsed_fields.get("pod") or extract_pod_name(message),
        "service": parsed_fields.get("service", "unknown"),
        "format": parsed_fields.get("format", "unknown"),
    }


def extract_ip(message: str) -> list:
    return _IP_RE.findall(message)


def extract_status_code(message: str) -> Optional[int]:
    m = re.search(r'\b([1-5]\d{2})\b', message)
    return int(m.group(1)) if m else None


def extract_latency(message: str) -> Optional[float]:
    m = _LATENCY_LABEL_RE.search(message)
    if m:
        val = float(m.group(1))
        unit = (m.group("unit") or "").lower()
        if unit.startswith("ms") or unit.startswith("milli"):
            return val
        if unit.startswith("s"):
            return val * 1000
        return val
    m = _LATENCY_MS_RE.search(message)
    return float(m.group(1)) if m else None


def extract_stack_trace(message: str) -> bool:
    return any(marker in message for marker in _STACK_TRACE_MARKERS)


def extract_error_type(message: str) -> Optional[str]:
    m = _ERROR_TYPE_RE.search(message)
    return m.group(1) if m else None


def extract_pod_name(message: str) -> Optional[str]:
    m = _POD_RE.search(message, re.IGNORECASE)
    return m.group(1) if m else None
