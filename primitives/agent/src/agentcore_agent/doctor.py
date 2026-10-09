"""``doctor``: read-only checks before a local run or a deploy. It changes nothing.

Copied from aws-samples/sample-agentcore-enterprise-platform
``scripts/preflight.py`` (Apache-2.0): a fixed read-only allow-list of AWS CLI
calls, no shell, PASS/WARN/FAIL lines, and a closing "No AWS resources were
changed." Adapted to Python 3.12, Docker (``docker ps``), the AgentCore CLI,
and the pattern's own model ids and secret names. Secrets are checked with
``describe-secret``, so no value is ever read.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from agentcore_agent.config import PatternConfig
from agentcore_agent.environment import EnvironmentConfig
from agentcore_agent.secrets import secret_name

READ_ONLY_AWS_CALLS = frozenset(
    {
        ("sts", "get-caller-identity"),
        ("bedrock", "get-inference-profile"),
        ("bedrock", "get-foundation-model"),
        ("secretsmanager", "describe-secret"),
    }
)
PROFILE_PREFIXES = frozenset({"eu", "us", "apac", "global", "us-gov", "jp", "au", "ca"})


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


class CommandRunner:
    """Run a bounded command without a shell. Non-read-only AWS calls are refused."""

    def run(self, args: Sequence[str]) -> CommandResult:
        if len(args) >= 3 and args[0] == "aws" and (args[1], args[2]) not in READ_ONLY_AWS_CALLS:
            return CommandResult(1, stderr="blocked non-read-only AWS command")
        try:
            completed = subprocess.run(list(args), check=False, capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return CommandResult(1, stderr=type(exc).__name__)
        return CommandResult(completed.returncode, completed.stdout.strip(), completed.stderr.strip())


class Reporter:
    def __init__(self, echo: Callable[[str], None] = print) -> None:
        self.passed = 0
        self.warnings = 0
        self.failed = 0
        self._echo = echo

    def pass_(self, subject: str, detail: str) -> None:
        self.passed += 1
        self._echo(f"[PASS] {subject}: {detail}")

    def warn(self, subject: str, detail: str) -> None:
        self.warnings += 1
        self._echo(f"[WARN] {subject}: {detail}")

    def fail(self, subject: str, detail: str) -> None:
        self.failed += 1
        self._echo(f"[FAIL] {subject}: {detail}")

    def summary(self) -> int:
        self._echo("")
        self._echo(f"Summary: {self.passed} passed, {self.warnings} warning(s), {self.failed} failed.")
        self._echo("No AWS resources were changed.")
        return 1 if self.failed else 0


class Doctor:
    def __init__(
        self,
        *,
        config: PatternConfig | None,
        environment: EnvironmentConfig | None,
        secrets: Sequence[str] = (),
        runner: CommandRunner | None = None,
        reporter: Reporter | None = None,
        which: Callable[[str], str | None] = shutil.which,
        python_version: tuple[int, ...] = (sys.version_info.major, sys.version_info.minor),
        local_only: bool = False,
    ) -> None:
        self.config = config
        self.environment = environment
        self.secrets = tuple(secrets)
        self.runner = runner or CommandRunner()
        self.reporter = reporter or Reporter()
        self.which = which
        self.python_version = python_version
        self.local_only = local_only

    def run(self) -> int:
        self._local_tools()
        if not self.local_only and self._aws_identity():
            self._models()
            self._secrets()
        return self.reporter.summary()

    def _local_tools(self) -> None:
        major, minor = self.python_version[:2]
        if (major, minor) == (3, 12):
            self.reporter.pass_("Python", f"{major}.{minor}")
        else:
            self.reporter.fail("Python", f"{major}.{minor} is active; this repo uses Python 3.12")
        self._tool("uv", ("uv", "--version"))
        if self.which("docker"):
            result = self.runner.run(("docker", "ps"))
            if result.returncode == 0:
                self.reporter.pass_("Docker", "`docker ps` works")
            else:
                self.reporter.fail("Docker", "`docker ps` failed; start Docker Desktop, Colima, or Finch")
        elif self.which("finch"):
            result = self.runner.run(("finch", "ps"))
            if result.returncode == 0:
                self.reporter.pass_("Finch", "`finch ps` works")
            else:
                self.reporter.fail("Finch", "`finch ps` failed; run `finch vm start`")
        else:
            self.reporter.fail("Docker", "neither docker nor finch is installed")
        if self.local_only:
            return
        self._tool("Node.js", ("node", "--version"))
        self._tool("AgentCore CLI", ("agentcore", "--version"), executable="agentcore")
        self._tool("AWS CDK", ("cdk", "--version"), executable="cdk")
        self._tool("AWS CLI", ("aws", "--version"), executable="aws")

    def _tool(self, subject: str, args: tuple[str, ...], *, executable: str | None = None) -> None:
        command = executable or args[0]
        if not self.which(command):
            self.reporter.fail(subject, f"{command} is not installed")
            return
        result = self.runner.run(args)
        if result.returncode != 0:
            self.reporter.fail(subject, f"{command} could not report its version")
            return
        lines = (result.stdout or result.stderr).splitlines()
        self.reporter.pass_(subject, lines[0] if lines else "found")

    def _aws_identity(self) -> bool:
        if not self.which("aws"):
            return False
        result = self.runner.run(("aws", "sts", "get-caller-identity", "--output", "json"))
        if result.returncode != 0:
            self.reporter.fail("AWS identity", "no credentials; log in with `aws sso login` or set a profile")
            return False
        try:
            identity = json.loads(result.stdout)
        except ValueError:
            self.reporter.fail("AWS identity", "unreadable get-caller-identity output")
            return False
        self.reporter.pass_("AWS identity", f"account ending {str(identity.get('Account', ''))[-4:]}")
        return True

    def _models(self) -> None:
        if self.config is None:
            return
        region = self._region()
        model = self.config.section("model")
        for label in ("primary", "fallback"):
            model_id = str(model[label])
            call = ("get-foundation-model", "--model-identifier")
            if model_id.split(".", 1)[0] in PROFILE_PREFIXES:
                call = ("get-inference-profile", "--inference-profile-identifier")
            result = self.runner.run(("aws", "bedrock", call[0], call[1], model_id, "--region", region))
            if result.returncode == 0:
                self.reporter.pass_(f"Model {label}", model_id)
            else:
                self.reporter.fail(f"Model {label}", f"{model_id} is not available in {region}")

    def _secrets(self) -> None:
        if self.environment is None:
            return
        for name in self.secrets:
            full = secret_name(self.environment.secrets_prefix, name)
            result = self.runner.run(
                ("aws", "secretsmanager", "describe-secret", "--secret-id", full, "--region", self._region())
            )
            if result.returncode == 0:
                self.reporter.pass_("Secret", full)
            else:
                self.reporter.fail("Secret", f"{full} does not exist or is not readable")

    def _region(self) -> str:
        if self.environment is not None:
            return self.environment.region
        if self.config is not None:
            return str(self.config.section("data")["region"])
        return "eu-west-2"
