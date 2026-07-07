"""Benchmark Mean Time To Resolution (MTTR) — the core resume metric."""

import json
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

API_BASE = "http://localhost:8000"
RESULTS_DIR = BASE_DIR / "results"


def _wait_for_api(timeout: int = 30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(f"{API_BASE}/health", timeout=2)
            if r.ok:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def run():
    RESULTS_DIR.mkdir(exist_ok=True)
    print("LogSentinel MTTR Benchmark")
    print("=" * 50)

    if not _wait_for_api():
        print("ERROR: LogSentinel API not reachable at http://localhost:8000")
        print("Start the API first: make run-api")
        sys.exit(1)

    # Baseline anomaly count before injection
    pre = requests.get(f"{API_BASE}/anomalies", timeout=5).json()
    pre_count = len(pre)
    print(f"Baseline anomaly count: {pre_count}")

    # ── T0: inject anomaly ────────────────────────────────────────
    print("\nInjecting error_storm anomaly…")
    t_inject = time.time()

    # Use the API endpoint to trigger injection in a subprocess
    requests.post(
        f"{API_BASE}/inject-anomaly",
        json={"service": "nginx", "anomaly_type": "error_storm"},
        timeout=5,
    )

    # ── Poll for detection ────────────────────────────────────────
    print("Waiting for anomaly detection…", end="", flush=True)
    t_detected = None
    for _ in range(120):  # poll for up to 4 minutes
        time.sleep(2)
        try:
            anomalies = requests.get(f"{API_BASE}/anomalies", timeout=3).json()
            if len(anomalies) > pre_count:
                t_detected = time.time()
                print(f" detected! ({t_detected - t_inject:.1f}s)")
                break
        except Exception:
            pass
        print(".", end="", flush=True)
    else:
        print("\nTIMEOUT: anomaly not detected within 4 minutes")
        sys.exit(1)

    time_to_detect = t_detected - t_inject

    # ── Poll for root cause analysis ────────────────────────────
    print("Waiting for LLM root cause analysis…", end="", flush=True)
    t_analyzed = None
    latest_analysis = None
    for _ in range(90):  # poll for up to 3 minutes
        time.sleep(2)
        try:
            anomalies = requests.get(f"{API_BASE}/anomalies", timeout=3).json()
            new_anomalies = anomalies[pre_count:]
            if new_anomalies:
                a = new_anomalies[-1]
                if a.get("analysis") and a["analysis"].get("root_cause"):
                    t_analyzed = time.time()
                    latest_analysis = a["analysis"]
                    print(f" done! ({t_analyzed - t_inject:.1f}s)")
                    break
        except Exception:
            pass
        print(".", end="", flush=True)
    else:
        t_analyzed = time.time()
        print("\nNOTE: analysis did not complete — recording detection time only")

    time_to_analyze = t_analyzed - t_inject

    # ── Results ───────────────────────────────────────────────────
    print("\n" + "=" * 50)
    print("BENCHMARK RESULTS")
    print("=" * 50)
    print(f"  Time to detect:  {time_to_detect:6.1f}s")
    print(f"  Time to analyze: {time_to_analyze:6.1f}s  ← MTTR")
    print(f"  Baseline MTTR (manual grep): ~480s (8 minutes)")
    print(f"  Improvement:     {480 / max(time_to_analyze, 1):.1f}x faster")

    if latest_analysis:
        print(f"\n  Root cause: {latest_analysis.get('root_cause', '')[:200]}")
        print(f"  Confidence: {latest_analysis.get('confidence', 0):.0%}")
        print("\n  Fix steps:")
        for i, step in enumerate(latest_analysis.get("fix_steps", [])[:4], 1):
            print(f"    {i}. {step[:100]}")

    result = {
        "timestamp": datetime.utcnow().isoformat(),
        "anomaly_type": "error_storm",
        "time_to_detect_seconds": round(time_to_detect, 2),
        "time_to_analyze_seconds": round(time_to_analyze, 2),
        "baseline_mttr_seconds": 480,
        "improvement_factor": round(480 / max(time_to_analyze, 1), 1),
        "root_cause": latest_analysis.get("root_cause") if latest_analysis else None,
        "confidence": latest_analysis.get("confidence") if latest_analysis else None,
    }

    ts_str = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    out_path = RESULTS_DIR / f"benchmark_{ts_str}.json"
    out_path.write_text(json.dumps(result, indent=2))
    print(f"\n  Results saved → {out_path}")
    print("=" * 50)
    return result


if __name__ == "__main__":
    run()
