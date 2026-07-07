from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List
import numpy as np

from config import settings


@dataclass
class TimeWindowFeatures:
    window_start: datetime
    window_end: datetime
    total_logs: int
    error_count: int
    error_rate: float
    warning_rate: float
    avg_latency_ms: float
    p99_latency_ms: float
    unique_error_types: int
    status_5xx_count: int

    def to_vector(self) -> List[float]:
        return [
            float(self.total_logs),
            float(self.error_count),
            self.error_rate,
            self.warning_rate,
            self.avg_latency_ms,
            self.p99_latency_ms,
            float(self.unique_error_types),
            float(self.status_5xx_count),
        ]

    @staticmethod
    def feature_names() -> List[str]:
        return [
            "total_logs", "error_count", "error_rate", "warning_rate",
            "avg_latency_ms", "p99_latency_ms", "unique_error_types", "status_5xx_count",
        ]


class RollingBaseline:
    def __init__(self):
        self._window: deque = deque(maxlen=settings.BASELINE_WINDOW_MINUTES)

    def update(self, window: TimeWindowFeatures):
        self._window.append(window)

    def get_z_scores(self, window: TimeWindowFeatures) -> Dict[str, float]:
        names = TimeWindowFeatures.feature_names()
        if len(self._window) < 2:
            return {name: 0.0 for name in names}

        matrix = np.array([w.to_vector() for w in self._window])
        means = matrix.mean(axis=0)
        stds = matrix.std(axis=0)
        current = np.array(window.to_vector())

        z_scores = {}
        for i, name in enumerate(names):
            if stds[i] < 1e-10:
                # Zero variance in history: deviation from the constant mean is extreme
                z_scores[name] = 0.0 if abs(current[i] - means[i]) < 1e-10 else 10.0
            else:
                z_scores[name] = float((current[i] - means[i]) / stds[i])
        return z_scores

    def is_normal(self, window: TimeWindowFeatures) -> bool:
        return all(abs(z) < 3.0 for z in self.get_z_scores(window).values())
