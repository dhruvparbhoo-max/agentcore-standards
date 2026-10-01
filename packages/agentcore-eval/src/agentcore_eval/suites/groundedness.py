"""Answer-versus-sources cases against the lexical scorer."""

from agentcore_eval.groundedness import LexicalGroundednessScorer, groundedness_evals, load_groundedness_pack

EVALS = groundedness_evals(LexicalGroundednessScorer(), load_groundedness_pack())
