"""Allow/block fixtures against the offline pattern guard."""

from agentcore_eval.guardrails import PatternGuard, guardrail_evals, load_guardrail_fixtures

EVALS = guardrail_evals(PatternGuard(), load_guardrail_fixtures())
