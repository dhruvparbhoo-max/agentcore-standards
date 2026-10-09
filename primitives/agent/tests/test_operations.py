"""doctor, verify, logging, lifecycle, and secrets."""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from agentcore_agent import load_pattern
from agentcore_agent import secrets as secret_module
from agentcore_agent.doctor import CommandResult, Doctor, Reporter
from agentcore_agent.environment import load_environment
from agentcore_agent.lifecycle import Checkpoint, run_in_background
from agentcore_agent.logging import CorrelatedLogger, StructuredJsonFormatter, mask
from agentcore_agent.verify import verify_runtime

REPO = Path(__file__).resolve().parents[3]


class FakeRunner:
    def __init__(self, failing: Sequence[str] = ()) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.failing = set(failing)

    def run(self, args: Sequence[str]) -> CommandResult:
        self.calls.append(tuple(args))
        if args[0] in self.failing or " ".join(args[:3]) in self.failing:
            return CommandResult(1, stderr="nope")
        if args[:3] == ("aws", "sts", "get-caller-identity"):
            return CommandResult(0, stdout=json.dumps({"Account": "111111111111"}))
        return CommandResult(0, stdout=f"{args[0]} 1.0")


def _doctor(make_pattern: Callable[..., Path], runner: FakeRunner, lines: list[str], **kwargs: Any) -> Doctor:
    return Doctor(
        config=load_pattern(make_pattern()),
        environment=load_environment("dev", repo_root=REPO),
        secrets=["webhook-signing-key"],
        runner=runner,  # type: ignore[arg-type]
        reporter=Reporter(lines.append),
        which=lambda name: f"/usr/bin/{name}",
        python_version=(3, 12, 0),
        **kwargs,
    )


def test_doctor_passes_and_changes_nothing(make_pattern: Callable[..., Path]) -> None:
    lines: list[str] = []
    runner = FakeRunner()
    assert _doctor(make_pattern, runner, lines).run() == 0
    assert ("docker", "ps") in runner.calls
    assert lines[-1] == "No AWS resources were changed."
    aws_calls = {(call[1], call[2]) for call in runner.calls if call[0] == "aws" and len(call) > 2}
    assert aws_calls <= {
        ("sts", "get-caller-identity"),
        ("bedrock", "get-inference-profile"),
        ("secretsmanager", "describe-secret"),
    }
    assert any("agentcore/dev/webhook-signing-key" in line for line in lines)


def test_doctor_fails_when_docker_ps_fails(make_pattern: Callable[..., Path]) -> None:
    lines: list[str] = []
    assert _doctor(make_pattern, FakeRunner(failing=["docker"]), lines, local_only=True).run() == 1
    assert any(line.startswith("[FAIL] Docker") for line in lines)


def test_doctor_runner_blocks_mutations() -> None:
    from agentcore_agent.doctor import CommandRunner

    result = CommandRunner().run(["aws", "secretsmanager", "put-secret-value", "--secret-id", "x"])
    assert result.returncode == 1
    assert "blocked" in result.stderr


class FakeControl:
    def __init__(self, **overrides: Any) -> None:
        self.runtime: dict[str, Any] = {
            "status": "READY",
            "agentRuntimeVersion": "4",
            "requestHeaderConfiguration": {
                "requestHeaderAllowlist": [
                    "Authorization",
                    "X-Amzn-Bedrock-AgentCore-Runtime-Custom-Actor-Id",
                ]
            },
            "lifecycleConfiguration": {"idleRuntimeSessionTimeout": 300, "maxLifetime": 1800},
            "protocolConfiguration": {"serverProtocol": "HTTP"},
            "environmentVariables": {"AGENTCORE_RELEASE_ID": "rel-1", "AGENTCORE_PATTERN": "demo-pattern"},
            "agentRuntimeArtifact": {"containerConfiguration": {"containerUri": "repo@sha256:" + "b" * 64}},
        }
        self.runtime.update(overrides)

    def get_agent_runtime(self, **kwargs: Any) -> Mapping[str, Any]:
        return self.runtime

    def get_agent_runtime_endpoint(self, **kwargs: Any) -> Mapping[str, Any]:
        return {"status": "READY", "liveVersion": "4"}


def test_verify_passes_on_a_matching_runtime(make_pattern: Callable[..., Path]) -> None:
    config = load_pattern(make_pattern())
    assert verify_runtime(config, FakeControl(), runtime_id="r", release_id="rel-1", endpoint="DEV") == []


def test_verify_catches_a_dropped_allowlist(make_pattern: Callable[..., Path]) -> None:
    config = load_pattern(make_pattern())
    control = FakeControl(requestHeaderConfiguration={})
    problems = verify_runtime(config, control, runtime_id="r", release_id="rel-1", endpoint="DEV")
    assert any(problem.startswith("requestHeaderAllowlist") for problem in problems)


def test_verify_catches_a_tag_instead_of_a_digest(make_pattern: Callable[..., Path]) -> None:
    config = load_pattern(make_pattern())
    control = FakeControl(agentRuntimeArtifact={"containerConfiguration": {"containerUri": "repo:latest"}})
    problems = verify_runtime(config, control, runtime_id="r", release_id="rel-1", endpoint="DEV")
    assert "containerUri: pinned by digest" in problems


def _record(message: str, **extra: Any) -> logging.LogRecord:
    record = logging.LogRecord("t", logging.INFO, __file__, 1, message, None, None)
    record._extra = extra
    return record


