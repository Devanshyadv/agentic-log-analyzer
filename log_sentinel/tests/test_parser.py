import pytest
from datetime import datetime
from parsing.log_parser import LogParser


@pytest.fixture
def parser():
    return LogParser()


NGINX_LINE = '192.168.1.1 - - [12/May/2025:10:23:45 +0000] "GET /api/users HTTP/1.1" 500 234 "0.342"'
NGINX_200  = '10.0.0.5 - - [01/Jan/2025:00:00:01 +0000] "GET /health HTTP/1.1" 200 18 "0.012"'
PYTHON_LINE = '2025-05-12 10:23:45,123 ERROR    app.api:45 - Database connection failed'
K8S_LINE    = '2025-05-12T10:23:45Z WARNING default/api-pod-7f8b OOMKilled: Container killed'
SYSLOG_LINE = 'May 12 10:23:45 webserver nginx[1234]: upstream timed out'
GARBAGE     = 'this is not a log line at all ===##'


class TestDetectFormat:
    def test_nginx_access(self, parser):
        assert parser.detect_format(NGINX_LINE) == "nginx_access"

    def test_python_app(self, parser):
        assert parser.detect_format(PYTHON_LINE) == "python_app"

    def test_k8s_event(self, parser):
        assert parser.detect_format(K8S_LINE) == "k8s_event"

    def test_syslog(self, parser):
        assert parser.detect_format(SYSLOG_LINE) == "syslog"

    def test_unknown(self, parser):
        assert parser.detect_format(GARBAGE) == "unknown"


class TestNginxAccess:
    def test_parse_returns_dict(self, parser):
        result = parser.parse(NGINX_LINE)
        assert result is not None
        assert isinstance(result, dict)

    def test_status_code(self, parser):
        result = parser.parse(NGINX_LINE)
        assert result["status_code"] == 500

    def test_error_level_for_5xx(self, parser):
        result = parser.parse(NGINX_LINE)
        assert result["level"] == "ERROR"

    def test_info_level_for_2xx(self, parser):
        result = parser.parse(NGINX_200)
        assert result["level"] == "INFO"

    def test_latency_converted_to_ms(self, parser):
        result = parser.parse(NGINX_LINE)
        assert result["latency_ms"] == pytest.approx(342.0, abs=1.0)

    def test_service_is_nginx(self, parser):
        result = parser.parse(NGINX_LINE)
        assert result["service"] == "nginx"

    def test_ip_in_host(self, parser):
        result = parser.parse(NGINX_LINE)
        assert result["host"] == "192.168.1.1"


class TestPythonApp:
    def test_parse_returns_dict(self, parser):
        result = parser.parse(PYTHON_LINE)
        assert result is not None

    def test_level_error(self, parser):
        result = parser.parse(PYTHON_LINE)
        assert result["level"] == "ERROR"

    def test_service_extracted(self, parser):
        result = parser.parse(PYTHON_LINE)
        assert result["service"] == "app"

    def test_message_preserved(self, parser):
        result = parser.parse(PYTHON_LINE)
        assert "Database connection failed" in result["message"]


class TestK8sEvent:
    def test_parse_returns_dict(self, parser):
        result = parser.parse(K8S_LINE)
        assert result is not None

    def test_level_warning(self, parser):
        result = parser.parse(K8S_LINE)
        assert result["level"] == "WARNING"

    def test_namespace_and_pod(self, parser):
        result = parser.parse(K8S_LINE)
        assert result["namespace"] == "default"
        assert result["pod"] == "api-pod-7f8b"


class TestEdgeCases:
    def test_unparseable_returns_none(self, parser):
        assert parser.parse(GARBAGE) is None

    def test_empty_string_returns_none(self, parser):
        assert parser.parse("") is None

    def test_whitespace_returns_none(self, parser):
        assert parser.parse("   \t  ") is None
