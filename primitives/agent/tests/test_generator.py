from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
from agentcore_agent import load_pattern
from agentcore_agent.agentcore_json import (
    render_agentcore_json,
    render_deploy_project,
    render_harness_json,
    stale_generated,
    write_generated,
)
from agentcore_agent.environment import load_environment
from agentcore_agent.release import build_digest, release_id
from agentcore_agent.stack_outputs import (
    FALLBACK_PROFILE,
    MODEL_PROFILE,
    NETWORK_SECURITY_GROUPS,
    NETWORK_SUBNETS,
    NETWORK_VPC,
    load_outputs,
    model_aliases,
    network_config,
)

REPO = Path(__file__).resolve().parents[3]
CLI = shutil.which("agentcore")
DIGEST = "sha256:" + "a" * 64


def _validate(project: Path) -> None:
    if CLI is None:
        pytest.skip("AgentCore CLI (@aws/agentcore) is not installed")
    result = subprocess.run([CLI, "validate", "-d", str(project)], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr


def test_runtime_project_has_no_account_or_arn(make_pattern: Callable[..., Path]) -> None:
    config = load_pattern(make_pattern())
    text = json.dumps(render_agentcore_json(config))
    assert "arn:" not in text
    assert "sha256:" not in text


def test_memory_pattern_declares_a_memory(make_pattern: Callable[..., Path], tmp_path: Path) -> None:
    config = load_pattern(make_pattern(memory={"enabled": True, "write_policy": "validated"}))
    document = render_agentcore_json(config)
    assert document["memories"][0]["strategies"][0]["type"] == "SEMANTIC"
    write_generated(config)
    _validate(config.root)


def test_harness_pattern_writes_harness_files(make_pattern: Callable[..., Path]) -> None:
    config = load_pattern(make_pattern(framework="harness"))
    written = {path.name for path in write_generated(config)}
    assert {"agentcore.json", "harness.json", "system-prompt.md"} <= written
    assert render_agentcore_json(config)["runtimes"] == []
    spec = render_harness_json(config)
    assert spec["maxIterations"] == 8
    assert spec["tools"] == []
    assert spec["memory"] == {"mode": "disabled"}
    _validate(config.root)


def test_stale_detection(make_pattern: Callable[..., Path]) -> None:
    config = load_pattern(make_pattern())
    assert stale_generated(config) == ["agentcore/agentcore.json", "agentcore/aws-targets.json"]
    write_generated(config)
    assert stale_generated(config) == []


def test_deploy_copy_has_the_release_and_endpoint(make_pattern: Callable[..., Path], tmp_path: Path) -> None:
    config = load_pattern(make_pattern())
    release = release_id(config, image_digest=DIGEST)
    path = render_deploy_project(
        config,
        environment=load_environment("dev", repo_root=REPO),
        destination=tmp_path / "deploy",
        repo_root=REPO,
        account="111111111111",
        release_id=release,
        endpoint_version=3,
    )
    runtime = json.loads(path.read_text(encoding="utf-8"))["runtimes"][0]
    variables = {item["name"]: item["value"] for item in runtime["envVars"]}
    assert variables["AGENTCORE_RELEASE_ID"] == release
    assert runtime["endpoints"] == {"DEV": {"version": 3}}
    assert Path(runtime["buildContextPath"]).is_absolute()
    targets = json.loads((path.parent / "aws-targets.json").read_text(encoding="utf-8"))
    assert targets[0]["region"] == "eu-west-2"


def test_vpc_deploy_needs_the_foundation_outputs(make_pattern: Callable[..., Path], tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="VPC"):
        render_deploy_project(
            load_pattern(make_pattern()),
            environment=load_environment("prod", repo_root=REPO),
            destination=tmp_path / "deploy",
            repo_root=REPO,
            account="111111111111",
            release_id="rel-x",
        )


def test_deploy_copy_takes_network_and_model_profiles(make_pattern: Callable[..., Path], tmp_path: Path) -> None:
    arn = "arn:" + "aws:bedrock:eu-west-2:111111111111:application-inference-profile/abc"
    fallback = "arn:" + "aws:bedrock:eu-west-2:111111111111:application-inference-profile/def"
    path = render_deploy_project(
        load_pattern(make_pattern()),
        environment=load_environment("prod", repo_root=REPO),
        destination=tmp_path / "deploy",
        repo_root=REPO,
        account="111111111111",
        release_id="rel-x",
        outputs={
            MODEL_PROFILE: arn,
            FALLBACK_PROFILE: fallback,
            NETWORK_SUBNETS: "subnet-aaa,subnet-bbb",
            NETWORK_SECURITY_GROUPS: "sg-aaa",
            NETWORK_VPC: "vpc-aaa",
        },
    )
    runtime = json.loads(path.read_text(encoding="utf-8"))["runtimes"][0]
    variables = {item["name"]: item["value"] for item in runtime["envVars"]}
    assert runtime["networkMode"] == "VPC"
    assert runtime["networkConfig"] == {
        "subnets": ["subnet-aaa", "subnet-bbb"],
        "securityGroups": ["sg-aaa"],
        "vpcId": "vpc-aaa",
    }
    assert variables["AGENTCORE_MODEL_PROFILE_ARN"] == arn
    assert variables["AGENTCORE_FALLBACK_PROFILE_ARN"] == fallback


def test_stack_outputs_merge_and_alias_profiles(tmp_path: Path) -> None:
    first = tmp_path / "a.json"
    first.write_text(json.dumps({"StackA": {MODEL_PROFILE: "arn:p", NETWORK_SUBNETS: "subnet-1"}}), encoding="utf-8")
    second = tmp_path / "b.json"
    second.write_text(
        json.dumps({"StackB": {FALLBACK_PROFILE: "arn:f", NETWORK_SECURITY_GROUPS: "sg-1", NETWORK_VPC: "vpc-1"}}),
        encoding="utf-8",
    )
    outputs = load_outputs(first, second)
    assert network_config(outputs) == {"subnets": ["subnet-1"], "securityGroups": ["sg-1"], "vpcId": "vpc-1"}
    assert model_aliases(outputs, primary="eu.primary", fallback="eu.fallback") == {
        "arn:p": "eu.primary",
        "arn:f": "eu.fallback",
    }


def test_deploy_copy_refuses_a_bad_account(make_pattern: Callable[..., Path], tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="12-digit"):
        render_deploy_project(
            load_pattern(make_pattern()),
            environment=load_environment("dev", repo_root=REPO),
            destination=tmp_path,
            repo_root=REPO,
            account="dev",
            release_id="rel-x",
        )


def test_release_id_changes_with_the_prompt(make_pattern: Callable[..., Path]) -> None:
    folder = make_pattern()
    first = release_id(load_pattern(folder), image_digest=DIGEST)
    (folder / "prompts" / "system.md").write_text("A different prompt.\n", encoding="utf-8")
    assert release_id(load_pattern(folder), image_digest=DIGEST) != first
    with pytest.raises(ValueError, match="digest"):
        release_id(load_pattern(folder), image_digest="latest")


def test_build_digest_tracks_source_and_base(make_pattern: Callable[..., Path], tmp_path: Path) -> None:
    folder = make_pattern()
    config = load_pattern(folder)
    root = folder.parents[1]
    names = [str(path.relative_to(root)) for path in folder.rglob("*") if path.is_file()]

    def listed(repo_root: Path, paths: object) -> list[str]:
        return names

    first = build_digest(config, repo_root=root, base_digest=DIGEST, list_files=listed)
    assert first.startswith("sha256:")
    assert build_digest(config, repo_root=root, base_digest="sha256:" + "b" * 64, list_files=listed) != first
    (folder / "agent" / "main.py").write_text("print('changed')\n", encoding="utf-8")
    assert build_digest(config, repo_root=root, base_digest=DIGEST, list_files=listed) != first
    with pytest.raises(ValueError, match="digest"):
        build_digest(config, repo_root=root, base_digest="latest", list_files=listed)


def test_build_digest_reads_git_for_the_template() -> None:
    config = load_pattern(REPO / "patterns" / "_template")
    assert build_digest(config, repo_root=REPO, base_digest=DIGEST) == build_digest(
        config, repo_root=REPO, base_digest=DIGEST
    )
