from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from loguru import logger

from parsing.log_parser import LogParser
from parsing.extractor import extract


@dataclass
class LogEvent:
    timestamp: datetime
    level: str
    service: str
    host: str
    message: str
    raw_line: str
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "level": self.level,
            "service": self.service,
            "host": self.host,
            "message": self.message,
            "raw_line": self.raw_line,
            "metadata": self.metadata,
        }


class NormalizerPipeline:
    def __init__(self):
        self._parser = LogParser()

    def process(self, raw_line: str, source: str = "unknown") -> Optional[LogEvent]:
        raw_line = raw_line.strip()
        if not raw_line:
            return None

        parsed = self._parser.parse(raw_line)
        if parsed is None:
            logger.debug(f"Unparseable line from {source}: {raw_line[:80]}")
            return None

        metadata = extract(parsed)

        return LogEvent(
            timestamp=parsed.get("timestamp", datetime.utcnow()),
            level=parsed.get("level", "INFO").upper(),
            service=parsed.get("service", source),
            host=parsed.get("host", "unknown"),
            message=parsed.get("message", raw_line),
            raw_line=raw_line,
            metadata=metadata,
        )


if __name__ == "__main__":
    pipeline = NormalizerPipeline()
    test_lines = [
        '192.168.1.1 - - [12/May/2025:10:23:45 +0000] "GET /api/users HTTP/1.1" 500 234 "0.342"',
        '2025-05-12 10:23:45,123 ERROR    app.api:45 - Database connection failed',
        '2025-05-12T10:23:45Z WARNING default/api-pod-7f8b OOMKilled: Container killed',
    ]
    for line in test_lines:
        event = pipeline.process(line, "test")
        if event:
            print(f"[{event.level}] {event.service}: {event.message}")
            print(f"  metadata: {event.metadata}")
        else:
            print(f"UNPARSED: {line[:60]}")
