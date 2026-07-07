import time
from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING
from loguru import logger

from config import settings
from alerts.slack_alert import SlackAlerter
from alerts.jira_ticket import JiraTicket

if TYPE_CHECKING:
    from agent.analysis_agent import RootCauseAnalysis
    from detection.classifier import Severity


@dataclass
class AlertResult:
    alerted: bool
    slack_sent: bool
    jira_key: Optional[str]


class AlertManager:
    def __init__(self):
        self._slack = SlackAlerter()
        self._jira = JiraTicket()
        self._last_alert: dict = {}

    def route(
        self,
        analysis: "RootCauseAnalysis",
        severity: "Severity",
        service: str,
    ) -> AlertResult:
        now = time.time()
        last = self._last_alert.get(service, 0.0)

        if now - last < settings.ALERT_COOLDOWN_SECONDS:
            remaining = int(settings.ALERT_COOLDOWN_SECONDS - (now - last))
            logger.info(f"Alert cooldown for '{service}': {remaining}s remaining — suppressed")
            return AlertResult(alerted=False, slack_sent=False, jira_key=None)

        sev = severity.value if hasattr(severity, "value") else str(severity)
        slack_sent = False
        jira_key = None

        if sev == "CRITICAL":
            slack_sent = self._slack.send_anomaly_alert(analysis, severity)
            jira_key = self._jira.create_ticket(analysis, severity)
            logger.info(f"CRITICAL alert dispatched: slack={slack_sent}, jira={jira_key}")
        elif sev == "HIGH":
            slack_sent = self._slack.send_anomaly_alert(analysis, severity)
            logger.info(f"HIGH alert sent to Slack: {slack_sent}")
        else:
            logger.info(f"{sev} anomaly recorded on dashboard (no external alert)")

        self._last_alert[service] = now
        return AlertResult(
            alerted=sev in ("CRITICAL", "HIGH"),
            slack_sent=slack_sent,
            jira_key=jira_key,
        )
