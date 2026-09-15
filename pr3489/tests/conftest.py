import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from cardlab.lab import ACTIVE, CMD, REQ, TASK, Lab
from cardlab.machine import ELF, REPO

EVIDENCE = {}
OUTCOMES = {}


@pytest.fixture
def lab(request):
    value = Lab()
    yield value
    EVIDENCE[request.node.nodeid] = {
        "commands_dispatched": sorted(value.executed_commands),
        "requests_dispatched": sorted(value.request_types),
        "active_types_observed": sorted(value.active_types),
        "tasks_dispatched": sorted(value.task_types),
        "functions_executed": dict(sorted(value.m.visited.items())),
        "card_calls": sorted({e[0] for e in value.card.events if e[0] != "complete"}),
        "hsd_callbacks": value.m.callbacks,
        "lb_callbacks": value.m.lb_callbacks,
    }
    value.m.check_canaries()


def pytest_runtest_logreport(report):
    if report.failed:
        OUTCOMES[report.nodeid] = "failed"
    elif report.when == "call" and report.nodeid not in OUTCOMES:
        OUTCOMES[report.nodeid] = report.outcome


def pytest_sessionfinish(session, exitstatus):
    directory = Path(__file__).resolve().parents[1] / "reports"
    directory.mkdir(exist_ok=True)
    for node, data in EVIDENCE.items():
        data["outcome"] = OUTCOMES.get(node, "unknown")
    provenance_file = REPO / "provenance.json"
    provenance = (
        json.loads(provenance_file.read_text())
        if provenance_file.exists()
        else {
            "source_checkout": str(REPO),
            "commit": subprocess.check_output(
                ["git", "-C", str(REPO), "rev-parse", "HEAD"], text=True
            ).strip(),
            "elf_sha256": hashlib.sha256(ELF.read_bytes()).hexdigest(),
        }
    )
    root = Path(__file__).resolve().parents[1]
    harness_files = sorted(
        list((root / "cardlab").glob("*.py"))
        + list((root / "tests").glob("*.py"))
        + [root / "audit.py", root / "requirements.txt", root / "pyproject.toml"]
    )
    provenance["harness_sha256"] = {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in harness_files
    }
    report = {
        "exit_status": exitstatus,
        "provenance": provenance,
        "outcomes": OUTCOMES,
        "enums": {"command": CMD, "request": REQ, "active": ACTIVE, "task": TASK},
        "tests": EVIDENCE,
    }
    (directory / "evidence.json").write_text(json.dumps(report, indent=2) + "\n")
