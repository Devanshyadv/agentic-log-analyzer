import pytest
from datetime import datetime, timedelta
from detection.baseline import TimeWindowFeatures, RollingBaseline
from detection.anomaly_detector import AnomalyDetector, AnomalyResult
from detection.classifier import SeverityClassifier, Severity


def _make_window(
    error_rate: float = 0.02,
    p99_latency_ms: float = 200.0,
    total_logs: int = 100,
    status_5xx: int = 2,
    unique_errors: int = 1,
) -> TimeWindowFeatures:
    now = datetime.utcnow()
    return TimeWindowFeatures(
        window_start=now,
        window_end=now + timedelta(seconds=60),
        total_logs=total_logs,
        error_count=int(total_logs * error_rate),
        error_rate=error_rate,
        warning_rate=0.05,
        avg_latency_ms=150.0,
        p99_latency_ms=p99_latency_ms,
        unique_error_types=unique_errors,
        status_5xx_count=status_5xx,
    )


class TestRollingBaseline:
    def test_z_scores_all_zero_on_empty(self):
        baseline = RollingBaseline()
        window = _make_window()
        z = baseline.get_z_scores(window)
        assert all(v == 0.0 for v in z.values())

    def test_z_scores_nonzero_after_sufficient_history(self):
        baseline = RollingBaseline()
        for _ in range(10):
            baseline.update(_make_window(error_rate=0.02))
        # Window with very high error rate should have large z-score
        anomalous = _make_window(error_rate=0.90, status_5xx=90)
        z = baseline.get_z_scores(anomalous)
        assert z["error_rate"] > 3.0

    def test_std_zero_returns_zero_not_nan(self):
        baseline = RollingBaseline()
        w = _make_window(error_rate=0.0)
        for _ in range(5):
            baseline.update(w)
        z = baseline.get_z_scores(w)
        assert z["error_rate"] == 0.0

    def test_is_normal_true_for_normal_window(self):
        baseline = RollingBaseline()
        for _ in range(10):
            baseline.update(_make_window())
        assert baseline.is_normal(_make_window())


class TestSeverityClassifier:
    def setup_method(self):
        self.clf = SeverityClassifier()

    def _result(self, score: float = 0.0):
        return AnomalyResult(
            is_anomaly=True, anomaly_score=score, features={}, z_scores={}, severity="LOW"
        )

    def test_critical_on_high_error_rate(self):
        r = self.clf.classify(self._result(), _make_window(error_rate=0.50))
        assert r.severity == Severity.CRITICAL

    def test_critical_on_5xx_count(self):
        r = self.clf.classify(self._result(), _make_window(status_5xx=150))
        assert r.severity == Severity.CRITICAL

    def test_high_on_elevated_error_rate(self):
        r = self.clf.classify(self._result(), _make_window(error_rate=0.25))
        assert r.severity == Severity.HIGH

    def test_high_on_low_if_score(self):
        r = self.clf.classify(self._result(score=-0.5), _make_window())
        assert r.severity == Severity.HIGH

    def test_high_on_latency_spike(self):
        r = self.clf.classify(self._result(), _make_window(p99_latency_ms=6000))
        assert r.severity == Severity.HIGH

    def test_medium_on_moderate_errors(self):
        r = self.clf.classify(self._result(), _make_window(error_rate=0.15))
        assert r.severity == Severity.MEDIUM

    def test_low_for_marginal_anomaly(self):
        r = self.clf.classify(self._result(score=-0.05), _make_window(error_rate=0.01))
        assert r.severity == Severity.LOW


class TestAnomalyDetector:
    def test_predict_before_fit_returns_result(self):
        detector = AnomalyDetector()
        w = _make_window()
        result = detector.predict(w)
        assert isinstance(result, AnomalyResult)
        assert isinstance(result.is_anomaly, bool)
        assert isinstance(result.z_scores, dict)
