"""Write a redacted evidence bundle next to a verdict.

Bundles keep spans, structured logs, and the verdict. They must not contain
resource ARNs or secret material.
"""

import json
from pathlib import Path
from typing import Any

from agentcore_eval.harness import TraceBundle, assert_no_resource_arn
from agentcore_eval.verdict import Verdict


def write_evidence(directory: Path, verdict: Verdict, bundle: TraceBundle) -> Path:
    """Write ``<eval-name>.json`` and return the path."""
    directory.mkdir(parents=True, exist_ok=True)
    body: dict[str, Any] = {
        "agent_version": verdict.agent_version,
        "eval": verdict.eval_name,
        "failures": list(verdict.failures),
        "logs": [dict(item) for item in bundle.logs],
        "notes": list(verdict.notes),
        "spans": [span.as_dict() for span in bundle.spans],
        "status": verdict.status.value,
    }
    if verdict.tags is not None:
        body.update(verdict.tags.as_dict())
    text = json.dumps(body, indent=2, sort_keys=True) + "\n"
    assert_no_resource_arn(text)
    path = directory / f"{verdict.eval_name}.json"
    path.write_text(text, encoding="utf-8")
    return path
