"""Trusted retrieve wrapper: tenant and role come from the verified login, never from the model.

There is no ``search_policies`` tool. The pattern calls this wrapper with the
user's question, filters the corpus by the actor's tenant and role, then either
returns citations or the empty sentence. The lexical retrieve is
``agentcore_tools.retrieve.Corpus`` (the local stand-in for a Gateway
knowledge-base target). A live deploy points the same wrapper at the Gateway
target; the filter still comes from the login.

The fixture set is deliberately messy: two leave policies that disagree, a
licence-refund note that shares the word "refund" with expenses, and a
second tenant so a wrong filter would leak. Copied in spirit from
aws-samples/sample-eval-first-building-enterprise-agents-with-agentcore
(MIT-0) and the tenant filter in aws-samples/sample-agentcore-and-multitenancy-blog.
"""

from __future__ import annotations

from dataclasses import dataclass

from agentcore_agent.untrusted import wrap
from agentcore_tools.retrieve import Citation, Corpus, Passage

EMPTY = "I couldn't find this in the policies"

# actor id the front door forwards: "{tenant}/{role}/{user}"
_ROLES = {"employee": ("employee",), "finance": ("employee", "finance"), "admin": ("employee", "finance", "admin")}


@dataclass(frozen=True)
class Actor:
    tenant: str
    role: str
    user: str

    @classmethod
    def parse(cls, actor_id: str) -> Actor:
        parts = [part for part in actor_id.split("/") if part]
        if len(parts) != 3:
            raise ValueError("actor id must be tenant/role/user from the verified login")
        tenant, role, user = parts
        if role not in _ROLES:
            raise ValueError(f"unknown role {role!r}")
        return cls(tenant=tenant, role=role, user=user)


@dataclass(frozen=True)
class PolicyDoc:
    passage_id: str
    title: str
    tenant: str
    roles: tuple[str, ...]
    text: str


# Deliberately messy: conflicts, a tempting wrong source, and a second tenant.
POLICIES: tuple[PolicyDoc, ...] = (
    PolicyDoc(
        "HR-Leave-2024",
        "Leave policy 2024",
        "acme",
        ("employee", "finance", "admin"),
        "From 1 January 2024, full-time employees at Acme receive 20 days of paid leave each year. "
        "Carry-over is capped at 5 days. This policy replaces HR-Leave-2019.",
    ),
    PolicyDoc(
        "HR-Leave-2019",
        "Leave policy 2019 (superseded)",
        "acme",
        ("employee", "finance", "admin"),
        "Full-time employees receive 15 days of paid leave each year. This document was the leave "
        "policy until 31 December 2023. It remains in the corpus so a wrong retrieve can pick it.",
    ),
    PolicyDoc(
        "FIN-Expense-2024",
        "Expense receipts",
        "acme",
        ("finance", "admin"),
        "Finance staff may approve expense claims with a receipt under 50 pounds without a second "
        "approver. Claims of 50 pounds or more need a director. Meals are not refundable.",
    ),
    PolicyDoc(
        "LIC-Refund-2018",
        "Software licence refunds",
        "acme",
        ("employee", "finance", "admin"),
        "Unused software licences may be refunded within 14 days of purchase. This is not an expense "
        "claim and is not the meals policy.",
    ),
    PolicyDoc(
        "GLOBEX-Leave-2024",
        "Globex leave",
        "globex",
        ("employee", "finance", "admin"),
        "Globex employees receive 28 days of paid leave. Acme staff must never see this passage.",
    ),
)


def parse_actor(actor_id: str) -> Actor:
    return Actor.parse(actor_id)


def visible(actor: Actor) -> tuple[PolicyDoc, ...]:
    allowed = set(_ROLES[actor.role])
    return tuple(doc for doc in POLICIES if doc.tenant == actor.tenant and allowed.intersection(doc.roles))


_STOP = frozenset(
    {
        "a",
        "an",
        "the",
        "is",
        "are",
        "was",
        "were",
        "what",
        "who",
        "whom",
        "which",
        "how",
        "many",
        "do",
        "does",
        "did",
        "of",
        "for",
        "to",
        "in",
        "on",
        "at",
        "by",
        "from",
        "and",
        "or",
        "our",
        "i",
        "you",
        "we",
        "they",
    }
)


def _search_text(query: str) -> str:
    """Drop short and stop words so 'what is the X' does not match every passage that contains 'the'."""
    kept: list[str] = []
    for raw in query.replace("?", " ").replace(".", " ").split():
        token = "".join(char for char in raw.casefold() if char.isalnum())
        if len(token) >= 4 and token not in _STOP:
            kept.append(token)
    return " ".join(kept)


def retrieve(query: str, actor_id: str, *, limit: int = 3) -> tuple[Citation, ...]:
    """Lexical retrieve over the documents this login may see. Empty means the empty sentence."""
    actor = Actor.parse(actor_id)
    corpus = Corpus()
    for doc in visible(actor):
        corpus.add(Passage(passage_id=doc.passage_id, title=doc.title, text=doc.text))
    return corpus.retrieve(_search_text(query), limit=limit)


def inject(prompt: str, citations: tuple[Citation, ...]) -> str:
    """Passages tagged as untrusted documents. The model cannot change the filter; it already ran."""
    lines = [wrap("user", prompt), "Cite every passage you use by its id in square brackets."]
    for citation in citations:
        lines.append(wrap("document", citation.render()))
    return "\n".join(lines)
