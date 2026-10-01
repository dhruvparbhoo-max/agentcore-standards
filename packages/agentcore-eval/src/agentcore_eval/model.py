"""Task definition for one eval."""

from collections.abc import Callable

from agentcore_eval.harness import InvokeResult, RuntimeHarness, SessionHandle


class EvalContext:
    """Mutable state shared by setup, act, and assert for a single run."""

    def __init__(self, *, agent_version: str, actor_id: str = "actor-default") -> None:
        self.agent_version = agent_version
        self.actor_id = actor_id
        self.session: SessionHandle | None = None
        self.results: list[InvokeResult] = []
        self.notes: list[str] = []


Hook = Callable[[RuntimeHarness, EvalContext], None]


class Eval:
    """A named task. ``assert_`` raises ``AssertionError`` when the observable outcome is wrong."""

    def __init__(
        self,
        *,
        name: str,
        rubric: str,
        act: Hook,
        assert_: Hook,
        setup: Hook | None = None,
    ) -> None:
        if not name or any(char.isspace() for char in name):
            raise ValueError("eval name must be a non-empty slug without spaces")
        if not rubric.strip():
            raise ValueError("rubric is required")
        self.name = name
        self.rubric = rubric
        self.act = act
        self.assert_ = assert_
        self.setup = setup
