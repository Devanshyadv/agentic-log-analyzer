from typing import Optional, TYPE_CHECKING
import requests
from loguru import logger

from config import settings

if TYPE_CHECKING:
    from agent.analysis_agent import RootCauseAnalysis
    from detection.classifier import Severity

_PRIORITY_MAP = {"CRITICAL": "Highest", "HIGH": "High", "MEDIUM": "Medium", "LOW": "Low"}


class JiraTicket:
    def create_ticket(
        self,
        analysis: "RootCauseAnalysis",
        severity: "Severity",
    ) -> Optional[str]:
        if not settings.JIRA_BASE_URL or not settings.JIRA_API_TOKEN:
            logger.info("Jira not configured — skipping ticket creation")
            return None

        sev = severity.value if hasattr(severity, "value") else str(severity)
        fix_text = "\n".join(f"{i}. {s}" for i, s in enumerate(analysis.fix_steps, 1))
        cmd_text = "\n".join(analysis.run_these_commands)

        description = {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "heading",
                    "attrs": {"level": 2},
                    "content": [{"type": "text", "text": "Anomaly Summary"}],
                },
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": analysis.anomaly_summary}],
                },
                {
                    "type": "heading",
                    "attrs": {"level": 2},
                    "content": [{"type": "text", "text": "Root Cause"}],
                },
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": analysis.root_cause}],
                },
                {
                    "type": "heading",
                    "attrs": {"level": 2},
                    "content": [{"type": "text", "text": "Fix Steps"}],
                },
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": fix_text}],
                },
                {
                    "type": "heading",
                    "attrs": {"level": 2},
                    "content": [{"type": "text", "text": "Diagnostic Commands"}],
                },
                {
                    "type": "codeBlock",
                    "attrs": {},
                    "content": [{"type": "text", "text": cmd_text}],
                },
            ],
        }

        payload = {
            "fields": {
                "project": {"key": settings.JIRA_PROJECT_KEY},
                "summary": f"LogSentinel: {analysis.anomaly_summary[:250]}",
                "description": description,
                "issuetype": {"name": "Bug"},
                "priority": {"name": _PRIORITY_MAP.get(sev, "Medium")},
            }
        }

        try:
            resp = requests.post(
                f"{settings.JIRA_BASE_URL}/rest/api/3/issue",
                headers={
                    "Authorization": f"Bearer {settings.JIRA_API_TOKEN}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=10,
            )
            resp.raise_for_status()
            key = resp.json().get("key")
            logger.info(f"Jira ticket created: {key}")
            return key
        except requests.RequestException as e:
            logger.error(f"Jira ticket creation failed: {e}")
            return None
