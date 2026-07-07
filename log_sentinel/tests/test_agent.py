import pytest


class TestRunDiagnosticTool:
    def test_allowed_command_executes(self):
        from agent.tools import run_diagnostic
        result = run_diagnostic.invoke("uptime")
        # On Windows this will say "not available" — acceptable
        assert isinstance(result, str)
        assert len(result) > 0

    def test_disallowed_command_rejected(self):
        from agent.tools import run_diagnostic
        result = run_diagnostic.invoke("rm -rf /")
        assert "not allowed" in result.lower()

    def test_disallowed_with_shell_injection(self):
        from agent.tools import run_diagnostic
        result = run_diagnostic.invoke("df -h; rm -rf /")
        assert "not allowed" in result.lower()

    def test_disallowed_arbitrary_command(self):
        from agent.tools import run_diagnostic
        result = run_diagnostic.invoke("cat /etc/passwd")
        assert "not allowed" in result.lower()

    def test_empty_string_rejected(self):
        from agent.tools import run_diagnostic
        result = run_diagnostic.invoke("")
        assert "not allowed" in result.lower()


class TestGetServiceRunbook:
    def test_unknown_service_returns_message(self):
        from agent.tools import get_service_runbook
        result = get_service_runbook.invoke("unknown_service")
        assert "no runbook" in result.lower() or "not found" in result.lower()

    def test_nginx_runbook_returns_string(self):
        from agent.tools import get_service_runbook
        result = get_service_runbook.invoke("nginx")
        assert isinstance(result, str)

    def test_k8s_alias_works(self):
        from agent.tools import get_service_runbook
        result = get_service_runbook.invoke("kubernetes")
        assert isinstance(result, str)


class TestSearchSimilarIncidents:
    def test_returns_string(self):
        from agent.tools import search_similar_incidents
        # FAISS index may not be built yet — should not crash
        result = search_similar_incidents.invoke("high error rate database connection")
        assert isinstance(result, str)
