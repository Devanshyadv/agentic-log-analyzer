from dataclasses import dataclass
from enum import Enum

from config import settings
from detection.baseline import TimeWindowFeatures


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


@dataclass
class ClassificationResult:
    severity: Severity
    reasoning: str


class SeverityClassifier:
    def classify(self, anomaly_result, window: TimeWindowFeatures) -> ClassificationResult:
        score = getattr(anomaly_result, "anomaly_score", 0.0)

        if window.error_rate > settings.CRITICAL_ERROR_RATE:
            return ClassificationResult(
                Severity.CRITICAL,
                f"Error rate {window.error_rate:.1%} exceeds critical threshold {settings.CRITICAL_ERROR_RATE:.0%}",
            )
        if window.status_5xx_count > 100:
            return ClassificationResult(
                Severity.CRITICAL,
                f"5xx count {window.status_5xx_count} > 100 in window",
            )

        if window.error_rate > settings.HIGH_ERROR_RATE:
            return ClassificationResult(
                Severity.HIGH,
                f"Error rate {window.error_rate:.1%} exceeds high threshold {settings.HIGH_ERROR_RATE:.0%}",
            )
        if score < -0.4:
            return ClassificationResult(
                Severity.HIGH,
                f"Isolation Forest score {score:.3f} indicates strong anomaly",
            )
        if window.p99_latency_ms > 5000:
            return ClassificationResult(
                Severity.HIGH,
                f"P99 latency {window.p99_latency_ms:.0f}ms > 5000ms",
            )

        if window.error_rate > settings.MEDIUM_ERROR_RATE:
            return ClassificationResult(
                Severity.MEDIUM,
                f"Error rate {window.error_rate:.1%} exceeds medium threshold {settings.MEDIUM_ERROR_RATE:.0%}",
            )
        if score < -0.2:
            return ClassificationResult(
                Severity.MEDIUM,
                f"Isolation Forest score {score:.3f} suggests moderate anomaly",
            )

        return ClassificationResult(
            Severity.LOW,
            "Anomaly detected but all metrics are near baseline",
        )
