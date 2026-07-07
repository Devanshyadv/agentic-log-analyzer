import subprocess
from pathlib import Path
from typing import Optional
from loguru import logger
from langchain_core.tools import tool

_ALLOWED_COMMANDS = frozenset([
    "ps aux",
    "netstat -an",
    "df -h",
    "free -m",
    "top -bn1",
    "cat /proc/meminfo",
    "uptime",
    "who",
    "last -n 5",
])

_memory: Optional[object] = None


def _get_memory():
    global _memory
    if _memory is None:
        from agent.incident_memory import IncidentMemory
        _memory = IncidentMemory()
        _memory.load_index()
    return _memory


@tool
def search_similar_incidents(anomaly_description: str) -> str:
    """Search the incident history database for past incidents similar to the given anomaly.
    Returns top 3 matching incidents with their root causes and resolutions."""
    mem = _get_memory()
    results = mem.retrieve_similar(anomaly_description, k=3)

    if not results:
        return "No similar incidents found in the database."

    lines = [f"Found {len(results)} similar incidents:"]
    for i, inc in enumerate(results, 1):
        lines.append(
            f"\n{i}. [{inc.get('id', '?')}] {inc['title']} ({inc.get('date', 'N/A')}) "
            f"[score={inc.get('similarity_score', 0):.2f}]:\n"
            f"   Symptoms: {str(inc.get('symptoms', ''))[:180]}\n"
            f"   Root cause: {str(inc.get('root_cause', ''))[:180]}\n"
            f"   Fix applied: {str(inc.get('fix_applied', ''))[:180]}\n"
            f"   Resolved in: {inc.get('time_to_resolve_minutes', '?')} minutes"
        )
    return "\n".join(lines)


@tool
def run_diagnostic(command: str) -> str:
    """Run a safe diagnostic shell command and return its output.
    Only these commands are allowed: ps aux, netstat -an, df -h, free -m,
    top -bn1, cat /proc/meminfo, uptime, who, last -n 5"""
    command = command.strip()
    if command not in _ALLOWED_COMMANDS:
        allowed = ", ".join(sorted(_ALLOWED_COMMANDS))
        return f"Command not allowed: '{command}'\nAllowed commands: {allowed}"
    try:
        result = subprocess.run(
            command.split(),
            capture_output=True,
            text=True,
            timeout=10,
            shell=False,
        )
        output = (result.stdout + result.stderr).strip()
        return output[:500] if len(output) > 500 else output
    except subprocess.TimeoutExpired:
        return "Command timed out after 10 seconds."
    except FileNotFoundError:
        return f"Command not available on this system: {command}"
    except Exception as e:
        return f"Error running diagnostic: {e}"


@tool
def get_service_runbook(service_name: str) -> str:
    """Retrieve troubleshooting runbook for a specific service.
    Available services: nginx, python_app, k8s"""
    _service_map = {
        "nginx": "nginx_runbook.txt",
        "python_app": "python_app_runbook.txt",
        "app": "python_app_runbook.txt",
        "k8s": "k8s_runbook.txt",
        "kubernetes": "k8s_runbook.txt",
    }
    filename = _service_map.get(service_name.lower().strip())
    if not filename:
        available = ", ".join(sorted(set(_service_map.keys())))
        return f"No runbook found for '{service_name}'. Available: {available}"

    runbook_path = Path("data/runbooks") / filename
    if not runbook_path.exists():
        return f"Runbook file not found at {runbook_path}"

    content = runbook_path.read_text(encoding="utf-8")
    return content[:800] if len(content) > 800 else content
