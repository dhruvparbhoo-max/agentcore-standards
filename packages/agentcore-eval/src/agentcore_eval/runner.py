"""Run one eval or a directory of eval modules.

A module exports ``EVAL`` or ``EVALS``. The runner always captures traces and
tears the session down, including when the assertion fails, so a FAIL still
has an evidence file.
"""

import importlib.util
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

from agentcore_eval.evidence import write_evidence
from agentcore_eval.harness import RuntimeHarness, TraceBundle
from agentcore_eval.model import Eval, EvalContext
from agentcore_eval.verdict import Report, Verdict, VerdictStatus


def run_eval(
    evaluation: Eval,
    *,
    agent_version: str,
    harness: RuntimeHarness,
    evidence_dir: Path,
) -> Verdict:
    """Execute ``evaluation`` and write an evidence bundle."""
    ctx = EvalContext(agent_version=agent_version)
    failures: list[str] = []
    try:
        if evaluation.setup is not None:
            evaluation.setup(harness, ctx)
        evaluation.act(harness, ctx)
        evaluation.assert_(harness, ctx)
    except AssertionError as exc:
        failures.append(str(exc) or evaluation.name)
    except Exception as exc:
        failures.append(f"{type(exc).__name__}: {exc}")

    bundle = TraceBundle(session_id="", spans=(), logs=())
    if ctx.session is not None:
        try:
            bundle = harness.capture_traces(ctx.session)
        except Exception as exc:
            failures.append(f"capture_traces failed: {type(exc).__name__}: {exc}")
        try:
            harness.tear_down(ctx.session)
        except Exception as exc:
            failures.append(f"tear_down failed: {type(exc).__name__}: {exc}")

    if failures:
        status = VerdictStatus.FAIL
    elif ctx.notes:
        status = VerdictStatus.PASS_NOTES
    else:
        status = VerdictStatus.PASS

    verdict = Verdict(
        status=status,
        eval_name=evaluation.name,
        agent_version=agent_version,
        notes=tuple(ctx.notes),
        failures=tuple(failures),
        evidence_path=None,
    )
    path = write_evidence(evidence_dir, verdict, bundle)
    verdict.evidence_path = path
    return verdict


def run_suite(
    path: Path,
    *,
    harness_factory: Callable[[], RuntimeHarness],
    agent_version: str,
    evidence_dir: Path,
) -> Report:
    """Run every eval exported by ``path`` (a module file or a directory)."""
    verdicts = tuple(
        run_eval(
            evaluation,
            agent_version=agent_version,
            harness=harness_factory(),
            evidence_dir=evidence_dir,
        )
        for evaluation in load_evals(path)
    )
    return Report(verdicts)


def load_evals(path: Path) -> tuple[Eval, ...]:
    """Load ``EVAL`` / ``EVALS`` from a Python file or a directory of files."""
    if path.is_file():
        files = [path]
    elif path.is_dir():
        files = sorted(
            item for item in path.glob("*.py") if item.name != "__init__.py" and not item.name.startswith("_")
        )
    else:
        raise ValueError(f"eval path does not exist: {path}")

    found: list[Eval] = []
    for file in files:
        module = _load_module(file)
        exported = getattr(module, "EVALS", None)
        if exported is None:
            single = getattr(module, "EVAL", None)
            exported = () if single is None else (single,)
        for item in exported:
            if not isinstance(item, Eval):
                raise TypeError(f"{file} exported a non-Eval object")
            found.append(item)
    if not found:
        raise ValueError(f"no EVAL or EVALS in {path}")
    return tuple(found)


def _load_module(path: Path) -> ModuleType:
    name = f"agentcore_eval_suite_{path.stem}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load eval module {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
