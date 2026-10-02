"""Fresh desk and hosted factory around each test."""

from collections.abc import Iterator

import pytest
from agent_with_tools.approvals import reset_approvals
from agent_with_tools.billing import reset_desk
from agent_with_tools.entrypoint import reset_agent_factory
from agent_with_tools.recovered import reset_recovery
from agent_with_tools.shelf import reset_shelf


@pytest.fixture(autouse=True)
def _fresh_desk() -> Iterator[None]:
    reset_desk()
    reset_agent_factory()
    reset_approvals()
    reset_recovery()
    reset_shelf()
    yield
    reset_desk()
    reset_agent_factory()
    reset_approvals()
    reset_recovery()
    reset_shelf()
