import re
from datetime import datetime
from typing import Optional
from dateutil import parser as dateutil_parser
from loguru import logger


NGINX_ACCESS_RE = re.compile(
    r'^(?P<ip>\S+) - - \[(?P<time>[^\]]+)\] '
    r'"(?P<method>\S+) (?P<path>\S+) (?P<protocol>[^"]+)" '
    r'(?P<status>\d+) (?P<bytes>\d+)'
    r'(?:\s+"(?P<latency>[^"]*)")?'
    r'(?:\s+"(?P<referrer>[^"]*)")?'
    r'(?:\s+"(?P<ua>[^"]*)")?$'
)

NGINX_ERROR_RE = re.compile(
    r'^(?P<timestamp>\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}) '
    r'\[(?P<level>\w+)\] '
    r'(?P<pid>\d+)#(?P<tid>\d+): '
    r'(?:\*(?P<connid>\d+) )?'
    r'(?P<message>.+)$'
)

PYTHON_APP_RE = re.compile(
    r'^(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}[,\.]\d+)\s+'
    r'(?P<level>DEBUG|INFO|WARNING|ERROR|CRITICAL)\s+'
    r'(?P<module>[^:]+):(?P<line>\d+) - '
    r'(?P<message>.+)$'
)

K8S_EVENT_RE = re.compile(
    r'^(?P<timestamp>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)\s+'
    r'(?P<level>\w+)\s+'
    r'(?P<namespace>[^/\s]+)/(?P<pod>\S+)\s+'
    r'(?P<event_type>[^:]+):\s+'
    r'(?P<message>.+)$'
)

SYSLOG_RE = re.compile(
    r'^(?P<month>\w{3})\s+(?P<day>\d{1,2})\s+(?P<time>\d{2}:\d{2}:\d{2})\s+'
    r'(?P<host>\S+)\s+'
    r'(?P<program>[^\[:\s]+)(?:\[(?P<pid>\d+)\])?: '
    r'(?P<message>.+)$'
)

_SYSLOG_MONTHS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}

_NGINX_LEVEL_MAP = {
    "debug": "DEBUG", "info": "INFO", "notice": "INFO",
    "warn": "WARNING", "error": "ERROR", "crit": "CRITICAL",
    "alert": "CRITICAL", "emerg": "CRITICAL",
}


class LogParser:
    def detect_format(self, raw_line: str) -> str:
        if NGINX_ACCESS_RE.match(raw_line):
            return "nginx_access"
        if NGINX_ERROR_RE.match(raw_line):
            return "nginx_error"
        if PYTHON_APP_RE.match(raw_line):
            return "python_app"
        if K8S_EVENT_RE.match(raw_line):
            return "k8s_event"
        if SYSLOG_RE.match(raw_line):
            return "syslog"
        return "unknown"

    def parse(self, raw_line: str) -> Optional[dict]:
        raw_line = raw_line.strip()
        if not raw_line:
            return None
        fmt = self.detect_format(raw_line)
        handlers = {
            "nginx_access": self._parse_nginx_access,
            "nginx_error": self._parse_nginx_error,
            "python_app": self._parse_python_app,
            "k8s_event": self._parse_k8s_event,
            "syslog": self._parse_syslog,
        }
        handler = handlers.get(fmt)
        return handler(raw_line) if handler else None

    def _parse_nginx_access(self, raw_line: str) -> Optional[dict]:
        m = NGINX_ACCESS_RE.match(raw_line)
        if not m:
            return None
        try:
            ts = dateutil_parser.parse(m.group("time"), dayfirst=True)
        except Exception:
            ts = datetime.utcnow()
        status = int(m.group("status"))
        level = "ERROR" if status >= 500 else ("WARNING" if status >= 400 else "INFO")
        latency_raw = m.group("latency")
        latency_ms = float(latency_raw) * 1000 if latency_raw else None
        return {
            "format": "nginx_access",
            "timestamp": ts,
            "level": level,
            "service": "nginx",
            "host": m.group("ip"),
            "message": f'{m.group("method")} {m.group("path")} {status}',
            "ip": m.group("ip"),
            "method": m.group("method"),
            "path": m.group("path"),
            "status_code": status,
            "response_bytes": int(m.group("bytes")),
            "latency_ms": latency_ms,
        }

    def _parse_nginx_error(self, raw_line: str) -> Optional[dict]:
        m = NGINX_ERROR_RE.match(raw_line)
        if not m:
            return None
        try:
            ts = datetime.strptime(m.group("timestamp"), "%Y/%m/%d %H:%M:%S")
        except Exception:
            ts = datetime.utcnow()
        return {
            "format": "nginx_error",
            "timestamp": ts,
            "level": _NGINX_LEVEL_MAP.get(m.group("level").lower(), "ERROR"),
            "service": "nginx",
            "host": "localhost",
            "message": m.group("message"),
        }

    def _parse_python_app(self, raw_line: str) -> Optional[dict]:
        m = PYTHON_APP_RE.match(raw_line)
        if not m:
            return None
        ts_str = m.group("timestamp").replace(",", ".")
        try:
            ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S.%f")
        except Exception:
            try:
                ts = dateutil_parser.parse(ts_str)
            except Exception:
                ts = datetime.utcnow()
        module = m.group("module").strip()
        service = module.split(".")[0] if module else "python_app"
        return {
            "format": "python_app",
            "timestamp": ts,
            "level": m.group("level").upper(),
            "service": service,
            "host": "localhost",
            "message": m.group("message"),
            "module": module,
            "line": int(m.group("line")),
        }

    def _parse_k8s_event(self, raw_line: str) -> Optional[dict]:
        m = K8S_EVENT_RE.match(raw_line)
        if not m:
            return None
        try:
            ts = datetime.strptime(m.group("timestamp"), "%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            ts = datetime.utcnow()
        level_map = {"info": "INFO", "warning": "WARNING", "error": "ERROR", "normal": "INFO"}
        level = level_map.get(m.group("level").lower(), "INFO")
        return {
            "format": "k8s_event",
            "timestamp": ts,
            "level": level,
            "service": "kubernetes",
            "host": m.group("namespace"),
            "message": f"{m.group('event_type')}: {m.group('message')}",
            "namespace": m.group("namespace"),
            "pod": m.group("pod"),
            "event_type": m.group("event_type"),
        }

    def _parse_syslog(self, raw_line: str) -> Optional[dict]:
        m = SYSLOG_RE.match(raw_line)
        if not m:
            return None
        try:
            month = _SYSLOG_MONTHS.get(m.group("month"), 1)
            day = int(m.group("day"))
            h, mi, s = (int(x) for x in m.group("time").split(":"))
            ts = datetime(datetime.utcnow().year, month, day, h, mi, s)
        except Exception:
            ts = datetime.utcnow()
        return {
            "format": "syslog",
            "timestamp": ts,
            "level": "INFO",
            "service": m.group("program").strip(),
            "host": m.group("host"),
            "message": m.group("message"),
        }
