"""LogSentinel CLI entry point."""

import argparse
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

# Ensure project root is on PYTHONPATH when run directly
sys.path.insert(0, str(Path(__file__).resolve().parent))


def _start_api_server(port: int = 8000):
    import uvicorn
    uvicorn.run("api.main:app", host="0.0.0.0", port=port, log_level="warning")


def _process_event(event, detector, classifier, agent_instance, alert_mgr, verbose: bool):
    """Called by the file watcher for each new log line."""
    from api.main import log_store, anomaly_store, detector as api_detector
    from detection.baseline import TimeWindowFeatures

    log_store.append(event)

    if verbose:
        print(f"[{event.level}] {event.service}: {event.message[:100]}")

    # Accumulate events per service in a 60-second buffer
    key = event.service
    if not hasattr(_process_event, "_buffers"):
        _process_event._buffers = {}
        _process_event._buffer_starts = {}

    buf = _process_event._buffers
    starts = _process_event._buffer_starts

    buf.setdefault(key, []).append(event)
    starts.setdefault(key, event.timestamp)

    # Check if window is ready (30s or 50 events — keeps demo snappy)
    elapsed = (event.timestamp - starts[key]).total_seconds()
    if elapsed >= 30 or len(buf[key]) >= 50:
        events_in_window = buf.pop(key)
        window_start = starts.pop(key)

        window = detector.compute_window_features(
            events_in_window, window_start, event.timestamp
        )
        result = detector.predict(window)

        if result.is_anomaly:
            classification = classifier.classify(result, window)
            from agent.analysis_agent import AnomalyReport
            report = AnomalyReport(
                anomaly_score=result.anomaly_score,
                severity=classification.severity.value,
                features=result.features,
                z_scores=result.z_scores,
                sample_log_lines=[e.raw_line for e in events_in_window[-10:]],
                service=key,
            )
            print(
                f"\n🚨 Anomaly detected [{classification.severity.value}] in '{key}' — "
                f"error_rate={window.error_rate:.1%}, score={result.anomaly_score:.3f}"
            )
            print("   Running LLM analysis…")
            analysis = agent_instance.analyze(report)
            print(f"   Root cause: {analysis.root_cause[:120]}")

            record = {
                "detected_at": datetime.utcnow().isoformat(),
                "service": key,
                "severity": classification.severity.value,
                "anomaly_score": result.anomaly_score,
                "error_rate": window.error_rate,
                "features": result.features,
                "analysis": analysis.model_dump(),
                "reasoning": classification.reasoning,
            }
            anomaly_store.append(record)
            alert_mgr.route(analysis, classification.severity, key)


def cmd_watch(args):
    from ingestion.file_watcher import FileWatcher
    from detection.anomaly_detector import AnomalyDetector
    from detection.classifier import SeverityClassifier
    from agent.analysis_agent import AnalysisAgent
    from alerts.alert_manager import AlertManager
    from ingestion.normalizer import NormalizerPipeline

    log_dir = Path(args.log_dir)
    if not log_dir.exists():
        print(f"Error: {log_dir} does not exist. Run: make generate-data")
        sys.exit(1)

    # Load / fit model
    detector = AnomalyDetector()
    normalizer = NormalizerPipeline()
    events = []
    for lf in sorted(log_dir.glob("*.log")):
        try:
            with open(lf, "r", errors="replace") as f:
                for line in f:
                    ev = normalizer.process(line.strip(), lf.stem)
                    if ev:
                        events.append(ev)
        except OSError:
            pass
    detector.load_or_fit(events or None)

    classifier = SeverityClassifier()
    agent_instance = AnalysisAgent()
    alert_mgr = AlertManager()

    # Start API server in background thread
    api_thread = threading.Thread(
        target=_start_api_server, kwargs={"port": args.api_port}, daemon=True
    )
    api_thread.start()
    print(f"LogSentinel API running at http://localhost:{args.api_port}")
    print(f"Dashboard: http://localhost:8501  (run: make run-ui)")

    def on_event(event):
        _process_event(event, detector, classifier, agent_instance, alert_mgr, args.verbose)

    watcher = FileWatcher(str(log_dir), on_event)
    log_count = len(list(log_dir.glob("*.log")))
    print(f"Watching {log_count} log files in {log_dir}  (Ctrl+C to stop)\n")
    watcher.run_forever()


def cmd_analyze(args):
    from ingestion.normalizer import NormalizerPipeline
    from detection.anomaly_detector import AnomalyDetector
    from detection.classifier import SeverityClassifier
    from agent.analysis_agent import AnalysisAgent

    normalizer = NormalizerPipeline()
    detector = AnomalyDetector()
    detector.load_or_fit()
    classifier = SeverityClassifier()
    agent_instance = AnalysisAgent()

    path = Path(args.log_file)
    events = []
    with open(path, "r", errors="replace") as f:
        for line in f:
            ev = normalizer.process(line.strip(), path.stem)
            if ev:
                events.append(ev)

    if not events:
        print("No parseable events found")
        sys.exit(1)

    print(f"Parsed {len(events)} events from {path}")
    from datetime import datetime
    window = detector.compute_window_features(events, datetime.utcnow(), datetime.utcnow())
    result = detector.predict(window)
    classification = classifier.classify(result, window)

    print(f"Anomaly: {result.is_anomaly}  Score: {result.anomaly_score:.4f}  Severity: {classification.severity.value}")
    if result.is_anomaly:
        from agent.analysis_agent import AnomalyReport
        report = AnomalyReport(
            anomaly_score=result.anomaly_score,
            severity=classification.severity.value,
            features=result.features,
            z_scores=result.z_scores,
            sample_log_lines=[e.raw_line for e in events[-10:]],
        )
        analysis = agent_instance.analyze(report)
        print(f"\nRoot Cause: {analysis.root_cause}")
        print("\nFix Steps:")
        for i, step in enumerate(analysis.fix_steps, 1):
            print(f"  {i}. {step}")


def cmd_benchmark(_args):
    from scripts.benchmark_mttr import run
    run()


def main():
    parser = argparse.ArgumentParser(description="LogSentinel — AI-Powered DevOps Co-Pilot")
    sub = parser.add_subparsers(dest="command", required=True)

    # watch
    p_watch = sub.add_parser("watch", help="Watch a directory of log files in real-time")
    p_watch.add_argument("log_dir", help="Directory containing .log files")
    p_watch.add_argument("--model", default="llama3.2", help="Ollama model name")
    p_watch.add_argument("--api-port", type=int, default=8000)
    p_watch.add_argument("--no-slack", action="store_true")
    p_watch.add_argument("--verbose", action="store_true")

    # analyze
    p_analyze = sub.add_parser("analyze", help="One-shot analysis of a log file")
    p_analyze.add_argument("log_file", help="Path to log file")

    # benchmark
    sub.add_parser("benchmark", help="Run MTTR benchmark (API must be running)")

    args = parser.parse_args()
    dispatch = {"watch": cmd_watch, "analyze": cmd_analyze, "benchmark": cmd_benchmark}
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
