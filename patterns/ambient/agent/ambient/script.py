"""Offline script: an event payload that says 'change …' selects ``submit_change``."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from agentcore_agent import Script, ScriptRule

WORKER = "ambient-worker"


def _change_args(match: re.Match[str]) -> dict[str, Any]:
    summary = match.group("summary").strip()
    digest = hashlib.sha256(summary.encode()).hexdigest()[:16]
    return {"idempotency_key": f"change-{digest}", "actor_id": WORKER, "summary": summary}


def work_script() -> Script:
    return Script(
        rules=(
            ScriptRule(
                pattern=r"(?:please\s+)?change\s+(?P<summary>.+)",
                tool="submit_change",
                arguments=_change_args,
            ),
            ScriptRule(pattern=r"(?P<text>\S.*)", reply="queued:{text}"),
        )
    )
