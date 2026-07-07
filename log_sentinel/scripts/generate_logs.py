"""Generate realistic sample log data for LogSentinel development and testing."""

import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

BASE_DIR = Path(__file__).resolve().parent.parent

USER_IPS = [f"192.168.{random.randint(1, 5)}.{i}" for i in range(1, 51)]
ENDPOINTS = [
    "/api/users", "/api/orders", "/api/products", "/api/auth/login",
    "/api/dashboard", "/api/search", "/static/css/main.css",
    "/health", "/metrics", "/api/cart", "/api/checkout",
]
METHODS = ["GET"] * 6 + ["POST"] * 3 + ["PUT", "DELETE"]
MODULES = ["app.api", "app.db", "app.cache", "app.auth", "app.worker", "app.tasks"]
K8S_NAMESPACES = ["default", "production", "staging"]
K8S_PODS = ["api-pod-7f8b9", "worker-pod-3k2m1", "db-pod-9x1c4", "cache-pod-2r5t8"]


def _nginx_line(ts: datetime, force_5xx: bool = False, latency_ms: float = None) -> str:
    ip = random.choice(USER_IPS)
    method = random.choice(METHODS)
    path = random.choice(ENDPOINTS)
    if force_5xx:
        status = random.choice([500, 502, 503, 500, 500, 500])
    else:
        r = random.random()
        if r < 0.90:
            status = random.choice([200, 200, 200, 304, 200, 201])
        elif r < 0.96:
            status = random.choice([404, 404, 403, 401])
        else:
            status = random.choice([500, 502, 503])
    if latency_ms is None:
        latency_ms = max(5.0, float(np.random.lognormal(np.log(150), 0.35)))
    size = random.randint(200, 8000)
    ts_str = ts.strftime("%d/%b/%Y:%H:%M:%S +0000")
    return f'{ip} - - [{ts_str}] "{method} {path} HTTP/1.1" {status} {size} "{latency_ms/1000:.3f}"'


def _python_line(ts: datetime, level: str = "INFO", msg: str = None) -> str:
    module = random.choice(MODULES)
    lineno = random.randint(15, 250)
    if msg is None:
        _msgs = {
            "INFO": [
                "User login successful uid={}".format(random.randint(1000, 9999)),
                "Request processed in {}ms".format(random.randint(10, 300)),
                "Cache hit for key user:{}".format(random.randint(1, 500)),
                "Task queued: send_email",
                "Order {} placed successfully".format(random.randint(10000, 99999)),
            ],
            "WARNING": [
                "Slow query detected ({}ms): SELECT * FROM orders JOIN users".format(
                    random.randint(800, 3000)
                ),
                "Connection pool at {}% capacity".format(random.randint(70, 90)),
                "Cache miss rate elevated: {:.1f}%".format(random.uniform(30, 60)),
                "Retry attempt {} for external API call".format(random.randint(1, 3)),
            ],
            "ERROR": [
                "psycopg2.OperationalError: FATAL: remaining connection slots are reserved",
                "redis.exceptions.ConnectionError: Connection refused 127.0.0.1:6379",
                "requests.exceptions.Timeout: HTTPSConnectionPool read timed out",
                "AttributeError: 'NoneType' object has no attribute 'user_id'",
                "KeyError: 'access_token' in JWT decode",
            ],
        }
        msg = random.choice(_msgs.get(level, ["Event processed"]))
    ts_str = ts.strftime("%Y-%m-%d %H:%M:%S") + f",{ts.microsecond // 1000:03d}"
    return f"{ts_str} {level:<8} {module}:{lineno} - {msg}"


