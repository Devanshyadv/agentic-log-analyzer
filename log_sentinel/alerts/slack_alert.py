from typing import TYPE_CHECKING
from loguru import logger

from config import settings

if TYPE_CHECKING:
    from agent.analysis_agent import RootCauseAnalysis
    from detection.classifier import Severity


class SlackAlerter:
    def __init__(self):
        self._client = None

    def _get_client(self):
        if not settings.SLACK_WEBHOOK_URL:
            return None
        if self._client is None:
            from slack_sdk.webhook import WebhookClient
            self._client = WebhookClient(settings.SLACK_WEBHOOK_URL)
        return self._client

    def send_anomaly_alert(
        self,
        analysis: "RootCauseAnalysis",
        severity: "Severity",
    ) -> bool:
        client = self._get_client()
        if client is None:
            logger.warning("SLACK_WEBHOOK_URL not configured — skipping Slack alert")
            return False

        sev = severity.value if hasattr(severity, "value") else str(severity)
        emoji = {"CRITICAL": "🚨", "HIGH": "⚠️", "MEDIUM": "🔶", "LOW": "🔵"}.get(sev, "🔍")
        fix_text = "\n".join(f"{i}. {s}" for i, s in enumerate(analysis.fix_steps, 1))
        cmd_text = "\n".join(f"`{c}`" for c in analysis.run_these_commands)

        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"{emoji} {sev}: LogSentinel Anomaly Detected"},
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Severity:*\n{sev}"},
                    {"type": "mrkdwn", "text": f"*Confidence:*\n{analysis.confidence:.0%}"},
                ],
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Summary:*\n{analysis.anomaly_summary}"},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Root Cause:*\n{analysis.root_cause}"},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Fix Steps:*\n{fix_text}"},
            },
        ]
        if analysis.run_these_commands:
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Diagnostic Commands:*\n{cmd_text}"},
            })
        blocks.append({
            "type": "context",
            "elements": [{
                "type": "mrkdwn",
                "text": (
                    f"Escalate: {'*YES*' if analysis.escalate else 'No'} | "
                    f"Est. resolution: {analysis.estimated_resolution_minutes} min | "
                    f"LogSentinel"
                ),
            }],
        })

        try:
            resp = client.send(blocks=blocks)
            ok = resp.status_code == 200
            if not ok:
                logger.error(f"Slack returned {resp.status_code}: {resp.body}")
            return ok
        except Exception as e:
            logger.error(f"Slack alert failed: {e}")
            return False
