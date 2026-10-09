"""Shell scripts parse, and deploy runs its gates before it changes anything."""

import subprocess
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


@pytest.mark.parametrize("name", ["deploy.sh", "teardown.sh", "sign-and-sbom.sh"])
def test_script_parses(name: str) -> None:
    subprocess.run(["bash", "-n", str(_SCRIPTS / name)], check=True)


def test_deploy_gates_come_before_any_change() -> None:
    text = (_SCRIPTS / "deploy.sh").read_text(encoding="utf-8")
    first_change = text.index("cdk@2 deploy")
    for gate in ("ps >/dev/null", '"${KIT[@]}" doctor', '"${KIT[@]}" production-check'):
        assert text.index(gate) < first_change, gate
    assert text.index("sign-and-sbom.sh") < text.index("agentcore deploy -y")


def test_teardown_keeps_going_after_a_failed_step() -> None:
    text = (_SCRIPTS / "teardown.sh").read_text(encoding="utf-8")
    assert "set -uo pipefail" in text
    assert "set -e" not in text
    assert text.index("agentcore remove all") < text.index("cdk@2 destroy")
