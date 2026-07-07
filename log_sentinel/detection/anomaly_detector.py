from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict
import numpy as np
from sklearn.ensemble import IsolationForest
import joblib
from loguru import logger

from config import settings
from detection.baseline import TimeWindowFeatures, RollingBaseline
from ingestion.normalizer import LogEvent


@dataclass
class AnomalyResult:
    is_anomaly: bool
    anomaly_score: float
    features: dict
    z_scores: dict
    severity: str = "LOW"


class AnomalyDetector:
    _MODEL_FILENAME = "isolation_forest.joblib"

    def __init__(self):
        self._model = IsolationForest(
            contamination=settings.ANOMALY_CONTAMINATION,
            n_estimators=100,
            random_state=42,
        )
        self.baseline = RollingBaseline()
        self._fitted = False
        self._model_path = Path(settings.FAISS_INDEX_PATH).parent / self._MODEL_FILENAME

    # ------------------------------------------------------------------
    # Feature engineering
    # ------------------------------------------------------------------

    def compute_window_features(
        self,
        events: List[LogEvent],
        window_start: datetime,
        window_end: datetime,
    ) -> TimeWindowFeatures:
        total = len(events)
        errors = sum(1 for e in events if e.level in ("ERROR", "CRITICAL"))
        warnings = sum(1 for e in events if e.level == "WARNING")
        latencies = [
            e.metadata.get("latency_ms")
            for e in events
            if e.metadata.get("latency_ms") is not None
        ]
        avg_lat = float(np.mean(latencies)) if latencies else 0.0
        p99_lat = float(np.percentile(latencies, 99)) if latencies else 0.0
        error_types = {
            e.metadata.get("error_type")
            for e in events
            if e.metadata.get("error_type")
        }
        status_5xx = sum(
            1 for e in events
            if e.metadata.get("status_code") and 500 <= e.metadata["status_code"] < 600
        )
        return TimeWindowFeatures(
            window_start=window_start,
            window_end=window_end,
            total_logs=total,
            error_count=errors,
            error_rate=errors / total if total > 0 else 0.0,
            warning_rate=warnings / total if total > 0 else 0.0,
            avg_latency_ms=avg_lat,
            p99_latency_ms=p99_lat,
            unique_error_types=len(error_types),
            status_5xx_count=status_5xx,
        )

    def _build_windows(self, log_events: List[LogEvent]) -> List[TimeWindowFeatures]:
        if not log_events:
            return []
        from collections import defaultdict
        events_sorted = sorted(log_events, key=lambda e: e.timestamp)
        step = settings.WINDOW_SIZE_SECONDS
        t_start = events_sorted[0].timestamp.timestamp()

        # O(n) single pass: assign each event to its bucket index
        buckets: dict = defaultdict(list)
        for e in events_sorted:
            idx = int((e.timestamp.timestamp() - t_start) / step)
            buckets[idx].append(e)

        windows = []
        for idx in sorted(buckets.keys()):
            t = t_start + idx * step
            wstart = datetime.utcfromtimestamp(t)
            wend = datetime.utcfromtimestamp(t + step)
            windows.append(self.compute_window_features(buckets[idx], wstart, wend))
        return windows

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def fit(self, log_events: List[LogEvent]):
        windows = self._build_windows(log_events)
        if not windows:
            logger.warning("No windows built — cannot fit detector")
            return
        X = np.array([w.to_vector() for w in windows])
        self._model.fit(X)
        self._fitted = True
        for w in windows:
            self.baseline.update(w)
        self._model_path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self._model, self._model_path)
        logger.info(
            f"Fitted on {len(windows)} windows, contamination={settings.ANOMALY_CONTAMINATION}"
        )

    def load_or_fit(self, log_events: Optional[List[LogEvent]] = None):
        if self._model_path.exists():
            try:
                self._model = joblib.load(self._model_path)
                self._fitted = True
                logger.info(f"Loaded existing model from {self._model_path}")
                return
            except Exception as e:
                logger.warning(f"Failed to load model ({e}), will refit if data provided")
        if log_events:
            self.fit(log_events)
        else:
            logger.warning("No model on disk and no log events — detector will use z-scores only")

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    def predict(self, window: TimeWindowFeatures) -> AnomalyResult:
        z_scores = self.baseline.get_z_scores(window)
        self.baseline.update(window)
        features_dict = dict(zip(TimeWindowFeatures.feature_names(), window.to_vector()))
        any_z_anomaly = any(abs(z) > 3.0 for z in z_scores.values())

        if not self._fitted:
            return AnomalyResult(
                is_anomaly=any_z_anomaly,
                anomaly_score=0.0,
                features=features_dict,
                z_scores=z_scores,
                severity="MEDIUM" if any_z_anomaly else "LOW",
            )

        X = np.array([window.to_vector()])
        if_pred = int(self._model.predict(X)[0])       # -1 = anomaly
        if_score = float(self._model.score_samples(X)[0])
        is_anomaly = (if_pred == -1) or any_z_anomaly

        return AnomalyResult(
            is_anomaly=is_anomaly,
            anomaly_score=if_score,
            features=features_dict,
            z_scores=z_scores,
        )


# ------------------------------------------------------------------
# CLI: python -m detection.anomaly_detector fit ./data/sample_logs/
# ------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    from pathlib import Path
    from ingestion.normalizer import NormalizerPipeline

    if len(sys.argv) < 3 or sys.argv[1] != "fit":
        print("Usage: python -m detection.anomaly_detector fit <log_dir>")
        sys.exit(1)

    log_dir = Path(sys.argv[2])
    normalizer = NormalizerPipeline()
    events: List[LogEvent] = []
    for log_file in sorted(log_dir.glob("*.log")):
        with open(log_file, "r", errors="replace") as f:
            for line in f:
                ev = normalizer.process(line.strip(), log_file.stem)
                if ev:
                    events.append(ev)

    if not events:
        print(f"No parseable events found in {log_dir}")
        sys.exit(1)

    print(f"Loaded {len(events)} log events from {log_dir}")
    detector = AnomalyDetector()
    detector.fit(events)
