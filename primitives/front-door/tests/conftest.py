from __future__ import annotations

import pytest
from agentcore_front_door import MemoryStore
from front_door_fakes import FakeRuntime


@pytest.fixture
def runtime() -> FakeRuntime:
    return FakeRuntime()


@pytest.fixture
def store() -> MemoryStore:
    return MemoryStore()
