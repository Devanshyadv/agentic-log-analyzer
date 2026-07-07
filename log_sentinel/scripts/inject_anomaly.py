"""Inject a live anomaly into a watched log file to trigger the LogSentinel pipeline."""

import argparse
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))


def _nginx_error_line(ts: datetime) -> str:
    ip = f"10.0.{random.randint(1,10)}.{random.randint(1,254)}"
    paths = ["/api/users", "/api/orders", "/api/checkout", "/api/products"]
    path = random.choice(paths)
    status = random.choice([500, 502, 503, 500, 500])
    lat = random.uniform(2.0, 8.0)
    ts_str = ts.strftime("%d/%b/%Y:%H:%M:%S +0000")
    return f'{ip} - - [{ts_str}] "POST {path} HTTP/1.1" {status} 0 "{lat:.3f}"'


def _app_error_line(ts: datetime, anomaly_type: str) -> str:
    module = random.choice(["app.api", "app.db", "app.worker"])
    lineno = random.randint(20, 300)
    ts_str = ts.strftime("%Y-%m-%d %H:%M:%S") + f",{ts.microsecond // 1000:03d}"
    msgs = {
        "error_storm": [
            "psycopg2.OperationalError: FATAL: remaining connection slots are reserved",
            "ConnectionResetError: [Errno 104] Connection reset by peer",
            "TimeoutError: upstream request timed out after 30s",
            "RuntimeError: worker process killed due to memory limit",
        ],
        "latency_spike": [
            f"Slow query ({random.randint(5000,15000)}ms): SELECT * FROM orders o JOIN users u ON o.user_id=u.id",
            f"External API call took {random.randint(6000,12000)}ms — threshold 2000ms",
        ],
        "memory_leak": [
            f"Memory usage: {random.randint(85, 99)}% — approaching limit 512Mi",
            "WARNING: gc collected 0 objects — potential memory leak in request handler",
        ],
        "disk_full": [
            "OSError: [Errno 28] No space left on device: '/var/log/app/access.log'",
            f"Disk at {random.randint(95, 100)}% capacity — write operations may fail",
        ],
        "connection_pool": [
            "psycopg2.OperationalError: FATAL: remaining connection slots are reserved for superuser",
            f"Pool exhausted: {random.randint(20,20)}/20 connections active, 0 available",
        ],
    }
    msg = random.choice(msgs.get(anomaly_type, msgs["error_storm"]))
    return f"{ts_str} ERROR    {module}:{lineno} - {msg}"


def inject(
    anomaly_type: str = "error_storm",
    service: str = "nginx",
    log_dir: str = None,
    num_lines: int = 120,
    interval_ms: int = 300,
):
    base = Path(log_dir) if log_dir else BASE_DIR / "data" / "sample_logs"
    nginx_file = base / "nginx_access.log"
    app_file = base / "app_errors.log"

    # Ensure files exist
    nginx_file.parent.mkdir(parents=True, exist_ok=True)
    nginx_file.touch(exist_ok=True)
    app_file.touch(exist_ok=True)

    print(f"Injecting {num_lines} anomaly lines of type '{anomaly_type}' into {base}")

    for i in range(num_lines):
        ts = datetime.now(timezone.utc).replace(tzinfo=None)
        nginx_line = _nginx_error_line(ts)
        app_line = _app_error_line(ts, anomaly_type)

        with open(nginx_file, "a", encoding="utf-8") as f:
            f.write(nginx_line + "\n")
        with open(app_file, "a", encoding="utf-8") as f:
            f.write(app_line + "\n")

        if i % 20 == 0:
            print(f"  {i}/{num_lines} lines injected…")

        time.sleep(interval_ms / 1000.0)

    print(f"Done. Injected {num_lines} lines of '{anomaly_type}' anomaly.")
    print("Check the LogSentinel dashboard at http://localhost:8501")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Inject anomaly logs into watched files")
    parser.add_argument("--type", default="error_storm",
                        choices=["error_storm", "latency_spike", "memory_leak", "disk_full", "connection_pool"])
    parser.add_argument("--service", default="nginx")
    parser.add_argument("--lines", type=int, default=120)
    parser.add_argument("--interval-ms", type=int, default=300)
    parser.add_argument("--log-dir", default=None)
    args = parser.parse_args()

    inject(
        anomaly_type=args.type,
        service=args.service,
        log_dir=args.log_dir,
        num_lines=args.lines,
        interval_ms=args.interval_ms,
    )
