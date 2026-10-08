"""Lexical groundedness scores and the assert hook."""

import pytest
from agentcore_eval import assert_groundedness, load_groundedness_pack
from agentcore_eval.groundedness import LexicalGroundednessScorer


def test_each_case_matches_its_label() -> None:
    pack = load_groundedness_pack()
    scorer = LexicalGroundednessScorer()
    labels = {case.expect for case in pack.cases}
    assert labels == {"supported", "unsupported", "contradicted", "abstain"}
    for case in pack.cases:
        score = scorer.score(case, pack.rubric)
        assert_groundedness(score, expect=case.expect, minimum=pack.rubric.minimum_score)


def test_invented_balance_is_not_supported() -> None:
    pack = load_groundedness_pack()
    invented = next(case for case in pack.cases if case.expect == "unsupported")
    score = LexicalGroundednessScorer().score(invented, pack.rubric)
    with pytest.raises(AssertionError):
        assert_groundedness(score, expect="supported", minimum=pack.rubric.minimum_score)
