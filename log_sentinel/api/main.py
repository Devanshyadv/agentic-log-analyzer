import asyncio
import json
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from pydantic import BaseModel

from config import settings
from detection.anomaly_detector import AnomalyDetector
from detection.classifier import SeverityClassifier
from agent.analysis_agent import AnalysisAgent, AnomalyReport, RootCauseAnalysis
from alerts.alert_manager import AlertManager

# ──────────────────────────────────────────────
# Shared in-process state (populated by FileWatcher)
# ──────────────────────────────────────────────
log_store: deque = deque(maxlen=1000)
anomaly_store: deque = deque(maxlen=50)
_ws_clients: List[WebSocket] = []

detector = AnomalyDetector()
classifier = SeverityClassifier()
agent = AnalysisAgent()
alert_mgr = AlertManager()


# ──────────────────────────────────────────────
# Helpers called by the processing pipeline
# ──────────────────────────────────────────────

def register_log_event(event) -> None:
    log_store.append(event)


def register_anomaly(record: dict) -> None:
    anomaly_store.append(record)


# ──────────────────────────────────────────────
# App
# ──────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("LogSentinel API starting — loading model…")
    detector.load_or_fit()
    logger.info("API ready")
    yield
    logger.info("API shutting down")


app = FastAPI(title="LogSentinel API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ──────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "model_loaded": detector._fitted,
        "faiss_ready": True,
        "recent_anomaly_count": len(anomaly_store),
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/logs")
async def get_logs(
    limit: int = Query(100, le=1000),
    level: Optional[str] = Query(None),
    service: Optional[str] = Query(None),
):
    logs = list(log_store)
    if level:
        logs = [l for l in logs if l.level == level.upper()]
    if service:
        logs = [l for l in logs if l.service == service]
    return [l.to_dict() for l in logs[-limit:]]


@app.get("/anomalies")
async def get_anomalies(limit: int = Query(20, le=50)):
    return list(anomaly_store)[-limit:]


class AnalyzeRequest(BaseModel):
    log_lines: List[str]


class InjectRequest(BaseModel):
    service: str = "nginx"
    anomaly_type: str = "error_storm"


@app.post("/analyze")
async def analyze_logs(request: AnalyzeRequest):
    from ingestion.normalizer import NormalizerPipeline

    normalizer = NormalizerPipeline()
    events = [e for line in request.log_lines if (e := normalizer.process(line, "api"))]

    if not events:
        raise HTTPException(status_code=400, detail="No parseable log lines provided")

    now = datetime.utcnow()
    window = detector.compute_window_features(events, now, now)
    anomaly_result = detector.predict(window)

    if not anomaly_result.is_anomaly:
        return {"message": "No anomaly detected", "anomaly_score": anomaly_result.anomaly_score}

    classification = classifier.classify(anomaly_result, window)
    report = AnomalyReport(
        anomaly_score=anomaly_result.anomaly_score,
        severity=classification.severity.value,
        features=anomaly_result.features,
        z_scores=anomaly_result.z_scores,
        sample_log_lines=[e.raw_line for e in events[:10]],
    )
    analysis = agent.analyze(report)
    return analysis.model_dump()


@app.post("/inject-anomaly")
async def inject_anomaly_endpoint(request: InjectRequest):
    import subprocess, sys
    subprocess.Popen(
        [sys.executable, "scripts/inject_anomaly.py",
         "--type", request.anomaly_type,
         "--service", request.service],
    )
    return {"status": "injection started", "type": request.anomaly_type}


# ──────────────────────────────────────────────
# WebSocket stream
# ──────────────────────────────────────────────

@app.websocket("/stream")
async def ws_stream(websocket: WebSocket):
    await websocket.accept()
    _ws_clients.append(websocket)
    try:
        while True:
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass
    finally:
        if websocket in _ws_clients:
            _ws_clients.remove(websocket)


async def broadcast(payload: dict):
    dead = []
    msg = json.dumps(payload) + "\n"
    for ws in _ws_clients:
        try:
            await ws.send_text(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        if ws in _ws_clients:
            _ws_clients.remove(ws)
