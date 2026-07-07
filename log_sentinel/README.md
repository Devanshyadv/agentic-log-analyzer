# LogSentinel — AI-Powered DevOps Co-Pilot

> **Final-year placement project.** An autonomous log analysis agent that detects anomalies in real-time and delivers root-cause analysis with actionable fix steps — reducing Mean Time To Resolution (MTTR) from ~8 minutes (manual grep) to **~42 seconds**.

---

## What It Does

LogSentinel watches your application logs, detects statistical anomalies using machine learning, and automatically invokes an LLM-powered ReAct agent to diagnose the root cause — all within seconds of an incident occurring.

```
Log Files  ──►  Watcher  ──►  IsolationForest  ──►  LangChain Agent  ──►  Slack / Jira
                                  +z-scores           (llama3.2 via           Alert
                                                        Ollama)
                                                            │
                                                     FAISS Incident
                                                       Memory DB
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        LogSentinel                              │
│                                                                 │
│  ┌──────────────┐    ┌─────────────────┐    ┌───────────────┐  │
│  │  File Watcher│───►│ Anomaly Detector│───►│ Analysis Agent│  │
│  │  (watchdog)  │    │ IsolationForest  │    │ LangChain ReAct│ │
│  └──────────────┘    │  + z-scores     │    │ llama3.2/Ollama│ │
│                      └─────────────────┘    └───────┬───────┘  │
│  ┌──────────────┐                                   │          │
│  │  Log Parsers │    ┌─────────────────┐    ┌───────▼───────┐  │
│  │  nginx/k8s/  │    │  FAISS Vector   │◄───│  Agent Tools  │  │
│  │  python/syslog    │  Incident Memory│    │  - search     │  │
│  └──────────────┘    │  (sentence-     │    │  - diagnostic │  │
│                      │   transformers) │    │  - runbook    │  │
│                      └─────────────────┘    └───────────────┘  │
│                                                                 │
│  ┌──────────────┐    ┌─────────────────┐    ┌───────────────┐  │
│  │  FastAPI     │    │  Streamlit      │    │  Alert Manager│  │
│  │  REST API    │    │  Dashboard      │    │  Slack + Jira │  │
│  └──────────────┘    └─────────────────┘    └───────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Key Metric

| Method | MTTR |
|--------|------|
| Manual grep + Slack thread | 480s (8 min) |
| **LogSentinel — detection** | **38.4s** |
| **LogSentinel — full RCA** | **42.4s** |
| Improvement | **11.3x faster** |

> Run `python main.py watch ./data/sample_logs/` + `python scripts/benchmark_mttr.py` to reproduce.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Log ingestion | `watchdog`, Kafka-ready normalizer |
| Anomaly detection | `scikit-learn` IsolationForest + rolling z-scores |
| LLM agent | LangChain ReAct + `llama3.2` via Ollama (fully offline) |
| Incident memory | FAISS + `sentence-transformers` (all-MiniLM-L6-v2) |
| API | FastAPI + WebSocket live stream |
| Dashboard | Streamlit |
| Alerts | Slack webhooks + Jira REST API |

---

## Setup

### Prerequisites
- Python 3.11+
- [Ollama](https://ollama.com) with `llama3.2` pulled

```bash
ollama pull llama3.2
```

### Install

```bash
git clone <repo-url>
cd log_sentinel
pip install -r requirements.txt
```

### First-time setup (run once)

```bash
# 1. Generate baseline training data
python scripts/generate_logs.py

# 2. Build incident memory index
python -c "from agent.incident_memory import IncidentMemory; m = IncidentMemory(); m.build_index('./data/incidents')"

# 3. Fit the anomaly detector
python -m detection.anomaly_detector fit ./data/sample_logs/
```

---

## Running

Open **three terminals** from the `log_sentinel/` directory:

```bash
# Terminal 1 — API
python -m uvicorn api.main:app --reload --port 8000

# Terminal 2 — Dashboard
python -m streamlit run ui/dashboard.py --server.port 8501

# Terminal 3 — Watch logs
python main.py watch ./data/sample_logs/ --verbose
```

Open **http://localhost:8501** to see the dashboard.

### Inject a live anomaly

```bash
python scripts/inject_anomaly.py --type error_storm
```

Anomaly types: `error_storm`, `latency_spike`, `memory_leak`, `disk_full`, `connection_pool`

---

## Benchmark (MTTR)

With the API running:

```bash
python scripts/benchmark_mttr.py
```

This injects an `error_storm`, measures time-to-detection and time-to-root-cause-analysis, and saves results to `results/`.

---

## Project Structure

```
log_sentinel/
├── parsing/          # Log parsers (nginx, python app, k8s, syslog)
├── ingestion/        # File watcher, Kafka consumer, normalizer
├── detection/        # IsolationForest detector, z-score baseline, classifier
├── agent/            # LangChain ReAct agent, tools, FAISS incident memory
├── alerts/           # Slack + Jira integration, alert manager
├── api/              # FastAPI app (REST + WebSocket)
├── ui/               # Streamlit dashboard
├── scripts/          # Data generation, anomaly injection, MTTR benchmark
├── tests/            # 49 pytest tests
└── data/
    ├── incidents/    # 20 historical incident JSON files (vector DB source)
    ├── runbooks/     # nginx, python app, k8s runbooks
    └── sample_logs/  # Generated training logs
```

---

## Tests

```bash
pytest tests/ -v   # 49 tests, all passing
```

---

## Optional: Alerts

Copy `.env.example` to `.env` and fill in:

```env
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
JIRA_BASE_URL=https://yourorg.atlassian.net
JIRA_API_TOKEN=...
JIRA_PROJECT_KEY=OPS
```

CRITICAL anomalies → Slack + Jira ticket auto-created  
HIGH anomalies → Slack only  
MEDIUM/LOW → dashboard only

---

## Optional: Docker

```bash
docker-compose up -d   # starts Kafka + Zookeeper
```
