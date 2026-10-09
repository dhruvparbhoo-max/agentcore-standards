"""Replay a pattern's ``events/*.json`` against a running agent container.

``make local`` starts the compose stack and then posts each sample event to
``/invocations`` with the session and actor headers the front door would set.
An event's ``expect`` block names the status and text the reply must carry.
"""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agentcore_agent.config import ACTOR_HEADER
from agentcore_agent.schema import SESSION_HEADER

Post = Callable[[str, bytes, Mapping[str, str]], Mapping[str, Any]]


@dataclass(frozen=True)
class EventOutcome:
    name: str
    problems: tuple[str, ...]
    body: Mapping[str, Any]

    @property
    def passed(self) -> bool:
        return not self.problems


def http_post(url: str, data: bytes, headers: Mapping[str, str]) -> Mapping[str, Any]:
    request = urllib.request.Request(url, data=data, headers=dict(headers), method="POST")
    with urllib.request.urlopen(request, timeout=60) as response:
        body = json.loads(response.read().decode("utf-8"))
    return body if isinstance(body, Mapping) else {"result": body}


def turn_events(folder: Path) -> list[Path]:
    """Events that carry a front door ``payload``. Queue and schedule events belong to their Lambda."""
    found: list[Path] = []
    for path in sorted((folder / "events").glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, Mapping) and isinstance(raw.get("payload"), Mapping):
            found.append(path)
    return found


def post_event(path: Path, url: str, post: Post = http_post) -> EventOutcome:
    raw = json.loads(path.read_text(encoding="utf-8"))
    headers = {
        "Content-Type": "application/json",
        SESSION_HEADER: str(raw["session_id"]),
        ACTOR_HEADER: str(raw["actor_id"]),
    }
    body = post(url.rstrip("/") + "/invocations", json.dumps(raw["payload"]).encode("utf-8"), headers)
    return EventOutcome(path.name, tuple(_problems(raw.get("expect") or {}, body)), body)


def _problems(expect: Mapping[str, Any], body: Mapping[str, Any]) -> list[str]:
    problems: list[str] = []
    status = expect.get("status")
    if status is not None and body.get("status") != status:
        problems.append(f"status {body.get('status')!r}, expected {status!r}")
    text = str(body.get("result", "")).lower()
    contains = expect.get("contains")
    if contains is not None and str(contains).lower() not in text:
        problems.append(f"reply does not contain {contains!r}")
    excludes = expect.get("excludes")
    if excludes is not None and str(excludes).lower() in text:
        problems.append(f"reply contains {excludes!r}")
    return problems
