import time
from dataclasses import dataclass
from typing import List
from loguru import logger
from pydantic import BaseModel, field_validator

from config import settings


# ──────────────────────────────────────────────
# Data models
# ──────────────────────────────────────────────

@dataclass
class AnomalyReport:
    anomaly_score: float
    severity: str
    features: dict
    z_scores: dict
    sample_log_lines: List[str]
    service: str = "unknown"


class RootCauseAnalysis(BaseModel):
    anomaly_summary: str
    root_cause: str
    confidence: float
    similar_incidents: List[str]
    fix_steps: List[str]
    run_these_commands: List[str]
    escalate: bool
    estimated_resolution_minutes: int

    @field_validator("confidence")
    @classmethod
    def clamp_confidence(cls, v):
        return max(0.0, min(1.0, float(v)))


_FALLBACK = RootCauseAnalysis(
    anomaly_summary="Anomaly detected — automated analysis failed",
    root_cause="Unable to determine root cause automatically. Please escalate to on-call engineer.",
    confidence=0.0,
    similar_incidents=[],
    fix_steps=[
        "Check application logs manually for error patterns",
        "Review recent deployments and config changes",
        "Monitor resource utilisation (CPU, memory, disk)",
        "Contact on-call engineer if service is degraded",
    ],
    run_these_commands=["df -h", "free -m", "ps aux"],
    escalate=True,
    estimated_resolution_minutes=30,
)

# ──────────────────────────────────────────────
# System prompt for LangGraph ReAct agent
# ──────────────────────────────────────────────

_SYSTEM_PROMPT = """You are LogSentinel, a senior SRE investigating a production incident.

You have EXACTLY three tools available — do not call, mention, or invent any other tool name:
- search_similar_incidents
- get_service_runbook
- run_diagnostic

Steps:
1. Call search_similar_incidents with a description of the anomaly
2. Call get_service_runbook with the affected service name
3. Optionally call run_diagnostic if more info is needed
4. Once you have enough information, summarize your root cause analysis in a final message."""


def _build_input(report: AnomalyReport) -> str:
    top_z = sorted(
        report.z_scores.items(), key=lambda kv: abs(kv[1]), reverse=True
    )[:4]
    z_lines = "\n".join(f"  {k}: {v:+.2f}σ" for k, v in top_z)
    sample = "\n".join(f"  {line[:120]}" for line in report.sample_log_lines[:5])
    return (
        f"Anomaly detected in service '{report.service}' (severity: {report.severity}).\n\n"
        f"Metrics:\n"
        f"  anomaly_score:   {report.anomaly_score:.4f}\n"
        f"  error_rate:      {report.features.get('error_rate', 0):.1%}\n"
        f"  p99_latency_ms:  {report.features.get('p99_latency_ms', 0):.0f}\n"
        f"  total_logs:      {report.features.get('total_logs', 0)}\n"
        f"  5xx_count:       {report.features.get('status_5xx_count', 0)}\n\n"
        f"Highest z-scores (deviation from baseline):\n{z_lines}\n\n"
        f"Sample log lines:\n{sample}\n\n"
        "Investigate this anomaly with your tools and provide a root cause analysis."
    )


# ──────────────────────────────────────────────
# Agent
# ──────────────────────────────────────────────

class AnalysisAgent:
    def __init__(self):
        self._agent = None

    def _build_agent(self):
        from langchain_ollama import ChatOllama
        from langgraph.prebuilt import create_react_agent
        from agent.tools import search_similar_incidents, run_diagnostic, get_service_runbook

        llm = ChatOllama(
            model=settings.LLM_MODEL,
            base_url=settings.OLLAMA_BASE_URL,
            temperature=0.1,
        )
        tools = [search_similar_incidents, run_diagnostic, get_service_runbook]
        return create_react_agent(
            model=llm,
            tools=tools,
            prompt=_SYSTEM_PROMPT,
            # Delegates final-answer extraction to a dedicated structured-output
            # call instead of hoping the ReAct loop's last message happens to be
            # bare JSON — the model was otherwise prone to emitting hallucinated
            # tool-call-shaped text as its "final answer".
            response_format=RootCauseAnalysis,
        )

    def _get_agent(self):
        if self._agent is None:
            self._agent = self._build_agent()
        return self._agent

    def analyze(self, report: AnomalyReport) -> RootCauseAnalysis:
        t0 = time.time()
        try:
            agent = self._get_agent()
            result = agent.invoke(
                {"messages": [("human", _build_input(report))]},
                config={"recursion_limit": settings.MAX_AGENT_ITERATIONS * 2 + 1},
            )
            elapsed = time.time() - t0
            structured = result.get("structured_response")
            if structured is None:
                logger.warning(f"Agent finished in {elapsed:.1f}s with no structured_response")
                return _FALLBACK
            logger.info(f"Agent finished in {elapsed:.1f}s")
            return structured
        except Exception as e:
            elapsed = time.time() - t0
            logger.error(f"Agent failed after {elapsed:.1f}s: {e}")
            return _FALLBACK
