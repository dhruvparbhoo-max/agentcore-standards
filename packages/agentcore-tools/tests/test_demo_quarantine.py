"""The demo is a sample module, not the tools library root."""

import pytest


def test_package_root_refuses_the_demo() -> None:
    with pytest.raises(ImportError, match=r"agentcore_tools\.demo"):
        from agentcore_tools import DemoTools  # noqa: F401

    from agentcore_tools.demo import DemoTools as Demo

    assert Demo is not None
