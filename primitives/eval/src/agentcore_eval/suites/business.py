"""Business golden scenarios. The harness factory must call ``BusinessStub``."""

from agentcore_eval.golden import dataset_evals, load_golden_dataset

EVALS = dataset_evals(load_golden_dataset())