def test_log_line_has_hashed_session_and_user() -> None:
    formatter = StructuredJsonFormatter(component="demo", session_id="s" * 40, user_id="user-1")
    line = json.loads(formatter.format(_record("turn finished", status="completed")))
    assert line["user_id"] == "user-1"
    assert line["session_id"] != "s" * 40
    assert len(line["session_id"]) == 32
    assert line["status"] == "completed"


def test_log_line_drops_prompts_and_masks_pii() -> None:
    formatter = StructuredJsonFormatter()
    line = json.loads(formatter.format(_record("mail me at bob@example.com", prompt="secret plan", tool="x")))
    assert "prompt" not in line
    assert "bob@example.com" not in line["message"]
    assert mask("call bob@example.com") != "call bob@example.com"


def test_correlated_logger_passes_extra() -> None:
    records: list[logging.LogRecord] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    base = logging.getLogger("test-correlated")
    base.addHandler(Capture())
    base.setLevel(logging.INFO)
    CorrelatedLogger(base, {}).info("x", extra={"tool": "lookup"})
    assert records[0]._extra == {"tool": "lookup"}  # type: ignore[attr-defined]


class FakeApp:
    def __init__(self) -> None:
        self.active: set[int] = set()
        self.next = 0

    def add_async_task(self, name: str, metadata: dict[str, Any] | None = None) -> int:
        self.next += 1
        self.active.add(self.next)
        return self.next

    def complete_async_task(self, task_id: int) -> bool:
        self.active.discard(task_id)
        return True


def test_background_task_is_busy_until_done() -> None:
    app = FakeApp()
    release = threading.Event()
    results: list[bool] = []
    task_id, thread = run_in_background(app, "job", release.wait, on_done=results.append)
    assert task_id in app.active
    release.set()
    thread.join(timeout=5)
    assert app.active == set()
    assert results == [True]


def test_background_task_completes_even_when_work_fails() -> None:
    app = FakeApp()

    def boom() -> None:
        raise RuntimeError("x")

    results: list[bool] = []
    _, thread = run_in_background(app, "job", boom, on_done=results.append)
    thread.join(timeout=5)
    assert app.active == set()
    assert results == [False]


def test_checkpoint_is_atomic(tmp_path: Path) -> None:
    checkpoint = Checkpoint(tmp_path / "state")
    assert checkpoint.load() is None
    checkpoint.save({"step": 2})
    assert checkpoint.load() == {"step": 2}
    assert not (tmp_path / "state" / "state.json.tmp").exists()
    checkpoint.path.write_text("{broken", encoding="utf-8")
    assert checkpoint.load() is None


class FakeSecrets:
    def __init__(self) -> None:
        self.calls = 0
        self.fail = False

    def get_secret_value(self, SecretId: str) -> dict[str, str]:
        self.calls += 1
        if self.fail:
            raise RuntimeError("throttled")
        return {"SecretString": f"value-{self.calls}"}


def test_secret_is_cached_and_errors_are_not(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeSecrets()
    secret_module.set_client(client)
    try:
        assert secret_module.get_secret("agentcore/dev/x") == "value-1"
        assert secret_module.get_secret("agentcore/dev/x") == "value-1"
        assert client.calls == 1
        secret_module.clear_cache()
        client.fail = True
        with pytest.raises(RuntimeError):
            secret_module.get_secret("agentcore/dev/x")
        client.fail = False
        assert secret_module.get_secret("agentcore/dev/x") == "value-3"
    finally:
        secret_module.set_client(None)


def test_secret_names_stay_under_the_prefix() -> None:
    assert secret_module.secret_name("agentcore/dev", "key") == "agentcore/dev/key"
    with pytest.raises(ValueError):
        secret_module.secret_name("agentcore/dev", "../prod/key")


def test_post_event_sends_front_door_headers_and_checks_expect() -> None:
    from agentcore_agent.config import ACTOR_HEADER
    from agentcore_agent.events import post_event, turn_events
    from agentcore_agent.schema import SESSION_HEADER

    sent: list[tuple[str, Mapping[str, str]]] = []

    def post(url: str, data: bytes, headers: Mapping[str, str]) -> Mapping[str, Any]:
        sent.append((url, headers))
        return {"status": "completed", "result": json.loads(data)["prompt"]}

    paths = turn_events(REPO / "patterns" / "_template")
    assert [path.name for path in paths] == ["hello.json"]
    outcome = post_event(paths[0], "http://localhost:8080/", post)
    assert outcome.passed
    url, headers = sent[0]
    assert url == "http://localhost:8080/invocations"
    assert headers[ACTOR_HEADER] == "actor-template-user"
    assert len(headers[SESSION_HEADER]) >= 33


def test_post_event_reports_a_wrong_reply(tmp_path: Path) -> None:
    from agentcore_agent.events import post_event

    (tmp_path / "events").mkdir()
    event = tmp_path / "events" / "turn.json"
    event.write_text(
        json.dumps(
            {
                "session_id": "s" * 40,
                "actor_id": "a",
                "payload": {"prompt": "x"},
                "expect": {"status": "completed", "contains": "pong", "excludes": "secret"},
            }
        ),
        encoding="utf-8",
    )
    outcome = post_event(event, "http://x", lambda *_: {"status": "blocked", "result": "the secret"})
    assert outcome.problems == (
        "status 'blocked', expected 'completed'",
        "reply does not contain 'pong'",
        "reply contains 'secret'",
    )