def _k8s_line(ts: datetime, event_type: str = "Normal") -> str:
    ns = random.choice(K8S_NAMESPACES)
    pod = random.choice(K8S_PODS)
    ts_str = ts.strftime("%Y-%m-%dT%H:%M:%SZ")
    if event_type == "Normal":
        evt = random.choice(["Scheduled", "Pulled", "Created", "Started"])
        msg = random.choice([
            f"Successfully assigned {ns}/{pod} to node-1",
            f"Container image pulled",
            f"Started container api",
        ])
    else:
        evt = random.choice(["BackOff", "OOMKilling", "Failed", "Unhealthy"])
        msg = random.choice([
            "Back-off restarting failed container",
            "OOMKilled: Container exceeded memory limit",
            "Liveness probe failed: HTTP probe failed connection refused",
        ])
    return f"{ts_str} {event_type} {ns}/{pod} {evt}: {msg}"


class LogGenerator:
    def __init__(self, output_dir: str = None):
        self.output_dir = Path(output_dir) if output_dir else BASE_DIR / "data" / "sample_logs"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_normal_logs(
        self,
        output_file: str = None,
        duration_hours: float = 1.0,
        logs_per_minute: int = 200,
    ):
        nginx_path = self.output_dir / (output_file or "nginx_access.log")
        app_path = self.output_dir / "app_errors.log"
        k8s_path = self.output_dir / "k8s_events.log"

        start = datetime(2025, 5, 12, 8, 0, 0)
        total_minutes = int(duration_hours * 60)

        print(f"Generating {total_minutes} minutes of normal logs -> {self.output_dir}")

        with open(nginx_path, "w") as nf, open(app_path, "w") as af, open(k8s_path, "w") as kf:
            for minute in range(total_minutes):
                ts_base = start + timedelta(minutes=minute)
                for i in range(logs_per_minute):
                    ts = ts_base + timedelta(seconds=random.uniform(0, 59))
                    nf.write(_nginx_line(ts) + "\n")

                # Python app: ~10 logs/minute with ~1% error rate
                for i in range(10):
                    ts = ts_base + timedelta(seconds=random.uniform(0, 59))
                    r = random.random()
                    level = "ERROR" if r < 0.01 else ("WARNING" if r < 0.05 else "INFO")
                    af.write(_python_line(ts, level) + "\n")

                # K8s: a few events per minute
                if minute % 5 == 0:
                    ts = ts_base + timedelta(seconds=random.uniform(0, 59))
                    kf.write(_k8s_line(ts, "Normal") + "\n")

        print(f"Normal logs written: nginx={nginx_path}, app={app_path}, k8s={k8s_path}")

    def generate_anomaly_window(
        self,
        output_file: str = "nginx_access.log",
        anomaly_type: str = "error_storm",
        duration_minutes: int = 10,
        start_offset_hours: float = 1.0,
    ):
        nginx_path = self.output_dir / output_file
        app_path = self.output_dir / "app_errors.log"
        k8s_path = self.output_dir / "k8s_events.log"

        start = datetime(2025, 5, 12, 8, 0, 0) + timedelta(hours=start_offset_hours)
        print(f"Generating anomaly window: type={anomaly_type}, duration={duration_minutes}min")

        with open(nginx_path, "a") as nf, open(app_path, "a") as af, open(k8s_path, "a") as kf:
            for minute in range(duration_minutes):
                ts_base = start + timedelta(minutes=minute)
                progress = minute / duration_minutes

                if anomaly_type == "error_storm":
                    # Error rate jumps from 2% to 45%
                    for i in range(200):
                        ts = ts_base + timedelta(seconds=random.uniform(0, 59))
                        force_5xx = random.random() < 0.45
                        nf.write(_nginx_line(ts, force_5xx=force_5xx) + "\n")
                    for i in range(30):
                        ts = ts_base + timedelta(seconds=random.uniform(0, 59))
                        af.write(_python_line(ts, "ERROR") + "\n")

                elif anomaly_type == "latency_spike":
                    # P99 goes from 200ms to 8000ms
                    spike_lat = 2000 + 6000 * progress
                    for i in range(200):
                        ts = ts_base + timedelta(seconds=random.uniform(0, 59))
                        latency = max(100, float(np.random.lognormal(np.log(spike_lat), 0.4)))
                        nf.write(_nginx_line(ts, latency_ms=latency) + "\n")
                    af.write(_python_line(
                        ts_base, "WARNING",
                        f"Slow query detected ({int(spike_lat)}ms): SELECT orders JOIN users ORDER BY created_at"
                    ) + "\n")

                elif anomaly_type == "memory_leak":
                    # Gradual memory warnings → OOMKilled
                    mem_pct = 60 + 35 * progress
                    for i in range(200):
                        ts = ts_base + timedelta(seconds=random.uniform(0, 59))
                        nf.write(_nginx_line(ts) + "\n")
                    af.write(_python_line(
                        ts_base, "WARNING",
                        f"Memory usage at {mem_pct:.0f}% — consider restarting workers"
                    ) + "\n")
                    if progress > 0.8:
                        ts = ts_base + timedelta(seconds=5)
                        kf.write(_k8s_line(ts, "Warning") + "\n")
                        kf.write(
                            f"{ts.strftime('%Y-%m-%dT%H:%M:%SZ')} Warning production/api-pod-7f8b9 "
                            "OOMKilling: OOMKilled: Container exceeded memory limit 512Mi\n"
                        )

                elif anomaly_type == "disk_full":
                    for i in range(200):
                        ts = ts_base + timedelta(seconds=random.uniform(0, 59))
                        nf.write(_nginx_line(ts) + "\n")
                    msg = (
                        "OSError: [Errno 28] No space left on device"
                        if progress > 0.6
                        else f"Disk usage at {75 + 25*progress:.0f}% on /var/log"
                    )
                    level = "ERROR" if progress > 0.6 else "WARNING"
                    af.write(_python_line(ts_base, level, msg) + "\n")

                elif anomaly_type == "connection_pool":
                    for i in range(200):
                        ts = ts_base + timedelta(seconds=random.uniform(0, 59))
                        force_5xx = random.random() < 0.35
                        nf.write(_nginx_line(ts, force_5xx=force_5xx) + "\n")
                    for i in range(20):
                        ts = ts_base + timedelta(seconds=random.uniform(0, 59))
                        af.write(_python_line(
                            ts, "ERROR",
                            "psycopg2.OperationalError: FATAL: remaining connection slots are reserved for non-replication superuser connections"
                        ) + "\n")

        print(f"Anomaly window appended ({anomaly_type})")

    def generate_recovery_window(
        self,
        output_file: str = "nginx_access.log",
        duration_minutes: int = 10,
        start_offset_hours: float = 1.17,
    ):
        path = self.output_dir / output_file
        start = datetime(2025, 5, 12, 8, 0, 0) + timedelta(hours=start_offset_hours)
        with open(path, "a") as f:
            for minute in range(duration_minutes):
                ts_base = start + timedelta(minutes=minute)
                for i in range(200):
                    ts = ts_base + timedelta(seconds=random.uniform(0, 59))
                    # Error rate recovers from ~45% back to ~2%
                    force_5xx = random.random() < max(0.02, 0.45 - 0.04 * minute)
                    f.write(_nginx_line(ts, force_5xx=force_5xx) + "\n")
        print("Recovery window appended")

    def generate_full_dataset(self):
        self.generate_normal_logs(duration_hours=1.0, logs_per_minute=200)
        self.generate_anomaly_window(anomaly_type="error_storm", duration_minutes=10)
        self.generate_recovery_window(duration_minutes=10)
        print("Full dataset generated: 1h normal + 10m anomaly + 10m recovery")


if __name__ == "__main__":
    gen = LogGenerator()
    if len(sys.argv) > 1 and sys.argv[1] == "--anomaly-only":
        atype = sys.argv[2] if len(sys.argv) > 2 else "error_storm"
        gen.generate_anomaly_window(anomaly_type=atype)
    else:
        gen.generate_full_dataset()
