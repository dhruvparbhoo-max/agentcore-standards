"""Tracer selection.

Inside an eval harness the in-memory binding captures spans for ``capture_traces``.
On AgentCore Runtime the binding is unset and spans use the process tracer
provider (ADOT, when the service installs it).
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


class TracerBinding:
    """In-memory tracer provider for one eval session."""

    def __init__(self) -> None:
        self._exporter = InMemorySpanExporter()
        self._provider = TracerProvider()
        self._provider.add_span_processor(SimpleSpanProcessor(self._exporter))

    def tracer(self) -> trace.Tracer:
        return self._provider.get_tracer("agentcore.tracing")

    def finished(self) -> tuple[ReadableSpan, ...]:
        return tuple(self._exporter.get_finished_spans())


_binding: ContextVar[TracerBinding | None] = ContextVar("agentcore_tracer_binding", default=None)


def get_tracer() -> trace.Tracer:
    """Return the active eval binding, or the process tracer when unbound."""
    binding = _binding.get()
    if binding is None:
        return trace.get_tracer("agentcore.tracing")
    return binding.tracer()


@contextmanager
def use_binding(binding: TracerBinding) -> Iterator[None]:
    """Make ``binding`` the tracer for the current context."""
    token = _binding.set(binding)
    try:
        yield
    finally:
        _binding.reset(token)
