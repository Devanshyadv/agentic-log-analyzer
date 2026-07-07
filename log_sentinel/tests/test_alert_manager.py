import time
import pytest
from unittest.mock import MagicMock, patch

from alerts.alert_manager import AlertManager, AlertResult
from detection.classifier import Severity
from agent.analysis_agent import RootCauseAnalysis


def _make_analysis() -> RootCauseAnalysis:
    return RootCauseAnalysis(
        anomaly_summary="Test anomaly",
        root_cause="High error rate caused by DB connection exhaustion",
        confidence=0.85,
        similar_incidents=["INC-001"],
        fix_steps=["Restart app", "Add connection pooler"],
        run_these_commands=["df -h"],
        escalate=False,
        estimated_resolution_minutes=10,
    )


class TestAlertManagerCooldown:
    def test_second_alert_within_cooldown_suppressed(self):
        mgr = AlertManager()
        analysis = _make_analysis()

        with patch.object(mgr._slack, "send_anomaly_alert", return_value=True), \
             patch.object(mgr._jira, "create_ticket", return_value="OPS-1"):
            r1 = mgr.route(analysis, Severity.CRITICAL, "nginx")
            r2 = mgr.route(analysis, Severity.CRITICAL, "nginx")

        assert r1.alerted is True
        assert r2.alerted is False  # suppressed by cooldown

    def test_different_services_not_affected_by_each_others_cooldown(self):
        mgr = AlertManager()
        analysis = _make_analysis()

        with patch.object(mgr._slack, "send_anomaly_alert", return_value=True), \
             patch.object(mgr._jira, "create_ticket", return_value=None):
            r1 = mgr.route(analysis, Severity.HIGH, "nginx")
            r2 = mgr.route(analysis, Severity.HIGH, "python_app")

        assert r1.alerted is True
        assert r2.alerted is True


class TestAlertManagerRouting:
    def test_critical_calls_slack_and_jira(self):
        mgr = AlertManager()
        analysis = _make_analysis()

        with patch.object(mgr._slack, "send_anomaly_alert", return_value=True) as mock_slack, \
             patch.object(mgr._jira, "create_ticket", return_value="OPS-5") as mock_jira:
            result = mgr.route(analysis, Severity.CRITICAL, "svc-a")

        mock_slack.assert_called_once()
        mock_jira.assert_called_once()
        assert result.slack_sent is True
        assert result.jira_key == "OPS-5"

    def test_high_calls_slack_only(self):
        mgr = AlertManager()
        analysis = _make_analysis()

        with patch.object(mgr._slack, "send_anomaly_alert", return_value=True) as mock_slack, \
             patch.object(mgr._jira, "create_ticket", return_value=None) as mock_jira:
            result = mgr.route(analysis, Severity.HIGH, "svc-b")

        mock_slack.assert_called_once()
        mock_jira.assert_not_called()
        assert result.slack_sent is True
        assert result.jira_key is None

    def test_medium_no_external_alert(self):
        mgr = AlertManager()
        analysis = _make_analysis()

        with patch.object(mgr._slack, "send_anomaly_alert", return_value=True) as mock_slack, \
             patch.object(mgr._jira, "create_ticket") as mock_jira:
            result = mgr.route(analysis, Severity.MEDIUM, "svc-c")

        mock_slack.assert_not_called()
        mock_jira.assert_not_called()
        assert result.alerted is False

    def test_low_no_external_alert(self):
        mgr = AlertManager()
        analysis = _make_analysis()

        with patch.object(mgr._slack, "send_anomaly_alert") as mock_slack, \
             patch.object(mgr._jira, "create_ticket") as mock_jira:
            result = mgr.route(analysis, Severity.LOW, "svc-d")

        mock_slack.assert_not_called()
        mock_jira.assert_not_called()
