# LogSentinel Makefile
# Requires GNU Make. On Windows use WSL2 or Git Bash.

.PHONY: install pull-model generate-data build-index fit-detector \
        run-api run-ui run-all watch inject benchmark \
        up down test clean

install:
	pip install -r requirements.txt

pull-model:
	ollama pull llama3.2

generate-data:
	python scripts/generate_logs.py

build-index:
	python -c "from agent.incident_memory import IncidentMemory; m = IncidentMemory(); m.build_index('./data/incidents')"

fit-detector:
	python -m detection.anomaly_detector fit ./data/sample_logs/

run-api:
	uvicorn api.main:app --reload --port 8000

run-ui:
	streamlit run ui/dashboard.py --server.port 8501

run-all:
	make run-api & make run-ui

watch:
	python main.py watch ./data/sample_logs/

inject:
	python scripts/inject_anomaly.py --type error_storm

benchmark:
	python scripts/benchmark_mttr.py

up:
	docker-compose up -d

down:
	docker-compose down

test:
	pytest tests/ -v

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; \
	find . -name "*.pyc" -delete 2>/dev/null; \
	rm -f data/faiss_index/*.index data/faiss_index/*.pkl; \
	rm -f data/sample_logs/*.log; \
	echo "Cleaned"
